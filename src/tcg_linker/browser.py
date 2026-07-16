"""Playwrightで既存Chrome(CDP)に接続し、管理画面を操作する。

方針:
- 認証は既存のログイン済みChromeセッションを流用（CDP接続）。ID/PWは扱わない。
- 書き込みボタン（修正/商品解除/リスト確定/データ反映チェック/紐づけ取消/消去）は押さない。
- 読み取り: 未紐づけ行の管理ID一覧、および「商品修正」パネルの候補一覧。

注意: セレクタは観測したUI（日本語ラベル・列構成）に基づく。実DOMに合わせて微調整が必要な場合がある。
その際は _SEL 定数を修正すること。
"""
from __future__ import annotations

import time
from typing import List, Optional

from playwright.sync_api import sync_playwright, Page

from .models import Candidate

# --- 調整ポイント（実DOMに合わせて必要なら変更）---
_SEL = {
    # 表示フィルタのドロップダウン（「表示」ラベルの隣のselect）
    "filter_select": "select",
    "filter_value_error": "エラーリスト",
    # 商品修正パネル
    "panel": "text=商品修正 >> xpath=ancestor::*[self::div][1]",
    "search_label": "商品名",
    # ボタンラベル
    "btn_product_edit": "商品修正",
}


class AdminBrowser:
    def __init__(self, cdp_url: str, allow_writes: bool = False):
        """allow_writes=False（既定）の間は link_candidate/unlink は実行しない（安全側）。"""
        self._cdp_url = cdp_url
        self._pw = None
        self._browser = None
        self.allow_writes = allow_writes
        self.page: Optional[Page] = None

    def __enter__(self) -> "AdminBrowser":
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.connect_over_cdp(self._cdp_url)
        ctx = self._browser.contexts[0] if self._browser.contexts else self._browser.new_context()
        # 既存タブ（Meet等）に干渉しないよう、ツール専用の新規タブを開いて使う。
        # 同じプロファイルなのでログイン状態は共有される。
        self.page = ctx.new_page()
        self.page.bring_to_front()
        return self

    def __exit__(self, *exc):
        # 専用タブを閉じてからPlaywrightを切断（ブラウザ本体は閉じない）。
        try:
            if self.page:
                self.page.close()
        except Exception:
            pass
        try:
            if self._pw:
                self._pw.stop()
        except Exception:
            pass

    # ---- ナビゲーション ----
    def open_registration(self, url: str):
        # networkidle は常時通信(WebSocket等)があると来ないため domcontentloaded を使う
        self.page.goto(url, wait_until="domcontentloaded", timeout=60000)
        # 商品リストの描画を待つ（最大15秒）。出なくても続行。
        try:
            self.page.get_by_text("商品リスト").first.wait_for(timeout=15000)
        except Exception:
            self.page.wait_for_timeout(2000)

    def ensure_error_list_filter(self):
        """表示フィルタを『エラーリスト』（未紐づけのみ）にする。"""
        try:
            sel = self.page.locator(_SEL["filter_select"]).first
            sel.select_option(label=_SEL["filter_value_error"])
            self.page.wait_for_timeout(600)
        except Exception:
            # select_optionが効かない実装の場合はスキップ（既定でエラーリストのことが多い）
            pass

    # ---- 未紐づけ行の一覧 ----
    def read_unlinked_kanri_ids(self, paginate: bool = True) -> List[str]:
        """商品リスト表から『未紐づけ行だけ』の管理ID(UUID)を取得する。
        行ごとに判定し紐づけ済み行（[商品解除]あり）は除外するので、
        フィルタが『エラーリスト』でも『すべて』でも未紐づけだけを拾える。

        paginate=True: 番号ボタン(2,3,...)をクリックして全ページを巡回して集める（読み取り専用途）。
        paginate=False: 現在表示中のページのみ（書き込みと組み合わせる実行時用）。
        """
        seen: List[str] = []
        js = r"""
        () => {
          const t=document.querySelector('table'); if(!t) return [];
          const re=/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/i;
          const out=[];
          for(const r of t.querySelectorAll('tr')){
            const tx=r.innerText||''; if(tx.includes('商品解除')) continue;  // 紐づけ済みは除外
            const m=tx.match(re); if(m) out.push(m[0].toLowerCase());
          }
          return out;
        }
        """

        def collect_current():
            try:
                for v in (self.page.evaluate(js) or []):
                    if v not in seen:
                        seen.append(v)
            except Exception:
                pass

        collect_current()
        if paginate:
            # Vuetifyのページャ: ページ番号は <button> にテキストで入る。2,3,...を順に押す。
            p = 1
            for _ in range(60):
                nxt = self.page.get_by_role("button", name=str(p + 1), exact=True)
                if nxt.count() == 0:
                    break
                try:
                    if not nxt.first.is_visible():
                        break
                    nxt.first.click()
                    self.page.wait_for_timeout(700)
                    p += 1
                    collect_current()
                except Exception:
                    break
            # 後続処理のため1ページ目に戻す
            try:
                one = self.page.get_by_role("button", name="1", exact=True).first
                if one.count() > 0:
                    one.click()
                    self.page.wait_for_timeout(500)
            except Exception:
                pass
        return seen

    def goto_next_page(self) -> bool:
        """商品リストのページャで次ページへ進む。進めたらTrue、次が無ければFalse。"""
        try:
            cur = self.page.evaluate(
                "() => {const b=[...document.querySelectorAll('button')]"
                ".filter(x=>/^[0-9]+$/.test((x.innerText||'').trim()));"
                "const a=b.find(x=>x.className.includes('bg-primary'));"
                "return a?parseInt(a.innerText.trim()):null;}"
            )
        except Exception:
            cur = None
        if not cur:
            return False
        nxt = self.page.get_by_role("button", name=str(cur + 1), exact=True)
        if nxt.count() == 0:
            return False
        try:
            if not nxt.first.is_visible():
                return False
            nxt.first.click(timeout=6000)
            self.page.wait_for_timeout(700)
            return True
        except Exception:
            return False

    # ---- 候補検索（商品修正パネル） ----
    def search_candidates(self, kanri_id: str, term: str) -> List[Candidate]:
        """指定行の『商品修正』を開き、termで検索して候補一覧を読み取り、閉じる。書き込みはしない。"""
        self._open_product_edit(kanri_id)
        default_sig = self._sig(self._read_candidate_table())  # 検索前のデフォルト一覧
        self._type_search(term, avoid_sig=default_sig)
        cands = self._read_candidate_table()
        self._close_panel()
        return cands

    def _open_product_edit(self, kanri_id: str):
        row = self.page.locator("tr", has_text=kanri_id).first
        # 行が現在ページに無い場合は素早く失敗させる（30秒待たない）
        row.get_by_role("button", name=_SEL["btn_product_edit"]).first.click(timeout=6000)
        self.page.wait_for_timeout(300)

    @staticmethod
    def _sig(cands: List[Candidate]) -> str:
        """候補一覧の署名（先頭数件の名前+ソート）。絞り込みが効いたかの判定に使う。"""
        return "|".join(f"{c.name}:{c.sort_number}" for c in cands[:6])

    # パネルの「商品名」入力に確実に値を入れるJS（複数入力欄の中から最右=パネル内を選ぶ）。
    # 検索はクライアント側フィルタなのでネットワーク待ちは不要。inputイベントで発火する。
    _JS_SET_SEARCH = r"""
    (term) => {
      const ins=[...document.querySelectorAll('input')]
        .filter(i=>i.offsetParent!==null && (i.type===''||i.type==='text'));
      if(!ins.length) return false;
      ins.sort((a,b)=>b.getBoundingClientRect().left-a.getBoundingClientRect().left);
      const box=ins[0];  // 右端の可視テキスト入力＝スライドインしたパネルの商品名欄
      const setter=Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype,'value').set;
      setter.call(box,''); box.dispatchEvent(new Event('input',{bubbles:true}));
      setter.call(box,term);
      box.dispatchEvent(new Event('input',{bubbles:true}));
      box.dispatchEvent(new Event('change',{bubbles:true}));
      return true;
    }
    """

    def _type_search(self, term: str, avoid_sig: Optional[str] = None):
        # パネルの商品名欄にJSで直接入力（別欄への誤入力を防ぐ）。クライアント側フィルタは即時反映。
        try:
            self.page.evaluate(self._JS_SET_SEARCH, term)
        except Exception:
            pass
        self.page.wait_for_timeout(450)

    def _find_candidate_table(self):
        """商品修正パネル内の『候補表』だけを特定して返す。

        候補表ヘッダ: 商品名/シリーズ/収録/レア度/ソート/画像/修正
        本体テーブルヘッダ: No./撮影画像/商品画像/.../商品名/管理ID/対応/消去
        → 『修正』列があり、かつ『管理ID』『撮影』を含まないテーブルが候補表。
        """
        tables = self.page.locator("table")
        for i in range(tables.count()):
            t = tables.nth(i)
            try:
                head = t.locator("tr").first.inner_text()
            except Exception:
                continue
            if ("商品名" in head and "ソート" in head and "修正" in head
                    and "管理ID" not in head and "撮影" not in head
                    and "消去" not in head):
                return t
        return None

    # 候補表を「ページ内1回のJS実行」で読み取る（セルごとの通信往復を避けて高速化）
    _JS_READ_CANDIDATES = r"""
    () => {
      const tables=[...document.querySelectorAll('table')];
      const t=tables.find(tb=>{const h=tb.querySelector('tr'); if(!h)return false;
        const x=h.innerText; return x.includes('商品名')&&x.includes('ソート')&&x.includes('修正')
          && !x.includes('管理ID') && !x.includes('撮影') && !x.includes('消去');});
      if(!t) return [];
      return [...t.querySelectorAll('tr')].slice(1).map(r=>{
        const c=[...r.querySelectorAll('td')]; if(c.length<5)return null;
        const img=r.querySelector('img');
        const g=i=>(c[i]&&c[i].innerText||'').trim();
        return {name:g(0),series:g(1),set:g(2),rarity:g(3),sort:g(4),image:img?img.src:''};
      }).filter(Boolean);
    }
    """

    def _read_candidate_table(self) -> List[Candidate]:
        """パネル内候補表を1回のJS実行で読み取る。列: 商品名/シリーズ/収録/レア度/ソート/画像/修正。"""
        try:
            data = self.page.evaluate(self._JS_READ_CANDIDATES) or []
        except Exception:
            data = []
        return [Candidate(name=d.get("name", ""), series=d.get("series", ""),
                          set_code=d.get("set", ""), rarity=d.get("rarity", ""),
                          sort_number=d.get("sort", ""), image_url=d.get("image", ""),
                          row_index=i)
                for i, d in enumerate(data)]

    def _close_panel(self):
        # ×が見つからない時に30秒待たないよう短いタイムアウト＋Escapeフォールバック
        try:
            self.page.get_by_role("button", name="×").first.click(timeout=2500)
        except Exception:
            try:
                self.page.keyboard.press("Escape")
            except Exception:
                pass
        self.page.wait_for_timeout(250)

    # ---- 書き込み（フェーズ2）----
    # 押すのは候補の[修正]と行の[商品解除]のみ。
    # リスト確定/データ反映チェック/紐づけ取消/消去 は本ツールから操作しない。
    def link_candidate(self, kanri_id: str, term: str, sort_number: str = "",
                       row_index: int = -1) -> bool:
        """指定行の商品修正を開き、termで検索、対象候補の[修正]を押して紐づける。
        収録番号(sort_number)一致で特定するのが基本。番号が無い場合（基本エネルギー等）は
        デザイン照合で決めた row_index の行を押す。"""
        if not self.allow_writes:
            raise RuntimeError("allow_writes=False のため書き込みは禁止（dry-run）")
        from .models import normalize_number
        self._open_product_edit(kanri_id)
        default_sig = self._sig(self._read_candidate_table())
        self._type_search(term, avoid_sig=default_sig)
        cands = self._read_candidate_table()
        idx = -1
        target_num = normalize_number(sort_number)
        if target_num:
            idx = next((i for i, c in enumerate(cands)
                        if normalize_number(c.sort_number) == target_num), -1)
        if idx < 0 and 0 <= row_index < len(cands):
            idx = row_index   # 番号なし: デザイン照合で決めた行
        if idx >= 0:
            self.page.get_by_role("button", name="修正", exact=True).nth(idx).click()
            self.page.wait_for_timeout(700)
            return True
        self._close_panel()
        return False

    def list_linked_rows(self) -> List[dict]:
        """『すべて』表示に切り替え、紐づけ済み行（[商品解除]がある行）の
        {kanri_id, product_image_url} を返す（ミス検出用）。"""
        import re
        try:
            self.page.locator(_SEL["filter_select"]).first.select_option(label="すべて")
            self.page.wait_for_timeout(600)
        except Exception:
            pass
        uuid_re = re.compile(
            r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I
        )
        out: List[dict] = []
        rows = self.page.locator("table").first.locator("tr")
        for i in range(rows.count()):
            r = rows.nth(i)
            try:
                txt = r.inner_text()
            except Exception:
                continue
            if "商品解除" not in txt:
                continue
            m = uuid_re.search(txt)
            if not m:
                continue
            # 商品画像列のimg（撮影画像とは別の、紐づけ済み公式画像）。2枚目のimgを想定。
            imgs = r.locator("img")
            prod_img = ""
            if imgs.count() >= 2:
                prod_img = imgs.nth(1).get_attribute("src") or ""
            out.append({"kanri_id": m.group(0).lower(), "product_image_url": prod_img})
        return out

    def unlink(self, kanri_id: str) -> bool:
        """指定行の[商品解除]を押して紐づけを解除する。"""
        if not self.allow_writes:
            raise RuntimeError("allow_writes=False のため書き込みは禁止（dry-run）")
        row = self.page.locator("tr", has_text=kanri_id).first
        try:
            row.get_by_role("button", name="商品解除").first.click()
            self.page.wait_for_timeout(700)
            return True
        except Exception:
            return False
