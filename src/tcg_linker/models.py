"""データモデル。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


def is_linked_row(row_text: Optional[str]) -> bool:
    """商品リストの1行テキストから、その行が既に紐づけ済みかを判定する。
    紐づけ済み行には対応列に「商品解除」ボタンがある（未紐づけ行には無い）。
    これにより表示フィルタ（エラーリスト/すべて）に関係なく未紐づけ行だけを選べる。"""
    if not row_text:
        return False
    return "商品解除" in row_text


def normalize_number(s: Optional[str]) -> str:
    """収録番号を正規化する。'034 / 060' -> '034/060'。全角スラッシュや空白を吸収。"""
    if not s:
        return ""
    s = s.strip()
    s = s.replace("／", "/").replace(" ", "").replace("　", "")
    return s.upper()


def normalize_set(s: Optional[str]) -> str:
    """セット記号を正規化する。'SM-H' -> 'SMH'、'sm7a' -> 'SM7A'。ハイフン/空白除去＋大文字化。"""
    if not s:
        return ""
    import re
    return re.sub(r"[-\s　]", "", s).upper()


@dataclass
class ScannedItem:
    """撮影画像1件（＝商品リストの1行）。"""
    no: Optional[int]          # 画面上のNo.（分かれば）
    kanri_id: str              # 管理ID（UUID）
    image_url: str             # 撮影画像のフル解像度URL

    # 画像認識で埋める
    read_name: str = ""
    read_set: str = ""
    read_number: str = ""      # 収録番号（ソート） 例: 034/060
    read_rarity: str = ""
    read_confidence: float = 0.0
    read_raw: str = ""         # 認識の生応答（デバッグ用）


@dataclass
class Candidate:
    """商品検索でヒットした候補（商品マスタの1レコード）。"""
    name: str
    series: str                # シリーズ 例: SM
    set_code: str              # 収録 例: SM7a
    rarity: str
    sort_number: str           # ソート 例: 034/060
    image_url: str = ""
    row_index: int = -1        # 候補表での行位置（番号が無いカードのクリック用）

    @property
    def number_norm(self) -> str:
        return normalize_number(self.sort_number)


@dataclass
class Proposal:
    """1件の撮影画像に対する提案結果。"""
    item: ScannedItem
    decision: str              # "confirm" or "skip"
    reason: str                # 判定理由
    matched: Optional[Candidate] = None
    candidates_count: int = 0
    illustration_confidence: Optional[float] = None
    search_term_used: str = ""
    # 効果測定用の内訳時間（秒）
    dl_sec: float = 0.0
    ocr_sec: float = 0.0
    search_sec: float = 0.0
    # 商品マスタ照合の結果（参考・スキップ分類用）
    master_name: str = ""
    master_set: str = ""
    master_number: str = ""
    master_kind: str = ""   # exact / name_number / number_unique / ambiguous / not_found など
    needs_review: bool = False   # マスタで番号+名前が重複＝別版/ミラーの区別要（要確認）
