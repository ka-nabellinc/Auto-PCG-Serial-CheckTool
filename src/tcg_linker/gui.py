"""ターミナル不要のGUI（tkinter）。非エンジニア向け。

使い方: このGUIを起動 → 紐づけID入力 → [実行] → 進捗表示 → 完了（CSV保存）。
Chromeのデバッグ起動もアプリが自動で行うため、利用者はコマンドを打つ必要がない。
"""
from __future__ import annotations

import os
import queue
import sys
import threading
import traceback

import tkinter as tk
from tkinter import messagebox, scrolledtext, ttk

from .chrome_launcher import ensure_debug_chrome
from .config import load_config
from .main import run


def _default_config_path() -> str:
    """config.yaml を、実行ファイル/スクリプトの隣→カレント の順で探す。"""
    bases = []
    if getattr(sys, "frozen", False):  # PyInstaller実行ファイル
        bases.append(os.path.dirname(sys.executable))
    bases.append(os.getcwd())
    bases.append(os.path.dirname(os.path.abspath(__file__)))
    for b in bases:
        p = os.path.join(b, "config.yaml")
        if os.path.exists(p):
            return p
    return "config.yaml"


class _QueueWriter:
    """print出力をキューへ流す（GUIスレッドで安全に表示するため）。"""
    def __init__(self, q):
        self.q = q

    def write(self, s):
        if s:
            self.q.put(("log", s))

    def flush(self):
        pass


class App:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.q: "queue.Queue" = queue.Queue()
        self.running = False
        root.title("商品紐づけ ツール")
        root.geometry("720x520")

        frm = ttk.Frame(root, padding=10)
        frm.pack(fill="both", expand=True)

        row = ttk.Frame(frm)
        row.pack(fill="x")
        ttk.Label(row, text="紐づけID：").pack(side="left")
        self.reg_var = tk.StringVar()
        self.reg_entry = ttk.Entry(row, textvariable=self.reg_var, width=16)
        self.reg_entry.pack(side="left")
        self.reg_entry.focus()

        self.mode_var = tk.StringVar(value="propose")
        ttk.Radiobutton(row, text="確認のみ（書き込まない）", variable=self.mode_var,
                        value="propose").pack(side="left", padx=(16, 4))
        ttk.Radiobutton(row, text="実行（紐づける）", variable=self.mode_var,
                        value="execute").pack(side="left")

        btnrow = ttk.Frame(frm)
        btnrow.pack(fill="x", pady=8)
        self.run_btn = ttk.Button(btnrow, text="実行", command=self.on_run)
        self.run_btn.pack(side="left")
        self.open_btn = ttk.Button(btnrow, text="出力フォルダを開く",
                                   command=self.open_output, state="disabled")
        self.open_btn.pack(side="left", padx=8)
        self.status = ttk.Label(btnrow, text="")
        self.status.pack(side="left", padx=8)

        self.log = scrolledtext.ScrolledText(frm, height=22, font=("Menlo", 11))
        self.log.pack(fill="both", expand=True)

        self.output_dir = None
        self.root.after(100, self._poll)

    # ---- ログ表示 ----
    def _append(self, text: str):
        self.log.insert("end", text)
        self.log.see("end")

    def _poll(self):
        try:
            while True:
                kind, payload = self.q.get_nowait()
                if kind == "log":
                    self._append(payload)
                elif kind == "done":
                    self._on_done(payload)
                elif kind == "error":
                    self._on_error(payload)
        except queue.Empty:
            pass
        self.root.after(100, self._poll)

    # ---- 実行 ----
    def on_run(self):
        if self.running:
            return
        reg = self.reg_var.get().strip()
        if not reg:
            messagebox.showwarning("入力エラー", "紐づけIDを入力してください。")
            return
        mode = self.mode_var.get()
        cfg_path = _default_config_path()
        if not os.path.exists(cfg_path):
            messagebox.showerror("設定エラー",
                                 f"config.yaml が見つかりません。\n探した場所: {cfg_path}")
            return
        if mode == "execute":
            if not messagebox.askyesno(
                "確認",
                f"紐づけID {reg} のカードを実際に紐づけます。よろしいですか？\n"
                "（確認のみで内容を先に見たい場合は『確認のみ』を選んでください）"):
                return

        self.running = True
        self.run_btn.config(state="disabled")
        self.open_btn.config(state="disabled")
        self.status.config(text="実行中…")
        self.log.delete("1.0", "end")
        t = threading.Thread(target=self._worker, args=(reg, cfg_path, mode), daemon=True)
        t.start()

    def _worker(self, reg, cfg_path, mode):
        old_out, old_err = sys.stdout, sys.stderr
        sys.stdout = sys.stderr = _QueueWriter(self.q)
        try:
            cfg = load_config(cfg_path)
            ok = ensure_debug_chrome(cfg.cdp_url, log=lambda s: self.q.put(("log", s + "\n")))
            if not ok:
                raise RuntimeError(
                    "Chromeのデバッグ起動に失敗しました。Chromeがインストールされているか確認してください。")
            res = run(reg, cfg_path, mode=mode,
                      assume_yes=(mode == "execute"), all_pages=(mode == "execute"),
                      notify=False)
            res["_output_dir"] = cfg.output_dir
            self.q.put(("done", res))
        except Exception as e:
            traceback.print_exc()
            self.q.put(("error", str(e)))
        finally:
            sys.stdout, sys.stderr = old_out, old_err

    def _on_done(self, res):
        self.running = False
        self.run_btn.config(state="normal")
        self.status.config(text="完了")
        self.output_dir = res.get("_output_dir")
        if self.output_dir and os.path.isdir(self.output_dir):
            self.open_btn.config(state="normal")
        confirm = res.get("confirm", 0)
        total = res.get("total", 0)
        skips = res.get("skips", 0)
        ex = res.get("executed", {})
        linked = ex.get("linked", 0) if isinstance(ex, dict) else 0
        msg = [f"完了しました。",
               f"確定 {confirm} / 合計 {total}（要確認・スキップ {skips} 件）"]
        if linked:
            msg.append(f"実際に紐づけた件数: {linked}")
        msg.append("")
        msg.append(f"チェック用CSV: {os.path.basename(res.get('skip_csv', ''))}")
        msg.append("仕上げ（データ反映チェック／リスト確定）は画面で行ってください。")
        messagebox.showinfo("完了", "\n".join(msg))

    def _on_error(self, err):
        self.running = False
        self.run_btn.config(state="normal")
        self.status.config(text="エラー")
        messagebox.showerror("エラー", f"処理中にエラーが発生しました:\n{err}")

    def open_output(self):
        if not self.output_dir:
            return
        d = os.path.abspath(self.output_dir)
        import platform
        import subprocess
        try:
            if platform.system() == "Darwin":
                subprocess.Popen(["open", d])
            elif platform.system() == "Windows":
                os.startfile(d)  # type: ignore
            else:
                subprocess.Popen(["xdg-open", d])
        except Exception:
            messagebox.showinfo("出力フォルダ", d)


def main():
    # 実行ファイル同梱のモデル/設定を展開（非frozenでは何もしない）
    try:
        from .bootstrap import bootstrap
        bootstrap()
    except Exception:
        pass
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
