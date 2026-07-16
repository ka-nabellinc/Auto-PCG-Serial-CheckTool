"""executor（フェーズ2 書き込みオーケストレーション）の単体テスト。ブラウザ不要。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from tcg_linker.executor import execute_confirms, should_relink, summarize
from tcg_linker.models import Candidate, Proposal, ScannedItem


class FakeBrowser:
    def __init__(self, ok=True):
        self.ok = ok
        self.link_calls = []
        self.unlink_calls = []

    def link_candidate(self, kanri_id, term, sort_number):
        self.link_calls.append((kanri_id, term, sort_number))
        return self.ok

    def unlink(self, kanri_id):
        self.unlink_calls.append(kanri_id)
        return self.ok


def _prop(decision, number="028/049", name="ミミッキュ"):
    it = ScannedItem(no=1, kanri_id=f"id-{name}", image_url="")
    it.read_name = name
    it.read_number = number
    matched = Candidate(name, "", "SM11b", "C", number) if decision == "confirm" else None
    return Proposal(item=it, decision=decision, reason="", matched=matched,
                    candidates_count=1, search_term_used=name)


def test_dry_run_never_writes():
    br = FakeBrowser()
    props = [_prop("confirm"), _prop("skip"), _prop("confirm", name="テンガン山")]
    res = execute_confirms(props, br, allow_writes=False)
    assert br.link_calls == []                      # 書き込みゼロ
    statuses = [s for _, s in res]
    assert statuses.count("would_link") == 2
    assert statuses.count("skipped") == 1


def test_execute_links_only_confirms():
    br = FakeBrowser(ok=True)
    props = [_prop("confirm"), _prop("skip"), _prop("confirm", name="テンガン山", number="130/131")]
    res = execute_confirms(props, br, allow_writes=True)
    # confirm 2件だけ link、skip は呼ばれない
    assert len(br.link_calls) == 2
    assert ("id-ミミッキュ", "ミミッキュ", "028/049") in br.link_calls
    assert all(kid != "id-スキップ" for kid, _, _ in br.link_calls)
    assert summarize(res)["linked"] == 2
    assert summarize(res)["skipped"] == 1


def test_execute_link_failure_recorded():
    br = FakeBrowser(ok=False)
    res = execute_confirms([_prop("confirm")], br, allow_writes=True)
    assert summarize(res)["link_failed"] == 1


def test_confirm_without_matched_is_failure_not_write():
    br = FakeBrowser()
    p = _prop("confirm")
    p.matched = None
    res = execute_confirms([p], br, allow_writes=True)
    assert br.link_calls == []
    assert summarize(res)["link_failed"] == 1


def test_should_relink_only_on_confident_mismatch():
    assert should_relink({"match": False, "confidence": 0.9}, 0.7) is True
    assert should_relink({"match": True, "confidence": 0.9}, 0.7) is False   # 一致→解除しない
    assert should_relink({"match": False, "confidence": 0.3}, 0.7) is False  # 確信低→解除しない


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"\n{len(fns)}/{len(fns)} tests passed")
