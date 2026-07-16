"""localrec の純粋関数テスト（OCR/OpenCV本体は不要）。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from tcg_linker.localrec import combine_similarity, parse_fields_from_texts


def test_parse_number_name_set():
    # ミミッキュ SM11b 028/049 C 相当のOCR断片
    texts = ["ミミッキュ", "HP70", "SM11b", "028/049", "C", "Illus. HYOGONOSUKE"]
    r = parse_fields_from_texts(texts)
    assert r["number"] == "028/049"
    assert r["name"] == "ミミッキュ"
    assert r["set"] == "SM11b"
    assert r["rarity"] == "C"
    assert r["confidence"] >= 0.8       # 番号も名前も取れた


def test_parse_fullwidth_slash():
    r = parse_fields_from_texts(["テンガン山", "130／131"])  # 全角スラッシュ
    assert r["number"] == "130/131"
    assert r["name"] == "テンガン山"


def test_parse_low_confidence_when_number_missing():
    r = parse_fields_from_texts(["ミミッキュ"])   # 番号読めず
    assert r["number"] == ""
    assert r["confidence"] <= 0.5


def test_parse_empty():
    r = parse_fields_from_texts([])
    assert r["number"] == "" and r["name"] == ""
    assert r["confidence"] < 0.3


def test_combine_similarity_range_and_weight():
    assert combine_similarity(1.0, 1.0) == 1.0
    assert combine_similarity(0.0, 0.0) == 0.0
    # ORBの重みが大きい（0.65:0.35）
    assert combine_similarity(1.0, 0.0) > combine_similarity(0.0, 1.0)
    # 範囲外入力はクランプ
    assert 0.0 <= combine_similarity(2.0, -1.0) <= 1.0


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"\n{len(fns)}/{len(fns)} tests passed")
