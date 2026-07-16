"""スキップ通知（ポップアップ）。

環境に応じてフォールバック:
1) tkinter のメッセージボックス（クロスプラットフォーム・追加依存なし）
2) macOS の osascript による通知ダイアログ
3) 標準出力（GUI不可の環境）
どれも失敗しても本処理は止めない。
"""
from __future__ import annotations

import platform
import subprocess
import sys


def show_popup(title: str, message: str) -> str:
    """ポップアップを表示。使った手段名を返す（'tk'/'osascript'/'stdout'）。"""
    # 1) tkinter
    try:
        import tkinter as tk
        from tkinter import messagebox

        root = tk.Tk()
        root.withdraw()
        root.attributes("-topmost", True)
        messagebox.showwarning(title, message)
        root.destroy()
        return "tk"
    except Exception:
        pass

    # 2) macOS osascript
    if platform.system() == "Darwin":
        try:
            safe_msg = message.replace('"', "'")[:1500]
            safe_title = title.replace('"', "'")
            subprocess.run(
                ["osascript", "-e",
                 f'display dialog "{safe_msg}" with title "{safe_title}" buttons {{"OK"}} '
                 f'default button "OK" with icon caution'],
                check=False, timeout=30,
            )
            return "osascript"
        except Exception:
            pass

    # 3) 標準出力
    print("\n" + "=" * 48, file=sys.stderr)
    print(f"[通知] {title}", file=sys.stderr)
    print(message, file=sys.stderr)
    print("=" * 48 + "\n", file=sys.stderr)
    return "stdout"


def build_skip_message(reg_id: str, skips, csv_path: str, max_lines: int = 8) -> str:
    """スキップ通知の本文を作る。"""
    lines = [f"紐づけID {reg_id}: スキップ {len(skips)} 件", "", "手動対応が必要なカード:"]
    for p in skips[:max_lines]:
        no = p.item.no or "?"
        name = p.item.read_name or "(名称不明)"
        lines.append(f"  ・No.{no} {name} — {p.reason}")
    if len(skips) > max_lines:
        lines.append(f"  … ほか {len(skips) - max_lines} 件")
    lines.append("")
    lines.append(f"詳細CSV: {csv_path}")
    return "\n".join(lines)
