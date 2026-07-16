"""設定ロード。"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import List

import yaml


@dataclass
class MatchingConfig:
    require_number_match: bool = True
    require_illustration_match: bool = True      # 位置引数の既存テスト互換のためTrueのまま
    illustration_min_confidence: float = 0.45    # ローカル照合の初期値
    require_set_match: bool = False              # セット記号一致を確定条件に含めるか


@dataclass
class Config:
    admin_base_url: str
    s3_list_url: str
    image_base_url: str
    cdp_url: str
    matching: MatchingConfig
    search_fallbacks: List[str]
    output_dir: str
    # 認識バックエンド: "local"（既定・Claude非依存・OCR）/ "claude"（Claude API）
    recognition_backend: str = "local"
    ocr_engine: str = "paddleocr"       # local時のOCR: "paddleocr" / "tesseract"
    ocr_bands: bool = True              # 高速化: カード名帯+番号帯だけOCR（本文を読まない）
    ocr_det_model: str = "PP-OCRv5_mobile_det"  # 高速化: 軽量検出モデル（空で既定モデル）
    ocr_rec_model: str = "PP-OCRv5_mobile_rec"  # 高速化: 軽量認識モデル（空で既定モデル）
    anthropic_api_key_env: str = "ANTHROPIC_API_KEY"  # claude時のみ使用
    vision_model: str = "claude-sonnet-5"             # claude時のみ使用
    notify_popup_on_skip: bool = True   # スキップがあれば実行後にポップアップ通知
    master_csv: str = ""                # 商品マスタCSV（空で無効）。OCR照合・清書名検索・スキップ分類に使う
    skip_master_duplicates: bool = True  # マスタで番号+名前が重複するカードは自動確定せず要確認スキップ
    advisory_illustration: bool = False  # 確定時に参考イラストスコアを計算するか（重い。既定オフ）

    @property
    def anthropic_api_key(self) -> str:
        key = os.environ.get(self.anthropic_api_key_env, "")
        if not key:
            raise RuntimeError(
                f"環境変数 {self.anthropic_api_key_env} にClaude APIキーが設定されていません。"
            )
        return key

    def registration_url(self, reg_id: str) -> str:
        return f"{self.admin_base_url.rstrip('/')}/inventory/registrations/{reg_id}"

    def s3_list(self, reg_id: str) -> str:
        return self.s3_list_url.format(reg_id=reg_id)

    def image_url(self, key: str) -> str:
        return self.image_base_url.format(key=key)


def load_config(path: str) -> Config:
    with open(path, "r", encoding="utf-8") as f:
        raw = yaml.safe_load(f)
    m = raw.get("matching", {}) or {}
    return Config(
        admin_base_url=raw["admin_base_url"],
        s3_list_url=raw["s3_list_url"],
        image_base_url=raw["image_base_url"],
        cdp_url=raw["cdp_url"],
        recognition_backend=raw.get("recognition_backend", "local"),
        ocr_engine=raw.get("ocr_engine", "paddleocr"),
        ocr_bands=bool(raw.get("ocr_bands", True)),
        ocr_det_model=raw.get("ocr_det_model", "PP-OCRv5_mobile_det"),
        ocr_rec_model=raw.get("ocr_rec_model", "PP-OCRv5_mobile_rec"),
        anthropic_api_key_env=raw.get("anthropic_api_key_env", "ANTHROPIC_API_KEY"),
        vision_model=raw.get("vision_model", "claude-sonnet-5"),
        matching=MatchingConfig(
            require_number_match=m.get("require_number_match", True),
            require_illustration_match=m.get("require_illustration_match", False),
            illustration_min_confidence=float(m.get("illustration_min_confidence", 0.45)),
            require_set_match=m.get("require_set_match", True),
        ),
        search_fallbacks=raw.get("search_fallbacks", ["full_name"]),
        output_dir=raw.get("output_dir", "./out"),
        notify_popup_on_skip=bool(raw.get("notify_popup_on_skip", True)),
        advisory_illustration=bool(raw.get("advisory_illustration", False)),
        master_csv=raw.get("master_csv", ""),
        skip_master_duplicates=bool(raw.get("skip_master_duplicates", True)),
    )
