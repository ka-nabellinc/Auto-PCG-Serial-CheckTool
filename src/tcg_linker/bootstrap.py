"""実行ファイル(PyInstaller)同梱リソースの初期化。

- 同梱したPaddleOCRモデルを ~/.paddlex/official_models に初回展開（オフライン化）。
- 同梱した config.yaml / master.csv をカレントに用意（無ければ）。
通常のPython実行（非frozen）では何もしない。
"""
from __future__ import annotations

import os
import shutil
import sys


def _meipass() -> str:
    return getattr(sys, "_MEIPASS", "")


def ensure_bundled_models(log=lambda *_: None) -> None:
    """同梱モデルを ~/.paddlex/official_models へコピー（未展開のもののみ）。"""
    base = _meipass()
    if not base:
        return
    src = os.path.join(base, "paddlex_models")
    if not os.path.isdir(src):
        return
    dst = os.path.join(os.path.expanduser("~"), ".paddlex", "official_models")
    os.makedirs(dst, exist_ok=True)
    for name in os.listdir(src):
        s = os.path.join(src, name)
        d = os.path.join(dst, name)
        if os.path.isdir(s) and not os.path.exists(d):
            try:
                shutil.copytree(s, d)
                log(f"モデル展開: {name}")
            except Exception as e:
                log(f"モデル展開失敗 {name}: {e}")


def ensure_bundled_files(target_dir: str = ".", log=lambda *_: None) -> None:
    """同梱 config.yaml / master.csv を target_dir に用意（無ければコピー）。"""
    base = _meipass()
    if not base:
        return
    for name in ("config.yaml", "master.csv"):
        s = os.path.join(base, name)
        d = os.path.join(target_dir, name)
        if os.path.exists(s) and not os.path.exists(d):
            try:
                shutil.copy(s, d)
                log(f"同梱ファイル展開: {name}")
            except Exception as e:
                log(f"同梱ファイル展開失敗 {name}: {e}")


def bootstrap(log=lambda *_: None) -> None:
    ensure_bundled_models(log)
    ensure_bundled_files(os.getcwd(), log)
