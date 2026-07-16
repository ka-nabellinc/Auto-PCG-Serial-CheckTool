"""商品マスタ（画像認識reference CSV）を使ったローカル照合。

用途:
- OCRで読んだ (セット記号 + 収録番号) からカードを一意特定する（セット+番号はほぼ一意キー）。
- セット記号のOCR誤読は (収録番号 + カード名) で補正する。
- どうしても該当が無ければ「マスタ該当なし＝OCR誤読 or 入荷データ/対象外の疑い」と分類する。

CSV列: image_id, inventory_product_id, image_url, pokemon_id, expansion, serial, mirror,
        check_flag, series_abbreviation, expansion_mark, collection_number,
        rarity_abbreviation, product_name
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from .models import normalize_number, normalize_set


# 小書きかな → 大書きかな（OCRが小さい仮名を大きい仮名に誤読する対策）
_SMALL_KANA = str.maketrans({
    "ぁ": "あ", "ぃ": "い", "ぅ": "う", "ぇ": "え", "ぉ": "お",
    "っ": "つ", "ゃ": "や", "ゅ": "ゆ", "ょ": "よ", "ゎ": "わ", "ゕ": "か", "ゖ": "け",
    "ァ": "ア", "ィ": "イ", "ゥ": "ウ", "ェ": "エ", "ォ": "オ",
    "ッ": "ツ", "ャ": "ヤ", "ュ": "ユ", "ョ": "ヨ", "ヮ": "ワ", "ヵ": "カ", "ヶ": "ケ",
})


def _norm_name(s: Optional[str]) -> str:
    """名前照合用の正規化。空白除去・小文字化に加え、小書きかなを大書きに畳んで
    OCRの小仮名誤読（ハネッコ↔ハネツコ 等）を吸収する。"""
    if not s:
        return ""
    s = s.replace(" ", "").replace("　", "").strip().lower()
    return s.translate(_SMALL_KANA)


@dataclass
class MasterEntry:
    name: str
    set_code: str          # expansion_mark 例: SM7a, S1W, SMH
    number: str            # collection_number 例: 052/060
    rarity: str
    image_url: str
    product_id: str

    @property
    def set_norm(self) -> str:
        return normalize_set(self.set_code)

    @property
    def number_norm(self) -> str:
        return normalize_number(self.number)


class Master:
    def __init__(self):
        self.by_set_number: Dict[Tuple[str, str], MasterEntry] = {}
        self.by_number: Dict[str, List[MasterEntry]] = {}
        # 「セット記号+収録番号」が重複するキー集合＝同一セット内にミラー/エディション違い等の
        # 別商品が複数あり、機械では一意に決められない＝要確認。
        self.dup_set_number: set = set()
        # 参考: 「収録番号+商品名」重複（別セット含む）。診断用に保持（要確認判定には使わない）。
        self.dup_name_number: set = set()
        self.count = 0

    @classmethod
    def load(cls, csv_path: str) -> "Master":
        m = cls()
        name_num_count: Dict[Tuple[str, str], int] = {}
        set_num_count: Dict[Tuple[str, str], int] = {}
        with open(csv_path, "r", encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                e = MasterEntry(
                    name=(row.get("product_name") or "").strip(),
                    set_code=(row.get("expansion_mark") or "").strip(),
                    number=(row.get("collection_number") or "").strip(),
                    rarity=(row.get("rarity_abbreviation") or "").strip(),
                    image_url=(row.get("image_url") or "").strip(),
                    product_id=(row.get("inventory_product_id") or "").strip(),
                )
                if not e.number_norm:
                    continue
                m.count += 1
                m.by_set_number.setdefault((e.set_norm, e.number_norm), e)
                m.by_number.setdefault(e.number_norm, []).append(e)
                kn = (e.number_norm, _norm_name(e.name))
                name_num_count[kn] = name_num_count.get(kn, 0) + 1
                ks = (e.set_norm, e.number_norm)
                set_num_count[ks] = set_num_count.get(ks, 0) + 1
        m.dup_name_number = {k for k, c in name_num_count.items() if c > 1}
        m.dup_set_number = {k for k, c in set_num_count.items() if c > 1}
        return m

    def needs_review(self, entry: Optional[MasterEntry]) -> bool:
        """要確認か。『セット記号+収録番号』が重複（同一セット内にミラー/エディション違い等の
        別商品が複数）＝機械で一意に決められないカードのみ要確認とする。
        別セットに同名・同番号があるだけ（セットで一意化できる）ケースは要確認にしない。"""
        if not entry:
            return False
        return (entry.set_norm, entry.number_norm) in self.dup_set_number

    def lookup(self, read_set: str, read_number: str, read_name: str
               ) -> Tuple[Optional[MasterEntry], str]:
        """(entry, kind) を返す。
        kind: exact / name_number(セット補正) / number_unique / ambiguous / no_number / not_found
        """
        num = normalize_number(read_number)
        if not num:
            return None, "no_number"
        sset = normalize_set(read_set)

        # 1) セット+番号の一致（一意キー）
        e = self.by_set_number.get((sset, num))
        if e:
            return e, "exact"

        cands = self.by_number.get(num, [])
        if not cands:
            return None, "not_found"

        # 2) 番号一致の中から、カード名が一致するもの（セット記号のOCR誤読を補正）
        rn = _norm_name(read_name)
        if rn:
            named = [c for c in cands if _norm_name(c.name) == rn]
            if not named:
                named = [c for c in cands
                         if rn in _norm_name(c.name) or _norm_name(c.name) in rn]
            if len(named) == 1:
                return named[0], "name_number"
            if len(named) > 1:
                return None, "ambiguous"

        # 3) 番号だけで一意なら採用
        if len(cands) == 1:
            return cands[0], "number_unique"
        return None, "ambiguous"
