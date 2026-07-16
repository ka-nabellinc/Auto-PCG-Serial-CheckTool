"""判定ロジック（純粋関数中心・単体テスト可能）。

確定条件（本測定 発見Aより）:
  - 「候補件数=1」では確定しない。撮影画像の収録番号と一致する候補が存在することが必須。
  - さらにイラスト照合も一致（require_illustration_match時）。
  - 満たさない場合はスキップ（誤紐づけを作らない）。
"""
from __future__ import annotations

from typing import Callable, List, Optional, Tuple

from .config import MatchingConfig
from .models import Candidate, ScannedItem, normalize_number, normalize_set

# 地方のすがた等の接頭辞（発見B）
_REGION_PREFIXES = ["アローラ", "ガラル", "ヒスイ", "パルデア"]


def build_search_terms(name: str, fallbacks: List[str]) -> List[str]:
    """設定のフォールバック順に検索語の候補を生成（重複除去・空除去）。"""
    name = (name or "").strip()
    terms: List[str] = []

    def add(t: str):
        t = t.strip()
        if t and t not in terms:
            terms.append(t)

    for kind in fallbacks:
        if kind == "full_name":
            add(name)
        elif kind == "strip_region":
            n = name
            for p in _REGION_PREFIXES:
                if n.startswith(p):
                    n = n[len(p):]
            add(n)
        elif kind == "last_token":
            # 空白（半角/全角）区切りの最後のトークン＝種名や特徴語
            parts = name.replace("　", " ").split(" ")
            if parts:
                add(parts[-1])
    if not terms:
        add(name)
    return terms


def find_number_matches(item: ScannedItem, candidates: List[Candidate],
                        target_number: Optional[str] = None) -> List[Candidate]:
    """収録番号と一致する候補を返す。target_number未指定時は撮影OCRの番号を使う。"""
    target = normalize_number(target_number if target_number is not None else item.read_number)
    if not target:
        return []
    return [c for c in candidates if c.number_norm == target]


def decide(
    item: ScannedItem,
    candidates: List[Candidate],
    cfg: MatchingConfig,
    illustration_check: Optional[Callable[[Candidate], Tuple[bool, float, str]]] = None,
    match_number: Optional[str] = None,
    match_set: Optional[str] = None,
) -> Tuple[str, str, Optional[Candidate], Optional[float]]:
    """判定を行い (decision, reason, matched_candidate, illust_confidence) を返す。

    match_number / match_set: 照合に使う収録番号・セット記号。
        マスタで正式カードを特定できた場合はマスタの値を渡す（OCRのセット誤読を吸収して確定へ）。
        未指定時は撮影OCRの read_number / read_set を使う。
    illustration_check: 候補を渡すと (match, confidence, reason) を返す関数。Noneで照合スキップ。
    """
    tgt_num = match_number if match_number is not None else item.read_number
    tgt_set = match_set if match_set is not None else item.read_set

    if not candidates:
        return "skip", "候補0件（検索でヒットせず）", None, None

    # 収録番号が無い場合は安全側でスキップ
    if cfg.require_number_match and not normalize_number(tgt_num):
        return "skip", "撮影画像の収録番号を読み取れず", None, None

    if cfg.require_number_match:
        num_matches = find_number_matches(item, candidates, tgt_num)
        if not num_matches:
            return (
                "skip",
                f"収録番号一致なし（撮影={tgt_num} / 候補={_nums(candidates)}）",
                None,
                None,
            )
        target_candidates = num_matches
    else:
        target_candidates = candidates

    # セット記号一致（収録番号＋セットで商品マスタ上ほぼ一意）
    if getattr(cfg, "require_set_match", False):
        rs = normalize_set(tgt_set)
        if not rs:
            # セットが読めない場合の保険: 番号一致候補が唯一ならそれで確定、
            # 複数なら（版の区別ができないので）スキップ
            if len(target_candidates) == 1:
                return "confirm", "収録番号一致（セット読取不可のため番号一意で確定）", target_candidates[0], None
            return "skip", "セット記号を読み取れず（番号一致候補が複数）", None, None
        set_matches = [c for c in target_candidates
                       if normalize_set(c.set_code) == rs]
        if not set_matches:
            cand_sets = ",".join(sorted({c.set_code for c in target_candidates})) or "なし"
            return "skip", f"セット記号一致なし（照合={tgt_set} / 候補={cand_sets}）", None, None
        target_candidates = set_matches

    # イラスト照合
    if cfg.require_illustration_match:
        if illustration_check is None:
            return "skip", "イラスト照合が実行できず（照合関数なし）", None, None
        scored: List[Tuple[float, Candidate, str]] = []
        for c in target_candidates:
            ok, conf, rsn = illustration_check(c)
            scored.append((conf, c, rsn))
        scored.sort(key=lambda x: x[0], reverse=True)
        best_conf, best_c, best_rsn = scored[0]
        thr = cfg.illustration_min_confidence
        passing = [s for s in scored if s[0] >= thr]
        if not passing:
            return ("skip",
                    f"イラスト照合が閾値未満（最良={best_conf:.2f}/閾値={thr}: {best_rsn}）",
                    best_c, best_conf)
        if len(passing) > 1:
            return "skip", f"イラスト一致候補が複数あり一意化できず（最良={best_conf:.2f}）", None, best_conf
        conf, c, rsn = passing[0]
        return "confirm", f"収録番号一致＋イラスト一致（{rsn}）", c, conf

    # イラスト照合は確定条件にしない: 番号＋セットで一意なら確定
    if len(target_candidates) == 1:
        gate = "収録番号＋セット一致" if getattr(cfg, "require_set_match", False) else "収録番号一致"
        return "confirm", gate, target_candidates[0], None
    return "skip", "収録番号＋セット一致が複数あり一意化できず", None, None


def _nums(candidates: List[Candidate]) -> str:
    return ",".join(c.sort_number for c in candidates[:5]) or "なし"
