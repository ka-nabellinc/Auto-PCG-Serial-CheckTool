"""フェーズ2: 書き込み実行のオーケストレーション（ブラウザ非依存・単体テスト可能）。

安全設計:
- allow_writes=False（既定・dry-run）では一切クリックせず「would_link」を返す。
- confirm 以外は絶対に書き込まない。
- 書き込みは「候補の[修正]」と「行の[商品解除]」のみ。
  リスト確定 / データ反映チェック / 紐づけ取消 / 消去 は本ツールから操作しない（人間が実施）。
"""
from __future__ import annotations

from typing import Callable, List, Optional, Protocol, Tuple

from .models import Proposal


class LinkWriter(Protocol):
    """browser.AdminBrowser が満たすインターフェース（テストでは差し替え可能）。"""
    def link_candidate(self, kanri_id: str, term: str, sort_number: str = "",
                       row_index: int = -1) -> bool: ...
    def unlink(self, kanri_id: str) -> bool: ...


def execute_confirms(
    proposals: List[Proposal],
    writer: LinkWriter,
    allow_writes: bool,
    log: Callable[[str], None] = print,
) -> List[Tuple[Proposal, str]]:
    """confirm のものだけ [修正] をクリックして紐づける。

    戻り値: [(proposal, status)] status in {"linked","link_failed","would_link","skipped"}
    """
    results: List[Tuple[Proposal, str]] = []
    for p in proposals:
        if p.decision != "confirm":
            results.append((p, "skipped"))
            continue
        if p.matched is None:
            results.append((p, "link_failed"))
            log(f"  [!] confirmだが候補情報なし: {p.item.kanri_id}")
            continue
        if not allow_writes:
            results.append((p, "would_link"))
            log(f"  [dry-run] link {p.item.read_name} -> {p.matched.sort_number}")
            continue
        try:
            ok = writer.link_candidate(p.item.kanri_id, p.search_term_used,
                                       p.matched.sort_number,
                                       getattr(p.matched, "row_index", -1))
        except Exception as e:  # noqa
            ok = False
            log(f"  [!] link例外 {p.item.kanri_id}: {e}")
        results.append((p, "linked" if ok else "link_failed"))
        log(f"  {'[OK]' if ok else '[NG]'} link {p.item.read_name} -> {p.matched.sort_number}")
    return results


def should_relink(match_result: dict, min_confidence: float) -> bool:
    """紐づけ済み行のミス検出: 撮影 vs 商品画像 が『不一致』と十分な確信度で判定されたら
    解除→再紐づけの対象（True）。判定不能/一致なら False（現状維持）。"""
    matched = bool(match_result.get("match"))
    conf = float(match_result.get("confidence", 0.0) or 0.0)
    if matched:
        return False
    # 「不一致」でしかも確信度が高いときのみ解除対象にする（誤って解除しないため）
    return conf >= min_confidence


def summarize(results: List[Tuple[Proposal, str]]) -> dict:
    out = {"linked": 0, "would_link": 0, "link_failed": 0, "skipped": 0}
    for _, s in results:
        out[s] = out.get(s, 0) + 1
    return out
