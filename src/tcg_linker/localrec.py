"""完全ローカルの認識モジュール（Claude非依存）。

- read_card: 撮影画像 -> {name, set, number, rarity, confidence}  … ローカルOCR
- same_card: 撮影画像 vs 候補画像 -> {match, confidence, reason} … ローカル画像類似

外部送信なし・APIキー不要。OCRエンジンはPaddleOCR（pip導入・日本語対応）を既定に、
画像類似はOpenCV(ORB特徴量)＋perceptual hashで算出する。重い依存(paddle/cv2)は
メソッド内で遅延importするため、このモジュール自体は依存が無くてもimportできる
（純粋関数の単体テストが可能）。
"""
from __future__ import annotations

import re
from typing import Dict, List, Optional

# 収録番号 例: 034/060, 126 / 131
_NUM_RE = re.compile(r"(\d{1,3})\s*[/／]\s*(\d{1,3})")
# セット記号 例: SM7a, S8b, SM-H, SMJ, SM3N, s1a, s8b, S2, SM11b, s1W
# 観測されたコードはすべて S / SM / s 始まり。HP70 等を誤検出しないよう先頭を限定。
_SET_RE = re.compile(r"^(SM-?[A-Za-z0-9]{1,3}|[Ss][0-9][A-Za-z]?)$")
_JP_RE = re.compile(r"[ぁ-んァ-ヶ一-龠ー]")
# 文章っぽさ・カテゴリ語の判定用
_SENTENCE_PUNCT = "。「」、（）()・：:；;／/…"
# カード名ではない定型ラベル（シリーズごとに表記ゆれがあるため広めに）。
# ※ 最終的にはフォントサイズ（最大文字＝カード名）で選ぶので、これは補助フィルタ。
_NAME_STOPWORDS = {
    # トレーナーズ種別
    "グッズ", "サポート", "スタジアム", "どうぐ", "ポケモンのどうぐ", "トレーナーズ",
    "TRAINER'S", "TRAINERS", "グッズ／サポート",
    # 進化段階（半角/全角）
    "たね", "たねポケモン", "1進化", "2進化", "１進化", "２進化", "進化", "MEGA進化",
    # 下部ラベル・ワザ枠等
    "にげる", "にげろ", "よわ点", "弱点", "抵抗力", "ていこうりょく", "ワザ",
    "エネルギー", "基本エネルギー", "特殊エネルギー", "特性", "とくせい", "ルール",
    "ポケモン", "ポケパワー", "ポケボディー", "ENERGY",
    # 種別サフィックス等（単独で出た場合）
    "GX", "EX", "ex", "V", "VMAX", "VSTAR", "BREAK", "PRISM", "TAG", "TEAM",
}


def _is_number(t: str) -> bool:
    return bool(_NUM_RE.search(t))


def _jp_ratio(t: str) -> float:
    if not t:
        return 0.0
    return len(_JP_RE.findall(t)) / max(1, len(t))


def looks_like_name(t: str) -> bool:
    """カード名らしいトークンか（番号・本文・カテゴリ語・記号・英字のみ を除外）。"""
    t = (t or "").strip()
    if _is_number(t):
        return False
    if not (2 <= len(t) <= 16):
        return False
    if any(p in t for p in _SENTENCE_PUNCT):
        return False
    if t in _NAME_STOPWORDS:
        return False
    return _jp_ratio(t) >= 0.5


def parse_fields_from_texts(texts: List[str]) -> Dict:
    """OCRで得たテキスト断片リストから、カード名/セット/収録番号/レア度を推定する（純粋関数）。

    ヒューリスティック:
      - number: 最初に見つかる `NNN/NNN`。
      - set: セット記号パターンに合致し、数字比率が高すぎない短いトークン。
      - name: 日本語比率が高く、最も長いトークン（カード名は上部に大きく出る）。
      - rarity: 単独の C/U/R/RR/SR/HR/UR/AR/SAR 等。
    confidence: number と name の両方が取れれば高く、片方なら中、なければ低。
    """
    texts = [t.strip() for t in texts if t and t.strip()]
    number = ""
    for t in texts:
        m = _NUM_RE.search(t)
        if m:
            number = f"{m.group(1)}/{m.group(2)}"
            break

    def _clean_set(tok: str) -> str:
        # 収録番号(NNN/NNN)を除去し、数字直後の単独レア度letter(C/U/R)を剥がす
        tok = _NUM_RE.sub(" ", tok).strip()
        m = re.match(r"^(.*\d)([CUR])$", tok)
        if m:
            tok = m.group(1)
        return tok

    set_code = ""
    for t in texts:
        # トークンを空白で分割し、番号除去・レア度剥がし後にセット記号判定
        for part in _NUM_RE.sub(" ", t).split():
            cp = _clean_set(part)
            if cp and _SET_RE.match(cp) and any(c.isalpha() for c in cp):
                set_code = cp
                break
        if set_code:
            break

    rarity = ""
    for t in texts:
        tt = t.strip().upper()
        if tt in {"C", "U", "R", "RR", "SR", "HR", "UR", "AR", "SAR", "PR", "K"}:
            rarity = tt
            break

    # カード名（テキストのみ版のフォールバック）: 条件を満たす最初のトークン。
    # ※ read_card では別途「フォントサイズ最大の名前トークン」を優先（シリーズ非依存）。
    name = ""
    for t in texts:
        if looks_like_name(t):
            name = t.strip()
            break
    if not name:  # 日本語比率×長さが最大のトークン
        best = 0.0
        for t in texts:
            if _is_number(t):
                continue
            r = _jp_ratio(t)
            if r >= 0.4 and r * len(t) > best:
                best = r * len(t)
                name = t

    conf = 0.2
    if number and name:
        conf = 0.85
    elif number or name:
        conf = 0.5
    return {"name": name, "set": set_code, "number": number,
            "rarity": rarity, "confidence": conf,
            "_raw": " | ".join(texts)}


def hue_to_energy_type(hue: float, low_sat: bool, mean_v: float) -> str:
    """支配色からエネルギー種別を推定（純粋関数）。hueはOpenCV基準(0-179)。
    low_sat時は彩度が低い＝鋼(灰)/悪(黒)を明度で区別。該当なしは ''。"""
    if low_sat:
        # 彩度が低い: 明るい→鋼(銀灰) / 暗い→悪(黒)
        if mean_v >= 150:
            return "鋼"
        if mean_v <= 90:
            return "悪"
        return "鋼"  # 中間はひとまず鋼
    h = hue % 180
    if h < 12 or h >= 168:
        return "炎"     # 赤
    if h < 22:
        return "闘"     # 橙〜茶
    if h < 34:
        return "雷"     # 黄
    if h < 85:
        return "草"     # 緑
    if h < 125:
        return "水"     # 青
    if h < 150:
        return "超"     # 紫
    return "フェアリー"  # 桃 (150-168)


def best_design_match(confs, threshold: float = 0.45, margin: float = 0.04) -> int:
    """デザイン照合スコア列から一意に決まる最良候補のインデックスを返す（純粋関数）。
    最良が閾値以上で、かつ2位と十分な差(margin)があるときのみ採用。曖昧なら -1。"""
    if not confs:
        return -1
    order = sorted(range(len(confs)), key=lambda i: confs[i], reverse=True)
    best = order[0]
    if confs[best] < threshold:
        return -1
    if len(order) > 1 and (confs[best] - confs[order[1]]) < margin:
        return -1
    return best


def combine_similarity(orb_inlier: float, hist_corr: float, phash_sim: float) -> float:
    """3つの類似スコア(各0-1)を統合して0-1の信頼度にする（純粋関数）。
    - orb_inlier: 特徴点のRANSACインライア率（構図・絵柄の一致。主指標）
    - hist_corr : 色ヒストグラム相関（色調の一致）
    - phash_sim : perceptual hash 類似（全体印象）
    """
    o = max(0.0, min(1.0, orb_inlier))
    h = max(0.0, min(1.0, hist_corr))
    p = max(0.0, min(1.0, phash_sim))
    return round(0.55 * o + 0.25 * h + 0.20 * p, 3)


class LocalRecognizer:
    """Claude非依存のローカル認識器。Vision と同じ read_card / same_card を提供する。"""

    def __init__(self, cfg=None, ocr_engine: str = "paddleocr", ocr_lang: str = "japan"):
        self.ocr_engine = getattr(cfg, "ocr_engine", ocr_engine) if cfg else ocr_engine
        self.ocr_lang = ocr_lang
        self._ocr = None
        # 高速化: カード名(上帯)とセット/収録番号(下帯)だけOCRし、本文は読まない
        self.ocr_bands = getattr(cfg, "ocr_bands", True) if cfg else True
        # 高速化: 軽量(mobile)モデルを既定に。使えない環境では自動フォールバック。
        self.det_model = getattr(cfg, "ocr_det_model", "PP-OCRv5_mobile_det") if cfg else "PP-OCRv5_mobile_det"
        self.rec_model = getattr(cfg, "ocr_rec_model", "PP-OCRv5_mobile_rec") if cfg else "PP-OCRv5_mobile_rec"
        # イラスト一致とみなすしきい値（matcherと同じ値を使う）
        self.illus_threshold = 0.5
        try:
            self.illus_threshold = float(cfg.matching.illustration_min_confidence)
        except Exception:
            pass

    # ---- OCR ----
    def _get_ocr(self):
        if self._ocr is not None:
            return self._ocr
        if self.ocr_engine == "paddleocr":
            from paddleocr import PaddleOCR
            # PaddleOCR は 2.x / 3.x で引数が異なる（show_log廃止, use_angle_cls→use_textline_orientation）。
            # 高速化: doc向き判定/UVDoc歪み補正/textline向き判定を無効化し、検出＋認識のみにする。
            # 通る引数の組を順に試す。
            base = {"lang": self.ocr_lang, "use_doc_orientation_classify": False,
                    "use_doc_unwarping": False, "use_textline_orientation": False}
            fast = dict(base)
            if self.det_model:
                fast["text_detection_model_name"] = self.det_model
            if self.rec_model:
                fast["text_recognition_model_name"] = self.rec_model
            last_err = None
            for kwargs in (
                fast,                          # 3.x 軽量モデル指定＋前処理オフ
                base,                          # 3.x 前処理オフ（既定モデル）
                {"lang": self.ocr_lang},       # 3.x最小
                {"lang": self.ocr_lang, "use_angle_cls": False, "show_log": False},  # 2.x
            ):
                try:
                    self._ocr = PaddleOCR(**kwargs)
                    break
                except (TypeError, ValueError) as e:
                    last_err = e
            if self._ocr is None:
                raise last_err or RuntimeError("PaddleOCR初期化に失敗")
        else:  # tesseract
            import pytesseract  # noqa: F401
            self._ocr = "tesseract"
        return self._ocr

    @staticmethod
    def _extract_paddle_items(result):
        """PaddleOCRの戻り値から {text, poly} を取り出す（2.x/3.x両対応）。polyは座標 or None。"""
        items = []
        for page in result or []:
            rec = polys = None
            if isinstance(page, dict) or hasattr(page, "get"):
                try:
                    rec = page.get("rec_texts")
                    polys = (page.get("rec_polys") or page.get("dt_polys")
                             or page.get("rec_boxes"))
                except Exception:
                    rec = None
            if rec is not None:
                for i, t in enumerate(rec):
                    if not t:
                        continue
                    poly = polys[i] if (polys is not None and i < len(polys)) else None
                    items.append({"text": t, "poly": poly})
                continue
            if isinstance(page, (list, tuple)):  # 2.x: [[box,(text,conf)],...]
                for line in page:
                    try:
                        items.append({"text": line[1][0], "poly": line[0]})
                    except Exception:
                        pass
        return items

    @staticmethod
    def _poly_h_cy(poly):
        """polyから (高さ, 中心y) を返す。不明時は (0,0)。"""
        if poly is None:
            return 0.0, 0.0
        try:
            pts = list(poly)
            if pts and hasattr(pts[0], "__len__") and len(pts[0]) >= 2:  # [[x,y],...]
                ys = [float(p[1]) for p in pts]
                return max(ys) - min(ys), sum(ys) / len(ys)
            if len(pts) == 4:  # [x1,y1,x2,y2]
                return abs(float(pts[3]) - float(pts[1])), (float(pts[1]) + float(pts[3])) / 2
        except Exception:
            pass
        return 0.0, 0.0

    def _run_ocr_items(self, arr):
        """1枚の画像配列をOCRして {text, poly} のリストを返す。"""
        if self.ocr_engine == "paddleocr":
            ocr = self._get_ocr()
            result = None
            for call in ("predict", "ocr"):  # 3.x=predict / 2.x=ocr
                fn = getattr(ocr, call, None)
                if fn is None:
                    continue
                try:
                    result = fn(arr)
                    break
                except Exception:
                    continue
            return self._extract_paddle_items(result)
        else:
            import pytesseract
            self._get_ocr()
            txt = pytesseract.image_to_string(arr, lang="jpn+eng")
            return [{"text": ln, "poly": None} for ln in txt.splitlines() if ln.strip()]

    def _ocr_items(self, png: bytes):
        """撮影画像をOCRして (items, 上帯高さ) を返す。上帯高さ=カード名領域(combo座標)。"""
        import numpy as np
        import cv2
        arr = cv2.imdecode(np.frombuffer(png, np.uint8), cv2.IMREAD_COLOR)
        if arr is None:
            return [], 0
        h, w = arr.shape[:2]
        m = max(h, w)
        if m > 1600:
            s = 1600.0 / m
            arr = cv2.resize(arr, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA)
            h, w = arr.shape[:2]
        if self.ocr_bands:
            th = int(0.22 * h)
            combo = np.vstack([arr[0:th, :], arr[int(0.80 * h):h, :]])
            items = self._run_ocr_items(combo)
            if any(_NUM_RE.search(it["text"]) for it in items):
                return items, th   # combo座標で 0..th が上帯（名前領域）
        return self._run_ocr_items(arr), int(0.22 * h)

    def _pick_name_by_size(self, items, top_h) -> str:
        """上帯で最もフォントが大きい『カード名らしい』トークンを選ぶ（シリーズ非依存）。
        カード名は常にそのカードで最大級の文字なので、汎用ラベル(サポート/2進化等)に強い。"""
        best, best_score = "", -1.0
        for it in items:
            t = (it.get("text") or "").strip()
            if not looks_like_name(t):
                continue
            hgt, cy = self._poly_h_cy(it.get("poly"))
            if top_h and hgt > 0 and cy > top_h * 1.2:
                continue  # 下帯（番号/セット領域）は名前候補から除外
            score = hgt if hgt > 0 else 0.01  # poly無し時は順序フォールバック
            if score > best_score:
                best, best_score = t, score
        return best

    def read_card(self, scanned_png: bytes) -> Dict:
        try:
            items, top_h = self._ocr_items(scanned_png)
        except Exception as e:
            return {"name": "", "set": "", "number": "", "rarity": "",
                    "confidence": 0.0, "_raw": f"OCRエラー: {e}"}
        texts = [it["text"] for it in items]
        fields = parse_fields_from_texts(texts)
        # 名前はフォントサイズ最大の名前トークンで上書き（拾えた場合）
        name = self._pick_name_by_size(items, top_h)
        if name:
            fields["name"] = name
        return fields

    # ---- 画像照合（撮影→カード切り出し→正規化→照合）----
    _CARD_W = 360
    _CARD_H = 500  # ポケカの縦横比 ≈ 0.716

    @staticmethod
    def _decode(b: bytes):
        import numpy as np
        import cv2
        return cv2.imdecode(np.frombuffer(b, np.uint8), cv2.IMREAD_COLOR)

    def _crop_card(self, bgr):
        """写真から最大の四角形（カード）を検出して正面に補正し、正規化サイズで返す。
        検出できなければ画像全体をリサイズして返す（フォールバック）。"""
        import numpy as np
        import cv2
        W, H = self._CARD_W, self._CARD_H
        if bgr is None:
            return None
        h0, w0 = bgr.shape[:2]
        scale = 800.0 / max(h0, w0)
        small = cv2.resize(bgr, (int(w0 * scale), int(h0 * scale)))
        gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
        gray = cv2.GaussianBlur(gray, (5, 5), 0)
        edges = cv2.Canny(gray, 50, 150)
        edges = cv2.dilate(edges, np.ones((3, 3), np.uint8), iterations=1)
        cnts, _ = cv2.findContours(edges, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        quad = None
        area_min = 0.2 * small.shape[0] * small.shape[1]
        for c in sorted(cnts, key=cv2.contourArea, reverse=True)[:5]:
            if cv2.contourArea(c) < area_min:
                continue
            peri = cv2.arcLength(c, True)
            approx = cv2.approxPolyDP(c, 0.02 * peri, True)
            if len(approx) == 4:
                quad = approx.reshape(4, 2) / scale
                break
        if quad is None:
            return cv2.resize(bgr, (W, H))
        # 四隅を並べ替え
        s = quad.sum(axis=1)
        d = np.diff(quad, axis=1).reshape(-1)
        src = np.array([quad[np.argmin(s)], quad[np.argmin(d)],
                        quad[np.argmax(s)], quad[np.argmax(d)]], dtype="float32")
        dst = np.array([[0, 0], [W, 0], [W, H], [0, H]], dtype="float32")
        M = cv2.getPerspectiveTransform(src, dst)
        return cv2.warpPerspective(bgr, M, (W, H))

    def _orb_inlier_ratio(self, cardA, cardB) -> float:
        """ORB特徴点をRANSACホモグラフィで検証し、インライア率(0-1)を返す。"""
        import numpy as np
        import cv2
        ga = cv2.cvtColor(cardA, cv2.COLOR_BGR2GRAY)
        gb = cv2.cvtColor(cardB, cv2.COLOR_BGR2GRAY)
        orb = cv2.ORB_create(nfeatures=1000)
        ka, da = orb.detectAndCompute(ga, None)
        kb, db = orb.detectAndCompute(gb, None)
        if da is None or db is None or len(ka) < 8 or len(kb) < 8:
            return 0.0
        bf = cv2.BFMatcher(cv2.NORM_HAMMING)
        good = []
        for pair in bf.knnMatch(da, db, k=2):
            if len(pair) == 2 and pair[0].distance < 0.75 * pair[1].distance:
                good.append(pair[0])
        if len(good) < 8:
            return len(good) / max(1, min(len(ka), len(kb)))
        srcp = np.float32([ka[m.queryIdx].pt for m in good]).reshape(-1, 1, 2)
        dstp = np.float32([kb[m.trainIdx].pt for m in good]).reshape(-1, 1, 2)
        _, mask = cv2.findHomography(srcp, dstp, cv2.RANSAC, 5.0)
        inliers = int(mask.sum()) if mask is not None else 0
        return inliers / max(1, min(len(ka), len(kb)))

    def _hist_corr(self, cardA, cardB) -> float:
        """HSV色ヒストグラム相関(0-1)。イラスト領域（上半分）で比較。"""
        import cv2
        def art(c):
            h = c.shape[0]
            return c[int(0.10 * h):int(0.55 * h), :]  # 上部の絵柄帯
        ha = cv2.calcHist([cv2.cvtColor(art(cardA), cv2.COLOR_BGR2HSV)], [0, 1],
                          None, [50, 60], [0, 180, 0, 256])
        hb = cv2.calcHist([cv2.cvtColor(art(cardB), cv2.COLOR_BGR2HSV)], [0, 1],
                          None, [50, 60], [0, 180, 0, 256])
        cv2.normalize(ha, ha); cv2.normalize(hb, hb)
        corr = cv2.compareHist(ha, hb, cv2.HISTCMP_CORREL)
        return max(0.0, corr)

    def _phash_sim(self, cardA, cardB) -> float:
        import imagehash
        import cv2
        from PIL import Image
        pa = Image.fromarray(cv2.cvtColor(cardA, cv2.COLOR_BGR2RGB))
        pb = Image.fromarray(cv2.cvtColor(cardB, cv2.COLOR_BGR2RGB))
        ha, hb = imagehash.phash(pa), imagehash.phash(pb)
        return 1.0 - (ha - hb) / (len(ha.hash) ** 2)

    def classify_energy_type(self, scanned_png: bytes) -> str:
        """基本エネルギーの種別を『カードの色』で判定して返す（例 '炎'）。判定不可は ''。"""
        try:
            import numpy as np
            import cv2
            card = self._crop_card(self._decode(scanned_png))
            if card is None:
                return ""
            h0, w0 = card.shape[:2]
            # カード中央帯（枠・文字の影響を避け、地色/記号が支配的な領域）を使う
            roi = card[int(0.30 * h0):int(0.75 * h0), int(0.12 * w0):int(0.88 * w0)]
            hsv = cv2.cvtColor(roi, cv2.COLOR_BGR2HSV)
            hh, ss, vv = hsv[:, :, 0], hsv[:, :, 1], hsv[:, :, 2]
            mean_v = float(vv.mean())
            mask = (ss > 60) & (vv > 50) & (vv < 245)
            ratio = float(mask.sum()) / max(1, mask.size)
            if ratio < 0.05:  # ほぼ無彩色 → 鋼/悪
                return hue_to_energy_type(0.0, True, mean_v)
            hue_med = float(np.median(hh[mask]))
            return hue_to_energy_type(hue_med, False, mean_v)
        except Exception:
            return ""

    def same_card(self, scanned_png: bytes, candidate_img: bytes,
                  candidate_media_type: str = "image/jpeg") -> Dict:
        try:
            import cv2
            ca = self._crop_card(self._decode(scanned_png))
            cb0 = self._decode(candidate_img)
            cb = cv2.resize(cb0, (self._CARD_W, self._CARD_H))  # 公式画像はほぼ正面
            orb = self._orb_inlier_ratio(ca, cb)
            hist = self._hist_corr(ca, cb)
            ph = self._phash_sim(ca, cb)
        except Exception as e:
            return {"match": False, "confidence": 0.0, "reason": f"照合エラー: {e}"}
        conf = combine_similarity(orb, hist, ph)
        return {"match": conf >= self.illus_threshold, "confidence": conf,
                "reason": f"ORB={orb:.2f} Hist={hist:.2f} pHash={ph:.2f} -> {conf:.2f}"}
