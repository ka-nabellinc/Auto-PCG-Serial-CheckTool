"""提案リストの出力（CSV + HTML）。書き込みは行わず、人間の確認用資料を作る。"""
from __future__ import annotations

import csv
import os
from typing import List

from .models import Proposal

_HTML_TMPL = """<!DOCTYPE html>
<html lang="ja"><head><meta charset="utf-8">
<title>紐づけ提案リスト reg={reg_id}</title>
<style>
 body{{font-family:sans-serif;margin:16px;}}
 table{{border-collapse:collapse;width:100%;}}
 th,td{{border:1px solid #ccc;padding:6px;font-size:13px;vertical-align:top;}}
 th{{background:#f3f3f3;}}
 .confirm{{background:#eaf7ea;}} .skip{{background:#fdeeee;}}
 img{{max-height:120px;}}
 .sum{{margin:8px 0;font-size:14px;}}
</style></head><body>
<h2>紐づけ提案リスト（reg={reg_id}）※提案のみ・自動書き込みなし</h2>
<div class="sum">合計 {total} 件 / 確定候補 {confirm} 件 / スキップ {skip} 件</div>
<table>
<tr><th>No</th><th>管理ID</th><th>撮影画像</th><th>読取(名/セット/番号/レア)</th>
<th>判定</th><th>提案商品</th><th>候補画像</th><th>理由</th><th>検索語</th></tr>
{rows}
</table></body></html>
"""

_ROW_TMPL = """<tr class="{cls}">
<td>{no}</td><td style="font-size:10px">{kanri}</td>
<td><img src="{scan}"></td>
<td>{rn}<br>{rs} {rnum} {rr}<br>conf={rc:.2f}</td>
<td><b>{decision}</b>{illus}</td>
<td>{mname}<br>{mset} {mnum} {mr}</td>
<td>{mimg}</td>
<td>{reason}</td><td>{term}</td></tr>"""


def _esc(s) -> str:
    s = "" if s is None else str(s)
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def write_reports(reg_id: str, proposals: List[Proposal], output_dir: str,
                  stamp: str = "") -> dict:
    os.makedirs(output_dir, exist_ok=True)
    base = f"{stamp}_{reg_id}_proposal" if stamp else f"proposal_{reg_id}"
    csv_path = os.path.join(output_dir, f"{base}.csv")
    html_path = os.path.join(output_dir, f"{base}.html")

    # CSV
    with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow([
            "No", "管理ID", "判定", "理由", "読取カード名", "読取セット", "読取収録番号",
            "読取レア度", "読取信頼度", "提案商品名", "提案セット", "提案収録番号",
            "候補件数", "イラスト信頼度", "検索語", "撮影画像URL", "候補画像URL",
        ])
        for p in proposals:
            it, m = p.item, p.matched
            w.writerow([
                it.no or "", it.kanri_id, p.decision, p.reason,
                it.read_name, it.read_set, it.read_number, it.read_rarity,
                f"{it.read_confidence:.2f}",
                m.name if m else "", m.set_code if m else "", m.sort_number if m else "",
                p.candidates_count,
                "" if p.illustration_confidence is None else f"{p.illustration_confidence:.2f}",
                p.search_term_used, it.image_url, m.image_url if m else "",
            ])

    # HTML
    rows = []
    for p in proposals:
        it, m = p.item, p.matched
        illus = "" if p.illustration_confidence is None else f"<br>illus={p.illustration_confidence:.2f}"
        rows.append(_ROW_TMPL.format(
            cls=p.decision, no=_esc(it.no or ""), kanri=_esc(it.kanri_id),
            scan=_esc(it.image_url),
            rn=_esc(it.read_name), rs=_esc(it.read_set), rnum=_esc(it.read_number),
            rr=_esc(it.read_rarity), rc=it.read_confidence,
            decision=_esc(p.decision), illus=illus,
            mname=_esc(m.name if m else "-"), mset=_esc(m.set_code if m else ""),
            mnum=_esc(m.sort_number if m else ""), mr=_esc(m.rarity if m else ""),
            mimg=(f'<img src="{_esc(m.image_url)}">' if (m and m.image_url) else "-"),
            reason=_esc(p.reason), term=_esc(p.search_term_used),
        ))
    n_conf = sum(1 for p in proposals if p.decision == "confirm")
    html = _HTML_TMPL.format(
        reg_id=_esc(reg_id), total=len(proposals), confirm=n_conf,
        skip=len(proposals) - n_conf, rows="\n".join(rows),
    )
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(html)

    return {"csv": csv_path, "html": html_path, "confirm": n_conf, "total": len(proposals)}


def write_skip_csv(reg_id: str, proposals: List[Proposal], output_dir: str,
                   stamp: str = "") -> str:
    """スキップ（要確認/手動対応）カードのチェック用CSVを出力し、パスを返す。
    stamp指定時はファイル名を『タイムスタンプ_紐づけID.csv』にする（履歴が残る）。"""
    os.makedirs(output_dir, exist_ok=True)
    name = f"{stamp}_{reg_id}.csv" if stamp else f"skips_{reg_id}.csv"
    path = os.path.join(output_dir, name)
    skips = [p for p in proposals if p.decision == "skip"]
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow([
            "紐づけID", "No", "管理ID", "要確認", "スキップ理由", "読取カード名",
            "読取セット", "読取収録番号", "読取レア度", "マスタ判定", "マスタ商品名",
            "マスタセット", "マスタ収録番号", "候補件数", "検索語", "撮影画像URL",
        ])
        for p in skips:
            it = p.item
            w.writerow([
                reg_id, it.no or "", it.kanri_id,
                "要確認" if p.needs_review else "",
                p.reason, it.read_name, it.read_set, it.read_number, it.read_rarity,
                p.master_kind, p.master_name, p.master_set, p.master_number,
                p.candidates_count, p.search_term_used, it.image_url,
            ])
    return path
