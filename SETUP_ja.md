# セットアップ手順（macOS）

このツールは「お手元のMac」で動かします。以下を上から順に実行してください。
ターミラル（アプリ →「ターミナル」）を開いて進めます。

---

## 0. 前提

- Python 3.9 以上（`python3 --version` で確認。無ければ https://www.python.org からインストール）
- Google Chrome

> このツールは**完全ローカル**で動きます（Claude非依存）。撮影画像の認識はローカルOCR（PaddleOCR）＋
> ローカル画像照合で行うため、**APIキーや課金は不要**、撮影画像を外部サービスに送りません。
> 初回だけOCRモデル（オープンソース）を自動ダウンロードします（以後はオフラインでも動作）。

---

## 1. プロジェクトを置く

ダウンロードした `tcg-linker.zip` を解凍し、分かりやすい場所（例：ホーム直下）に置きます。
**以降のコマンドは、この `tcg-linker` フォルダの中で実行します**（＝コマンドを打つディレクトリはここ）。

```bash
# 例: ダウンロードフォルダのzipをホームに解凍
cd ~
unzip ~/Downloads/tcg-linker.zip -d ~
cd ~/tcg-linker        # ← 以降ずっとこのディレクトリで作業
pwd                    # /Users/あなた/tcg-linker と出ればOK
```

> どのディレクトリで実行するか迷ったら「`config.yaml` と `src` フォルダが見える場所」＝`tcg-linker` の直下、が答えです。

---

## 2. Python環境を用意して依存をインストール

```bash
cd ~/tcg-linker
python3 -m venv .venv          # 仮想環境を作成
source .venv/bin/activate      # 有効化（プロンプト先頭に (.venv) が付く）
pip install -e .               # 依存(playwright/paddleocr/opencv等)を導入。数分かかることあり
```

> `python -m playwright install chromium` は不要です（お手元のログイン済みChromeにデバッグ接続するため）。
> `pip install -e .` は PaddleOCR/OpenCV などを含むため、初回は少し時間がかかります。

---

## 3. 設定ファイル

```bash
cd ~/tcg-linker
cp config.example.yaml config.yaml     # 設定ファイルを作成（既定 recognition_backend: local のままでOK）
```

> ローカル認識が既定なので、APIキーの設定は不要です。

---

## 4. ログイン済みChromeを「デバッグモード」で起動

ツールはこのChromeのログインセッションを流用します（ID/PWはツールに渡しません）。
**普段使いのChromeとは別プロファイル**で起動するのが安全です。

```bash
"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome" \
  --remote-debugging-port=9222 \
  --user-data-dir="$HOME/chrome-tcg-profile"
```

- 上記で開いたChromeで https://admin.tcg-platform.com にログインしておく。
- このChromeは起動したままにして、次の手順へ。

---

## 5. まず3件だけ試運転（推奨）

別のターミナルタブ（`.venv` を有効化し、`~/tcg-linker` にいる状態）で:

```bash
cd ~/tcg-linker
source .venv/bin/activate
python -m tcg_linker.main --reg 920 --config config.yaml --mode execute --limit 3
```

- 判定が流れ、確認プロンプト（yes/no）が出ます。`yes` で3件だけ紐づけ。
- 問題なければ、件数を広げる／全件へ。

---

## 6. 本番（末尾まで）

```bash
# まず全件ドライラン（書き込みなしで確定/スキップを確認）
python -m tcg_linker.main --reg 920 --config config.yaml

# 問題なければ実行（末尾まで自動。--yes で確認省略）
python -m tcg_linker.main --reg 920 --config config.yaml --mode execute
```

出力（`out/` フォルダ）:
- `proposal_920.html` / `.csv` … 判定一覧
- `skips_920.csv` … スキップ（手動対応が必要）カード。スキップがあればポップアップ通知

---

## つまずいたら

- `command not found: python` → `python3` で試す。
- 候補の[修正]が押せない等でうまく動かない → まず `--limit 3` で挙動を確認し、
  `src/tcg_linker/browser.py` の `_SEL`（セレクタ）を実画面に合わせて微調整。
- Chromeに繋がらない → デバッグ起動（手順4）のChromeが開いているか、`config.yaml` の
  `cdp_url` が `http://localhost:9222` か確認。
