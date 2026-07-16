"""Claude API による撮影画像の読み取りとイラスト照合。

- read_card: 撮影画像 -> {name, set, number, rarity, confidence}
- same_card: 撮影画像 と 候補画像 -> {match, confidence, reason}

APIキーはコードに持たず、Config経由（環境変数）で渡す。
"""
from __future__ import annotations

import base64
import json
import re
from typing import Dict

import anthropic

_READ_PROMPT = """あなたはポケモンカードの鑑定補助AIです。
渡された「撮影画像」（斜めから撮影され光沢・反射があることがある）から、カードを特定する情報を読み取ってください。
特にカード右下に小さく書かれた「セット記号」「収録番号」「レア度」を丁寧に読み取ること。

出力は次のJSONのみ（前後に文章を付けない）:
{
  "name": "カード名（日本語。地方のすがたは『アローラ ロコン』のように種名を含める）",
  "set": "セット記号（例 SM7a, SM-H, s1a など。読めなければ空文字）",
  "number": "収録番号（例 034/060。読めなければ空文字）",
  "rarity": "レア度（C/U/R/RR/SR等。無い場合や読めなければ空文字）",
  "confidence": 0.0
}
confidence は読み取り全体の自信度(0-1)。番号が読めない場合は低くすること。"""

_MATCH_PROMPT = """2枚の画像が「同一のポケモンカード（同じイラスト・同じ版）」かどうかを判定してください。
1枚目は査定用の撮影画像（斜め・光沢あり）、2枚目は商品マスタの公式カード画像です。
向きや光沢の違いは無視し、イラスト・キャラクター・構図が一致するかで判断してください。

出力は次のJSONのみ:
{ "match": true/false, "confidence": 0.0, "reason": "簡潔な理由" }"""


def _extract_json(text: str) -> dict:
    """応答からJSON部分を抽出してパース。"""
    text = text.strip()
    # ```json ... ``` を除去
    text = re.sub(r"^```(?:json)?", "", text).strip()
    text = re.sub(r"```$", "", text).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        text = text[start : end + 1]
    return json.loads(text)


def _img_block(data: bytes, media_type: str = "image/png") -> dict:
    return {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": media_type,
            "data": base64.standard_b64encode(data).decode("ascii"),
        },
    }


class Vision:
    def __init__(self, api_key: str, model: str = "claude-sonnet-5"):
        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = model

    def read_card(self, scanned_png: bytes) -> Dict:
        msg = self.client.messages.create(
            model=self.model,
            max_tokens=400,
            messages=[
                {
                    "role": "user",
                    "content": [_img_block(scanned_png), {"type": "text", "text": _READ_PROMPT}],
                }
            ],
        )
        raw = msg.content[0].text
        try:
            data = _extract_json(raw)
        except Exception:
            data = {"name": "", "set": "", "number": "", "rarity": "", "confidence": 0.0}
        data["_raw"] = raw
        return data

    def same_card(self, scanned_png: bytes, candidate_img: bytes,
                  candidate_media_type: str = "image/jpeg") -> Dict:
        msg = self.client.messages.create(
            model=self.model,
            max_tokens=300,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "【1枚目: 撮影画像】"},
                        _img_block(scanned_png, "image/png"),
                        {"type": "text", "text": "【2枚目: 商品マスタ画像】"},
                        _img_block(candidate_img, candidate_media_type),
                        {"type": "text", "text": _MATCH_PROMPT},
                    ],
                }
            ],
        )
        raw = msg.content[0].text
        try:
            data = _extract_json(raw)
        except Exception:
            data = {"match": False, "confidence": 0.0, "reason": "解析失敗"}
        return data
