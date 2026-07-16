"""matcher / models / report の単体テスト（ブラウザ・API不要）。"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from tcg_linker.config import MatchingConfig
from tcg_linker.matcher import build_search_terms, decide, find_number_matches
from tcg_linker.models import Candidate, Proposal, ScannedItem, is_linked_row, normalize_number
from tcg_linker.notify import build_skip_message
from tcg_linker.report import write_reports, write_skip_csv


def _item(number, name="ミミッキュ"):
    it = ScannedItem(no=1, kanri_id="a6b7daf8-0000-0000-0000-000000000000",
                     image_url="http://x/scan.png")
    it.read_name = name
    it.read_number = number
    it.read_set = "SM11b"
    it.read_rarity = "C"
    it.read_confidence = 0.9
    return it


def test_normalize_number():
    assert normalize_number("034 / 060") == "034/060"
    assert normalize_number("028／049") == "028/049"
    assert normalize_number(None) == ""


def test_is_linked_row_detects_unlink_button():
    # 「すべて」表示から始めても、紐づけ済み行([商品解除]あり)は未紐づけ抽出から除外できる
    linked = "1\tSM\tSM7a\tC\t034/060\tイワーク\ta6b7...\tID修正\t商品修正\t商品解除"
    unlinked = "2\t\t\t\t\t\t1162e3f0-...\tID修正\t商品修正"
    assert is_linked_row(linked) is True
    assert is_linked_row(unlinked) is False
    assert is_linked_row("") is False


def test_search_terms_region_and_lasttoken():
    terms = build_search_terms("アローラ ロコン",
                               ["full_name", "strip_region", "last_token"])
    assert terms[0] == "アローラ ロコン"
    assert "ロコン" in terms  # strip_region と last_token の両方でロコンになる
    # 重複排除されている
    assert len(terms) == len(set(terms))


def test_confirm_when_number_and_illustration_match():
    cfg = MatchingConfig(require_number_match=True, require_illustration_match=True,
                         illustration_min_confidence=0.7)
    item = _item("028/049")
    cands = [Candidate("ミミッキュ", "SM", "SM11b", "C", "028/049", "http://x/c.jpg")]
    d, reason, matched, conf = decide(item, cands, cfg,
                                      illustration_check=lambda c: (True, 0.95, "ok"))
    assert d == "confirm"
    assert matched.sort_number == "028/049"
    assert conf == 0.95


def test_skip_when_single_candidate_but_number_mismatch():
    # 本測定 発見A: 候補1件でも番号が違えばスキップ（誤紐づけ防止）
    cfg = MatchingConfig(True, True, 0.7)
    item = _item("019/060", name="インテレオン")  # 撮影は s1W 019/060
    cands = [Candidate("インテレオン", "S", "S4a", "-", "041/190", "http://x/c.jpg")]
    d, reason, matched, conf = decide(item, cands, cfg,
                                      illustration_check=lambda c: (True, 0.99, "ok"))
    assert d == "skip"
    assert "収録番号一致なし" in reason


def test_skip_when_no_candidates():
    cfg = MatchingConfig(True, True, 0.7)
    d, reason, _, _ = decide(_item("028/049"), [], cfg,
                             illustration_check=lambda c: (True, 1.0, ""))
    assert d == "skip"
    assert "候補0件" in reason


def test_skip_when_number_unreadable():
    cfg = MatchingConfig(True, True, 0.7)
    item = _item("")  # 番号読めず
    cands = [Candidate("ミミッキュ", "SM", "SM11b", "C", "028/049")]
    d, reason, _, _ = decide(item, cands, cfg, illustration_check=lambda c: (True, 1.0, ""))
    assert d == "skip"
    assert "収録番号を読み取れず" in reason


def test_skip_when_illustration_mismatch():
    cfg = MatchingConfig(True, True, 0.7)
    item = _item("028/049")
    cands = [Candidate("ミミッキュ", "SM", "SM11b", "C", "028/049", "http://x/c.jpg")]
    d, reason, _, _ = decide(item, cands, cfg,
                             illustration_check=lambda c: (False, 0.1, "違う絵"))
    assert d == "skip"
    assert "イラスト" in reason


def test_report_outputs_files():
    cfg = MatchingConfig(True, True, 0.7)
    item = _item("028/049")
    cands = [Candidate("ミミッキュ", "SM", "SM11b", "C", "028/049", "http://x/c.jpg")]
    d, reason, matched, conf = decide(item, cands, cfg,
                                      illustration_check=lambda c: (True, 0.9, "ok"))
    p = Proposal(item=item, decision=d, reason=reason, matched=matched,
                 candidates_count=1, illustration_confidence=conf, search_term_used="ミミッキュ")
    with tempfile.TemporaryDirectory() as d2:
        res = write_reports("920", [p], d2)
        assert os.path.exists(res["csv"])
        assert os.path.exists(res["html"])
        assert res["confirm"] == 1


def _skip_prop(no, name, num, cand_num):
    it = _item(num, name)
    it.no = no
    return Proposal(item=it, decision="skip",
                    reason=f"収録番号一致なし（撮影={num} / 候補={cand_num}）",
                    candidates_count=1, search_term_used=name)


def test_skip_csv_contains_only_skips():
    conf = _item("028/049"); conf.no = 9
    p_ok = Proposal(item=conf, decision="confirm", reason="ok",
                    matched=Candidate("ミミッキュ", "", "SM11b", "C", "028/049"),
                    candidates_count=1, illustration_confidence=0.9, search_term_used="ミミッキュ")
    p_skip = _skip_prop(21, "インテレオン", "019/060", "041/190")
    with tempfile.TemporaryDirectory() as d:
        path = write_skip_csv("920", [p_ok, p_skip], d)
        assert os.path.exists(path)
        with open(path, encoding="utf-8-sig") as f:
            body = f.read()
        assert "インテレオン" in body        # skipは含む
        assert "ミミッキュ" not in body       # confirmは含まない
        assert body.count("\n") == 2          # ヘッダ + skip1件（末尾改行）


def test_skip_message_lists_reasons():
    msg = build_skip_message("920",
                             [_skip_prop(21, "インテレオン", "019/060", "041/190"),
                              _skip_prop(23, "イトマル", "005/066", "006/095")],
                             "out/skips_920.csv")
    assert "スキップ 2 件" in msg
    assert "インテレオン" in msg and "イトマル" in msg
    assert "skips_920.csv" in msg


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = 0
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
        passed += 1
    print(f"\n{passed}/{len(fns)} tests passed")
