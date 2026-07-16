<<<<<<< HEAD
# tcg-linker（フェーズ1: 提案リスト出力ツール）

商品管理ID紐づけ画面の未紐づけカードについて、撮影画像をAIで読み取り→商品検索→
「収録番号一致＋イラスト照合」で判定し、**確定候補とスキップ理由の提案リスト（CSV/HTML）を出力**します。

**このツールは書き込みを一切行いません**（[修正]/[商品解除]/[リスト確定] 等は押さない）。
出力された提案リストを人間が確認し、実際の紐づけは管理画面上で人が行う運用です（フェーズ1＝半自動）。

## 判定ロジック（本測定の結果を反映）

各未紐づけ行について:

1. 撮影画像（S3のフル解像度PNG）をClaudeで読み取り、`カード名 / セット記号 / 収録番号 / レア度` を抽出。
2. カード名で商品検索（管理画面の「商品修正」パネル経由）。0件なら多段フォールバック検索
   （地方のすがた接頭辞の除去、種名/特徴語での部分検索）。
3. 判定:
   - **確定(confirm)**: 撮影画像の収録番号と一致する候補が存在し、かつイラスト照合も一致。
   - **スキップ(skip)**: 候補0件 / 収録番号を読めず / 収録番号一致なし / イラスト不一致 / 一意化不可。
   - 重要: 「候補が1件」でも収録番号が一致しなければスキップする（別版が返る誤紐づけを防ぐ）。

## セットアップ

```bash
pip install -e .                        # 依存を導入（playwright/paddleocr/opencv 等）
cp config.example.yaml config.yaml      # 既定は recognition_backend: local（Claude非依存）
```

認識は既定で**完全ローカル**（PaddleOCR＋OpenCV）です。APIキー・課金は不要で、撮影画像を外部に送りません。
初回のみOCRモデルを自動ダウンロードします。`recognition_backend: "claude"` に切り替えると Claude API を使う構成にもできます（その場合のみ `pip install -e ".[claude]"` と `export ANTHROPIC_API_KEY=...`）。

### 既存Chromeにデバッグ接続する（推奨）

ログイン済みのChromeを「リモートデバッグ有効」で起動し、そのセッションを流用します。
一度、管理画面に手動でログインしておいてください。

macOSの例:

```bash
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  --remote-debugging-port=9222 \
  --user-data-dir="$HOME/chrome-tcg-profile"
```

この専用プロファイルのChromeで https://admin.tcg-platform.com にログインしてから、ツールを実行します。
（`config.yaml` の `cdp_url` が `http://localhost:9222` を指していること）

## 実行

### フェーズ1: 提案のみ（書き込みなし・既定）

```bash
# まずは少数で試運転（例: 先頭10件）
python -m tcg_linker.main --reg 920 --config config.yaml --limit 10

# 全未紐づけを提案
python -m tcg_linker.main --reg 920 --config config.yaml
```

### フェーズ2: 自動実行（confirmを[修正]で紐づけ・書き込みあり）

```bash
# 初回は必ず少数で実機確認（確認プロンプトあり）
python -m tcg_linker.main --reg 920 --config config.yaml --mode execute --limit 3

# 精度確認後、無人実行（確認省略）
python -m tcg_linker.main --reg 920 --config config.yaml --mode execute --yes
```

execute モードは confirm 判定のカードだけを紐づけ、skip は書き込みません。
「リスト確定 / データ反映チェック / 紐づけ取消 / 消去」はツールから操作しないので、
仕上げは従来どおり人間が行います。**初回は必ず `--limit 3` で挙動を確認**してください。

出力は `config.yaml` の `output_dir`（既定 `./out`）に:
- `proposal_920.csv` … 判定結果一覧（Excelで開ける）
- `proposal_920.html` … 撮影画像・候補画像のサムネイル付きレビュー画面
- `skips_920.csv` … スキップ（手動対応が必要）カードだけの一覧。スキップがあれば実行後にポップアップ通知

## テスト

ブラウザ・API不要のコアロジック（判定・レポート）を単体テスト:

```bash
python tests/test_matcher.py
```

## 構成

```
src/tcg_linker/
  config.py    設定ロード（APIキーは環境変数から）
  models.py    データモデル（ScannedItem / Candidate / Proposal）
  images.py    S3の撮影画像一覧取得・ダウンロード（認証不要GET）
  vision.py    Claude API: 撮影画像の読み取り／イラスト照合
  browser.py   Playwright(CDP)で管理画面を操作（読み取り・検索のみ）
  matcher.py   判定ロジック（収録番号一致＋イラスト照合）
  report.py    提案リスト（CSV/HTML）出力
  main.py      CLIオーケストレーション
```

## 注意・既知の調整ポイント

- `browser.py` のセレクタは観測したUI（日本語ラベル・列構成）に基づく推定です。実DOMに合わせて
  `_SEL` 定数（表示フィルタのselect、商品修正ボタン、商品名入力、候補テーブル）を微調整してください。
  初回は `--limit 3` 程度で挙動を確認することを推奨します。
- ホログラム/反射の強いカードは収録番号が読みにくく、read_confidence が低め・スキップになりやすい
  傾向があります（本測定 発見D）。
- フェーズ2（確定条件を満たすものを自動で[修正]クリックまで実行）に進む際は、`browser.py` に
  「候補行の修正ボタンを押す」メソッドを追加し、`main.py` の confirm 判定時に呼び出す形になります。
  仕上げの「リスト確定/データ反映チェック」は引き続き人間が実施する想定です。
```
=======
# Auto-PCG-Serial-CheckTool
>>>>>>> 6230cf841d1167281dbcd65a10625ac90716acf3
