"""ログイン済みChromeをデバッグモードで自動起動する（メンバーがターミナルを触らないため）。

- 既にデバッグポートが開いていれば何もしない。
- 開いていなければ、専用プロファイルでChromeを --remote-debugging-port 起動する。
- OS別にChromeの実行パスを推定（mac/Windows/Linux）。
"""
from __future__ import annotations

import os
import platform
import socket
import subprocess
import time
from typing import List, Optional


def _port_open(host: str, port: int, timeout: float = 1.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def _chrome_candidates() -> List[str]:
    sysname = platform.system()
    if sysname == "Darwin":
        return [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Google Chrome Beta.app/Contents/MacOS/Google Chrome Beta",
        ]
    if sysname == "Windows":
        pf = os.environ.get("PROGRAMFILES", r"C:\Program Files")
        pfx = os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")
        local = os.environ.get("LOCALAPPDATA", "")
        return [
            os.path.join(pf, r"Google\Chrome\Application\chrome.exe"),
            os.path.join(pfx, r"Google\Chrome\Application\chrome.exe"),
            os.path.join(local, r"Google\Chrome\Application\chrome.exe"),
        ]
    # Linux
    return ["/usr/bin/google-chrome", "/usr/bin/google-chrome-stable", "/usr/bin/chromium-browser"]


def find_chrome(explicit: Optional[str] = None) -> Optional[str]:
    if explicit and os.path.exists(explicit):
        return explicit
    for p in _chrome_candidates():
        if os.path.exists(p):
            return p
    return None


def ensure_debug_chrome(cdp_url: str = "http://127.0.0.1:9222",
                        profile_dir: Optional[str] = None,
                        chrome_path: Optional[str] = None,
                        wait_sec: int = 15, log=print) -> bool:
    """デバッグChromeを用意する。ポートが開けばTrue。
    既に開いていればそのまま利用。開いていなければ起動して待つ。"""
    # cdp_url からポートを取り出す
    port = 9222
    try:
        port = int(cdp_url.rsplit(":", 1)[1].split("/")[0])
    except Exception:
        pass

    if _port_open("127.0.0.1", port):
        log(f"デバッグChromeに接続できます（ポート{port}）。")
        return True

    chrome = find_chrome(chrome_path)
    if not chrome:
        log("Google Chromeが見つかりませんでした。Chromeをインストールしてください。")
        return False

    if profile_dir is None:
        profile_dir = os.path.join(os.path.expanduser("~"), "chrome-tcg-profile")

    log("Chromeをデバッグモードで起動します…")
    args = [chrome, f"--remote-debugging-port={port}",
            f"--user-data-dir={profile_dir}", "--no-first-run", "--no-default-browser-check"]
    try:
        creationflags = 0
        if platform.system() == "Windows":
            creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
        subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                         creationflags=creationflags)
    except Exception as e:
        log(f"Chrome起動に失敗しました: {e}")
        return False

    for _ in range(wait_sec):
        time.sleep(1)
        if _port_open("127.0.0.1", port):
            log("デバッグChromeが起動しました。")
            return True
    log("デバッグChromeの起動待ちがタイムアウトしました。")
    return False
