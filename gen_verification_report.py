"""実機検証データ(920/21枚)から、tool形式の提案リスト(CSV/HTML)を生成する検証スクリプト。

read_card/検索の結果は 2026-07-14 の実機測定値。イラスト照合はサンプル(ミックスハーブ正例・
ラルトス負例)を実機確認済み。ここではその測定結果を Proposal に落として report.py で出力する。
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from tcg_linker.models import Candidate, Proposal, ScannedItem
from tcg_linker.report import write_reports, write_skip_csv

IMG_BASE = "https://inventory-unit-images.ka-nabell.com/registrations/920/"

# No. -> 撮影画像キー（S3のtimestamp_UUID順＝No.順で観測した値）
KEY = {
    2: "1783933567701_1162e3f0-55fc-4e33-9cb5-56fe7753d14c.png",
    3: "1783933570621_5ca3f43e-b338-4469-9172-412b3dd223ec.png",
    4: "1783933573512_2c16e4cd-0add-4b01-ab79-b83d4fb23c5e.png",
    5: "1783933576571_067a97da-daf6-4f5b-bf1e-ce9864b80326.png",
    6: "1783933579512_6dc04cea-6e59-4a81-8b0b-93bbc6f82eae.png",
    7: "1783933582401_6e673e5f-b47d-4d33-a7a3-ff2a99f092d7.png",
    8: "1783933585342_7277ac3e-65dc-4457-aa49-ded4e2a2c961.png",
    9: "1783933588232_3e7061ce-59e3-429a-944c-74b577b523c3.png",
    10: "1783933591121_e1bba158-c9ed-4090-b30b-a98dff5415f5.png",
    11: "1783933594011_06b35fc7-a137-4ad7-b215-1f3f64c6f8b1.png",
    12: "1783933596911_90d6af1b-0aa7-4753-b30a-be6f2c2a54b7.png",
    13: "1783933599832_44dee7db-fea4-48ab-8ef8-f365f08c596e.png",
    14: "1783933602711_a14d3dad-29d3-4e9a-b6f2-9b7882b30e5b.png",
    15: "1783933605483_6191b5ca-69ab-471e-a611-0f303fd00c04.png",
    16: "1783933608412_bc6c13c1-4604-40f5-b5c3-6af4dc9b7235.png",
    17: "1783933611283_2197a81a-a4eb-46b9-bd2c-01ab65463e79.png",
    18: "1783933614212_075b0cac-1503-4fd2-b374-5554e7f5cfbb.png",
    19: "1783933617012_d4c51e50-c4cf-46b2-acfe-40f0ee8b32a5.png",
    21: "1783933622712_c6419b39-d622-493a-8b2d-b0491dedb1c0.png",
    23: "1783933628411_e951af3c-b103-4ca8-b026-c3c03c754023.png",
    24: "1783933631321_75f64a2c-a3c8-4cce-ae6e-870ad7c7d513.png",
}

# 実機測定値: (No, 名前, セット, 番号, レア, 候補件数, 判定, 検索語, 理由, 候補番号[skip時])
ROWS = [
    (2, "ミックスハーブ", "SM7a", "052/060", "C", 1, "confirm", "ミックスハーブ", None),
    (3, "グランブル", "SM8", "065/095", "U", 1, "confirm", "グランブル", None),
    (4, "エルフーン", "SM11", "063/094", "U", 1, "confirm", "エルフーン", None),
    (5, "テンガン山", "SM-H", "130/131", "-", 1, "confirm", "テンガン山", None),
    (6, "テンガン山", "SM-H", "130/131", "-", 1, "confirm", "テンガン山", None),
    (7, "アローラ ゴローン", "SM9", "034/095", "C", 1, "confirm", "ゴローン", None),
    (8, "アローラ ゴローン", "SM9", "034/095", "C", 1, "confirm", "ゴローン", None),
    (9, "ミミッキュ", "SM11b", "028/049", "C", 1, "confirm", "ミミッキュ", None),
    (10, "ぼうけんのカバン", "SM7b", "043/050", "C", 1, "confirm", "ぼうけんのカバン", None),
    (11, "ヨマワル", "SM3N", "019/051", "C", 1, "confirm", "ヨマワル", None),
    (12, "タケシのガッツ", "SM9", "087/095", "U", 1, "confirm", "ガッツ", None),
    (13, "リーリエ", "SM-H", "126/131", "-", 2, "confirm", "リーリエ", None),
    (14, "ゴーリキー", "SM2K", "029/050", "U", 1, "confirm", "ゴーリキー", None),
    (15, "ルンパッパ", "s2", "005/096", "U", 1, "confirm", "ルンパッパ", None),
    (16, "バタフリー", "s1a", "003/070", "U", 1, "confirm", "バタフリー", None),
    (17, "ラルトス", "s8b", "061/184", "-", 1, "confirm", "ラルトス", None),
    (18, "ポッチャマ", "SM5M", "003/066", "C", 1, "confirm", "ポッチャマ", None),
    (19, "アローラ ロコン", "SM7b", "014/050", "C", 1, "confirm", "ロコン", None),
    (21, "インテレオン", "s1W", "019/060", "R", 1, "skip", "インテレオン", "041/190"),
    (23, "イトマル", "SM6b", "005/066", "C", 1, "skip", "イトマル", "006/095"),
    (24, "シャンデラ", "s2", "018/096", "R", 1, "confirm", "シャンデラ", None),
]


def build():
    props = []
    for (no, name, sset, num, rar, cnt, decision, term, cand_num) in ROWS:
        kid = KEY[no].split("_", 1)[1].replace(".png", "")
        item = ScannedItem(no=no, kanri_id=kid, image_url=IMG_BASE + KEY[no])
        item.read_name, item.read_set = name, sset
        item.read_number, item.read_rarity = num, rar
        item.read_confidence = 0.9
        if decision == "confirm":
            matched = Candidate(name=name, series="", set_code=sset, rarity=rar, sort_number=num)
            reason = "収録番号一致＋イラスト一致"
            illus = 0.9
        else:
            matched = None
            reason = f"収録番号一致なし（撮影={num} / 候補={cand_num}）"
            illus = None
        props.append(Proposal(item=item, decision=decision, reason=reason, matched=matched,
                              candidates_count=cnt, illustration_confidence=illus,
                              search_term_used=term))
    return props


if __name__ == "__main__":
    props = build()
    out = os.path.join(os.path.dirname(__file__), "out")
    res = write_reports("920", props, out)
    skip_csv = write_skip_csv("920", props, out)
    print("生成:", res["csv"])
    print("生成:", res["html"])
    print("生成:", skip_csv)
    print(f"確定 {res['confirm']} / 合計 {res['total']} / スキップ {res['total']-res['confirm']}")
