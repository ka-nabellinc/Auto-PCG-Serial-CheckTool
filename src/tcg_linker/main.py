"""CLIエントリポイント（フェーズ1: 提案のみ・書き込みなし）。

使い方:
  python -m tcg_linker.main --reg 920 --config config.yaml [--limit 30]
"""
from __future__ import annotations

import argparse
import sys
import time
import traceback
from functools import lru_cache
from typing import List, Optional, Tuple

from .browser import AdminBrowser
from .config import load_config
from .executor import execute_confirms, summarize
from .images import download_bytes, list_scan_keys, map_kanri_id_to_url
from .matcher import build_search_terms, decide
from .models import Candidate, Proposal, ScannedItem, normalize_number
from .notify import build_skip_message, show_popup
from .report import write_reports, write_skip_csv


def _build_recognizer(cfg):
    """認識器を設定に応じて生成。local=OCR(Claude非依存) / claude=Claude API。"""
    if cfg.recognition_backend == "claude":
        from .vision import Vision
        return Vision(cfg.anthropic_api_key, cfg.vision_model)
    from .localrec import LocalRecognizer
    return LocalRecognizer(cfg)


def _media_type(url: str) -> str:
    u = url.lower()
    if u.endswith(".png"):
        return "image/png"
    if u.endswith(".webp"):
        return "image/webp"
    return "image/jpeg"


def run(reg_id: str, config_path: str, limit: Optional[int] = None,
        mode: str = "propose", assume_yes: bool = False,
        all_pages: bool = False, notify: bool = True) -> dict:
    """mode='propose'（既定・書き込みなし・全ページ巡回）／'execute'（confirmを[修正]で紐づけ）。
    all_pages=True かつ execute のとき、未紐づけが尽きるまでパスを繰り返す（末尾まで）。"""
    cfg = load_config(config_path)
    recognizer = _build_recognizer(cfg)
    print(f"      認識バックエンド: {cfg.recognition_backend}"
          + (f"（OCR={cfg.ocr_engine}）" if cfg.recognition_backend == "local" else ""))

    master = None
    if cfg.master_csv:
        from .master import Master
        master = Master.load(cfg.master_csv)
        print(f"      商品マスタ読込: {master.count} 件（{cfg.master_csv}）")

    # 1) 撮影画像の一覧（S3）
    print(f"[1/4] S3から撮影画像一覧を取得: reg={reg_id}")
    keys = list_scan_keys(cfg.s3_list(reg_id))
    id2url = map_kanri_id_to_url(keys, cfg.image_base_url)
    print(f"      画像 {len(id2url)} 件")

    all_proposals: List[Proposal] = []
    exec_total = {"linked": 0, "would_link": 0, "link_failed": 0, "skipped": 0}
    url = cfg.registration_url(reg_id)
    t_start = time.time()
    processed = 0   # 判定した枚数（効果測定の分母）

    print(f"[2/4] Chrome(CDP)に接続  mode={mode}"
          + ("  (--all: 末尾まで繰り返し)" if (all_pages and mode == "execute") else ""))

    with AdminBrowser(cfg.cdp_url, allow_writes=False) as br:

        def process_kids(kids: List[str]) -> List[Proposal]:
            nonlocal processed
            props: List[Proposal] = []
            for idx, kid in enumerate(kids, 1):
                processed += 1
                t_item = time.time()
                try:
                    prop = _process_item(br, recognizer, cfg, reg_id, idx, kid, id2url, master)
                except Exception as e:  # 1件失敗しても続行
                    traceback.print_exc()
                    item = ScannedItem(no=idx, kanri_id=kid, image_url=id2url.get(kid, ""))
                    prop = Proposal(item=item, decision="skip",
                                    reason=f"処理エラー: {e}", candidates_count=0)
                props.append(prop)
                print(f"      [{idx}/{len(kids)}] {prop.item.read_name or '?'} "
                      f"-> {prop.decision} ({prop.reason}) "
                      f"[計{time.time() - t_item:.1f}s = DL{prop.dl_sec:.1f}/OCR{prop.ocr_sec:.1f}/検索{prop.search_sec:.1f}]")
            return props

        if mode == "propose":
            # ドライラン: 別ページの行はパネルを開けないため、ページごとに読みながら処理する
            br.open_registration(url)
            br.ensure_error_list_filter()
            page = 1
            while True:
                kids = br.read_unlinked_kanri_ids(paginate=False)  # 現在ページのみ
                if limit:
                    remain = limit - len(all_proposals)
                    if remain <= 0:
                        break
                    kids = kids[:remain]
                print(f"[3/4] ページ{page}: 未紐づけ {len(kids)} 行を判定")
                all_proposals.extend(process_kids(kids))
                if limit and len(all_proposals) >= limit:
                    break
                if not br.goto_next_page():
                    break
                page += 1
        else:  # execute: 表示中ページ(1ページ目)を処理→再読込、を --all で繰り返す
            pass_no = 0
            while True:
                pass_no += 1
                br.open_registration(url)
                br.ensure_error_list_filter()
                kids = br.read_unlinked_kanri_ids(paginate=False)  # 表示中ページのみ
                if limit:
                    kids = kids[:limit]
                print(f"[3/4] pass{pass_no}: 未紐づけ(現ページ) {len(kids)} 行を判定")
                if not kids:
                    print("      未紐づけは残っていません。")
                    break
                proposals = process_kids(kids)
                all_proposals.extend(proposals)
                confirms = [p for p in proposals if p.decision == "confirm"]
                print(f"\n[execute pass{pass_no}] 確定候補 {len(confirms)} 件"
                      f"（スキップ {len(proposals) - len(confirms)} 件は書き込みません）")
                proceed = assume_yes or _confirm_prompt(len(confirms))
                if not proceed:
                    print("      中止しました（書き込みなし）。")
                    break
                br.allow_writes = True
                res_exec = execute_confirms(confirms, br, allow_writes=True)
                br.allow_writes = False
                s = summarize(res_exec)
                for k in exec_total:
                    exec_total[k] += s.get(k, 0)
                print("      実行結果:", s)
                if not all_pages:
                    break
                if s.get("linked", 0) == 0:
                    print("      これ以上自動確定できる未紐づけはありません（残りは要手動）。")
                    break

    # 重複（パス跨ぎで再出現したスキップ等）は管理IDで一意化（最後の判定を採用）
    uniq: dict = {}
    for p in all_proposals:
        uniq[p.item.kanri_id] = p
    proposals_final = list(uniq.values())

    # 4) レポート出力＋スキップ通知（ファイル名にタイムスタンプを付与し履歴を残す）
    print("[4/4] 提案リストを出力")
    stamp = time.strftime("%Y%m%d_%H%M%S", time.localtime(t_start))
    res = write_reports(reg_id, proposals_final, cfg.output_dir, stamp=stamp)
    skip_csv = write_skip_csv(reg_id, proposals_final, cfg.output_dir, stamp=stamp)
    skips = [p for p in proposals_final if p.decision == "skip"]
    print(f"      提案CSV : {res['csv']}")
    print(f"      提案HTML: {res['html']}")
    print(f"      スキップCSV: {skip_csv}（{len(skips)}件）")
    print(f"      確定 {res['confirm']} / 合計 {res['total']}")
    if mode == "execute":
        print(f"      実行合計: {exec_total}")

    # 効果測定: 総時間と1枚あたり
    elapsed = time.time() - t_start
    per = elapsed / processed if processed else 0.0
    mm, ss = divmod(int(elapsed), 60)
    print(f"[時間] 処理 {processed} 枚 / 総時間 {mm}分{ss}秒 / 1枚あたり {per:.1f} 秒")
    # 内訳の平均（どこがボトルネックか）
    if proposals_final:
        n = len(proposals_final)
        avg_dl = sum(p.dl_sec for p in proposals_final) / n
        avg_ocr = sum(p.ocr_sec for p in proposals_final) / n
        avg_srch = sum(p.search_sec for p in proposals_final) / n
        print(f"[内訳/枚] DL {avg_dl:.1f}s / OCR {avg_ocr:.1f}s / 検索 {avg_srch:.1f}s "
              f"（残りはブラウザ遷移等）")
    res["processed"] = processed
    res["elapsed_sec"] = round(elapsed, 1)
    res["sec_per_card"] = round(per, 2)

    if skips and cfg.notify_popup_on_skip and notify:
        msg = build_skip_message(reg_id, skips, skip_csv)
        how = show_popup(f"紐づけスキップ通知 (reg {reg_id})", msg)
        print(f"      スキップ通知を表示（{how}）")

    res["skip_csv"] = skip_csv
    res["skips"] = len(skips)
    res["executed"] = exec_total
    return res


def _confirm_prompt(n_confirm: int) -> bool:
    """実書き込み前の確認。'yes' を入力したときのみ True。"""
    try:
        ans = input(f"  {n_confirm} 件を実際に紐づけます。よろしいですか？ (yes/no) > ").strip().lower()
    except EOFError:
        return False
    return ans in ("yes", "y")


def _process_basic_energy(br, recognizer, cfg, kid: str, item: ScannedItem,
                          scanned: bytes, dl_sec: float, ocr_sec: float) -> Proposal:
    """基本エネルギー専用の確定処理（デザイン照合）。

    基本エネルギーはシリアル番号を持たず、種別は色（エネルギー記号）で決まる。
    「基本」で検索して出てきた候補（各種・各版）の画像と撮影画像を照合し、
    一意に決まる最一致候補を確定する。番号が無いので row_index で行をクリックする。
    一意化できなければ要確認スキップ（誤紐づけは絶対に作らない）。
    色判定（classify_energy_type）は理由文の補助ヒントとしてのみ使う。
    """
    from .localrec import best_design_match

    energy_type = ""
    try:
        energy_type = recognizer.classify_energy_type(scanned) or ""
    except Exception:
        energy_type = ""
    if energy_type:
        item.read_name = f"基本{energy_type}エネルギー"
    et = f"基本{energy_type}エネルギー" if energy_type else "基本エネルギー"

    _t = time.time()
    candidates: List[Candidate] = br.search_candidates(kid, "基本")
    scored: List[Tuple[float, Candidate]] = []
    for c in candidates:
        conf = 0.0
        if c.image_url:
            try:
                data, mt = download_bytes(c.image_url), _media_type(c.image_url)
                r = recognizer.same_card(scanned, data, mt)
                conf = float(r.get("confidence", 0.0) or 0.0)
            except Exception:
                conf = 0.0
        scored.append((conf, c))
    search_sec = time.time() - _t

    order = sorted(range(len(scored)), key=lambda i: scored[i][0], reverse=True)
    confs = [scored[i][0] for i in order]
    top_txt = " / ".join(
        f"{scored[i][1].name}"
        f"{('・' + scored[i][1].set_code) if scored[i][1].set_code else ''}"
        f"={scored[i][0]:.2f}" for i in order[:3]) or "候補なし"
    thr = float(getattr(cfg.matching, "illustration_min_confidence", 0.45))
    bi = best_design_match(confs, threshold=thr, margin=0.04)

    common = dict(candidates_count=len(candidates), search_term_used="基本",
                  dl_sec=round(dl_sec, 2), ocr_sec=round(ocr_sec, 2),
                  search_sec=round(search_sec, 2))
    if not candidates:
        return Proposal(item=item, decision="skip",
                        reason=f"{et}: 「基本」検索で候補なし（要確認）",
                        needs_review=True, **common)
    if bi >= 0:
        best = scored[order[bi]][1]
        best_conf = confs[bi]
        return Proposal(
            item=item, decision="confirm",
            reason=(f"{et}: デザイン照合で確定"
                    f"（{best.name} {best.set_code} 一致度{best_conf:.2f} / 上位: {top_txt}）"),
            matched=best, illustration_confidence=best_conf, **common)
    return Proposal(item=item, decision="skip",
                    reason=f"{et}: デザイン照合で一意化できず・要確認（上位: {top_txt}）",
                    needs_review=True, **common)


def _process_item(br: AdminBrowser, recognizer, cfg, reg_id: str,
                  idx: int, kid: str, id2url: dict, master=None) -> Proposal:
    img_url = id2url.get(kid)
    item = ScannedItem(no=idx, kanri_id=kid, image_url=img_url or "")

    # 撮影画像が一覧に無い場合はきれいにスキップ（誤ったURLを叩かない）
    if not img_url:
        return Proposal(item=item, decision="skip",
                        reason="撮影画像がS3一覧に見つからず（未アップロード/対象外の可能性）",
                        candidates_count=0)

    # 撮影画像を読み取り（内訳時間を計測）。取得失敗もスキップに倒す（例外で止めない）
    _t = time.time()
    try:
        scanned = download_bytes(img_url)
    except Exception as e:
        return Proposal(item=item, decision="skip",
                        reason=f"撮影画像の取得に失敗（{e}）", candidates_count=0,
                        dl_sec=round(time.time() - _t, 2))
    dl_sec = time.time() - _t

    _t = time.time()
    read = recognizer.read_card(scanned)
    ocr_sec = time.time() - _t
    item.read_name = read.get("name", "") or ""
    item.read_set = read.get("set", "") or ""
    item.read_number = read.get("number", "") or ""
    item.read_rarity = read.get("rarity", "") or ""
    item.read_confidence = float(read.get("confidence", 0.0) or 0.0)
    item.read_raw = read.get("_raw", "")

    # 基本エネルギーはシリアル番号が無く、種別は「色（エネルギー記号）」で決まるため
    # OCR文字では一意化できない。専用の『デザイン（画像）照合』分岐で確定する:
    #   OCRで基本エネルギーと判定 →「基本」で検索 → 各候補画像と撮影画像を照合 → 最一致を確定。
    raw = item.read_raw or ""
    if ("基本" in raw and "エネルギ" in raw):
        return _process_basic_energy(br, recognizer, cfg, kid, item, scanned,
                                     dl_sec, ocr_sec)

    # 商品マスタ照合（あれば）: 正式名で検索できるようにし、スキップ分類にも使う
    m_entry, m_kind = (None, "")
    if master is not None:
        m_entry, m_kind = master.lookup(item.read_set, item.read_number, item.read_name)

    # 検索キーワードは「マスタ側に存在するカード名」を使う（OCRで読んだ名前では検索しない）。
    # OCR名はマスタ引き当て（番号+名前でのセット補正）にのみ使用する。
    if master is not None:
        if m_entry:
            search_terms = [m_entry.name]          # 特定できた正式名で検索
        else:
            # 特定できない場合は、収録番号が一致するマスタのカード名で検索（OCR名は使わない）
            num = normalize_number(item.read_number)
            names: List[str] = []
            for e in master.by_number.get(num, []):
                if e.name and e.name not in names:
                    names.append(e.name)
            search_terms = names
    else:
        # マスタ未使用時のみOCR名の多段フォールバック（従来動作）
        search_terms = build_search_terms(item.read_name, cfg.search_fallbacks)

    # 多段検索
    _t = time.time()
    candidates: List[Candidate] = []
    used_term = ""
    seen_terms = set()
    for term in search_terms:
        if not term or term in seen_terms:
            continue
        seen_terms.add(term)
        candidates = br.search_candidates(kid, term)
        used_term = term
        if candidates:
            break
    search_sec = time.time() - _t

    # イラスト照合クロージャ（候補画像をDLしてClaudeで同一判定）
    @lru_cache(maxsize=64)
    def _cand_bytes(url: str) -> Tuple[bytes, str]:
        return download_bytes(url), _media_type(url)

    def illustration_check(c: Candidate):
        if not c.image_url:
            return (False, 0.0, "候補画像URLなし")
        data, mt = _cand_bytes(c.image_url)
        r = recognizer.same_card(scanned, data, mt)
        return (bool(r.get("match")), float(r.get("confidence", 0.0) or 0.0),
                r.get("reason", ""))

    # マスタで正式カードを特定できたら、その「セット・番号」で照合（OCRセット誤読を吸収）
    match_number = m_entry.number if m_entry else None
    match_set = m_entry.set_code if m_entry else None
    decision, reason, matched, illus_conf = decide(
        item, candidates, cfg.matching,
        illustration_check if cfg.matching.require_illustration_match else None,
        match_number=match_number, match_set=match_set,
    )
    # イラストを確定条件にしない場合でも、参考スコアを計算して残す（目視材料）
    # ただし重いので既定オフ（advisory_illustration: true のときだけ）
    if (decision == "confirm" and matched is not None and illus_conf is None
            and getattr(cfg, "advisory_illustration", False)):
        try:
            ok, conf, _ = illustration_check(matched)
            illus_conf = conf
            reason = f"{reason}（参考イラスト={conf:.2f}）"
        except Exception:
            pass
    # マスタで「番号+名前」が重複するカードは別版/ミラーの区別がつかないため要確認スキップ
    needs_review = bool(master is not None and m_entry is not None and master.needs_review(m_entry))
    if needs_review and getattr(cfg, "skip_master_duplicates", True):
        decision = "skip"
        reason = (f"要確認（マスタで『セット+番号』重複＝ミラー/版違い等で一意化不可: "
                  f"{m_entry.name} {m_entry.set_code} {m_entry.number}）自動確定を保留")
        matched = None

    # スキップ理由をマスタ照合で分類（OCR誤読か、入荷/対象外の疑いか）
    if decision == "skip" and not needs_review and master is not None:
        if m_entry:
            reason = f"{reason} ／マスタには存在（{m_entry.name} {m_entry.set_code} {m_entry.number}）＝画面検索側の要確認"
        else:
            reason = f"{reason} ／マスタ該当なし（OCR誤読 or 入荷データ・対象外の疑い）"

    return Proposal(
        item=item, decision=decision, reason=reason, matched=matched,
        candidates_count=len(candidates), illustration_confidence=illus_conf,
        search_term_used=used_term,
        dl_sec=round(dl_sec, 2), ocr_sec=round(ocr_sec, 2), search_sec=round(search_sec, 2),
        master_name=(m_entry.name if m_entry else ""),
        master_set=(m_entry.set_code if m_entry else ""),
        master_number=(m_entry.number if m_entry else ""),
        master_kind=m_kind,
        needs_review=needs_review,
    )


def main(argv=None):
    ap = argparse.ArgumentParser(description="商品紐づけ 提案リスト出力ツール（提案のみ）")
    ap.add_argument("--reg", required=True, help="紐づけID（例 920）")
    ap.add_argument("--config", default="config.yaml", help="設定ファイル")
    ap.add_argument("--limit", type=int, default=None, help="処理件数の上限（試運転用）")
    ap.add_argument("--mode", choices=["propose", "execute"], default="propose",
                    help="propose=提案のみ(既定・書き込みなし) / execute=confirmを[修正]で自動紐づけ")
    ap.add_argument("--yes", action="store_true",
                    help="execute時の確認プロンプトを省略（無人実行）。取り扱い注意")
    ap.add_argument("--all", dest="all_pages", action="store_true",
                    help="execute時、未紐づけが尽きるまでパスを繰り返す（末尾まで処理）")
    args = ap.parse_args(argv)
    try:
        run(args.reg, args.config, args.limit, mode=args.mode,
            assume_yes=args.yes, all_pages=args.all_pages)
    except Exception as e:
        print(f"エラー: {e}", file=sys.stderr)
        traceback.print_exc()
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
