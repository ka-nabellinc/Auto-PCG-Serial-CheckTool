"""ブラウザUI（tkinter不要・Python標準ライブラリのみ）。

起動すると localhost に簡易サーバを立て、既定ブラウザにフォームを開く。
利用者は: 紐づけID入力 → 実行 → 進捗表示 → CSVダウンロード、をブラウザ上で行う。
コマンド入力は不要。Chromeのデバッグ起動もアプリが自動で行う。
"""
from __future__ import annotations

import json
import os
import socket
import sys
import threading
import traceback
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

from .chrome_launcher import ensure_debug_chrome
from .config import load_config

_STATE = {"running": False, "log": [], "result": None, "error": None, "output_dir": "."}
_LOCK = threading.Lock()


def _log(s: str):
    with _LOCK:
        _STATE["log"].append(s if s.endswith("\n") else s + "\n")


def _config_path() -> str:
    bases = []
    if getattr(sys, "frozen", False):
        bases.append(os.path.dirname(sys.executable))
    bases += [os.getcwd(), os.path.dirname(os.path.abspath(__file__))]
    for b in bases:
        p = os.path.join(b, "config.yaml")
        if os.path.exists(p):
            return p
    return "config.yaml"


class _Writer:
    def write(self, s):
        if s:
            _log(s)
    def flush(self):
        pass


def _worker(reg: str, mode: str):
    old = sys.stdout, sys.stderr
    sys.stdout = sys.stderr = _Writer()
    try:
        from .main import run   # 重い依存は実行時に読み込む（UI起動を軽くする）
        cfg_path = _config_path()
        cfg = load_config(cfg_path)
        _STATE["output_dir"] = cfg.output_dir
        if not ensure_debug_chrome(cfg.cdp_url, log=_log):
            raise RuntimeError("Chromeのデバッグ起動に失敗しました。Chromeを確認してください。")
        res = run(reg, cfg_path, mode=mode, assume_yes=(mode == "execute"),
                  all_pages=(mode == "execute"), notify=False)
        _STATE["output_dir"] = res.get("_output_dir", cfg.output_dir) or cfg.output_dir
        with _LOCK:
            _STATE["result"] = res
    except Exception as e:
        traceback.print_exc()
        with _LOCK:
            _STATE["error"] = str(e)
    finally:
        sys.stdout, sys.stderr = old
        with _LOCK:
            _STATE["running"] = False


_HTML = """<!doctype html><html lang="ja"><head><meta charset="utf-8">
<title>商品紐づけ ツール</title><style>
body{font-family:sans-serif;margin:24px;max-width:900px}
h1{font-size:18px} label{margin-right:12px}
#log{background:#111;color:#ddd;padding:10px;height:320px;overflow:auto;white-space:pre-wrap;font-size:12px;border-radius:6px}
button{padding:6px 16px;font-size:14px} .row{margin:10px 0}
#dl a{display:inline-block;margin-right:12px}
</style></head><body>
<h1>商品紐づけ ツール</h1>
<div class="row">
 紐づけID：<input id="reg" size="12" autofocus>
 <label><input type="radio" name="mode" value="propose" checked> 確認のみ（書き込まない）</label>
 <label><input type="radio" name="mode" value="execute"> 実行（紐づける）</label>
</div>
<div class="row"><button id="run">実行</button> <span id="status"></span></div>
<div class="row" id="dl"></div>
<div id="log"></div>
<script>
let since=0, timer=null;
const logEl=document.getElementById('log'), st=document.getElementById('status');
function poll(){
 fetch('/status?since='+since).then(r=>r.json()).then(d=>{
  if(d.log&&d.log.length){logEl.textContent+=d.log.join('');since+=d.log.length;logEl.scrollTop=logEl.scrollHeight;}
  if(d.running){st.textContent='実行中…';}
  else{
   clearInterval(timer);timer=null;document.getElementById('run').disabled=false;
   if(d.error){st.textContent='エラー';alert('エラー: '+d.error);}
   else if(d.result){const R=d.result;st.textContent='完了';
     let msg='確定 '+R.confirm+' / 合計 '+R.total+'（要確認・スキップ '+R.skips+'）';
     if(R.executed&&R.executed.linked){msg+=' / 紐づけ '+R.executed.linked+'件';}
     st.textContent='完了: '+msg;
     const dl=document.getElementById('dl');dl.innerHTML='ダウンロード: ';
     (R.files||[]).forEach(f=>{const a=document.createElement('a');a.href='/download?name='+encodeURIComponent(f);a.textContent=f;a.download=f;dl.appendChild(a);});
   }
  }
 });
}
document.getElementById('run').onclick=function(){
 const reg=document.getElementById('reg').value.trim();
 if(!reg){alert('紐づけIDを入力してください');return;}
 const mode=document.querySelector('input[name=mode]:checked').value;
 if(mode==='execute'&&!confirm('紐づけID '+reg+' のカードを実際に紐づけます。よろしいですか？')){return;}
 this.disabled=true;logEl.textContent='';since=0;document.getElementById('dl').innerHTML='';
 fetch('/run',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({reg:reg,mode:mode})})
  .then(r=>r.json()).then(_=>{if(!timer)timer=setInterval(poll,700);});
};
</script></body></html>"""


class _Handler(BaseHTTPRequestHandler):
    def _send(self, code, ctype, body: bytes):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        u = urlparse(self.path)
        if u.path == "/":
            self._send(200, "text/html; charset=utf-8", _HTML.encode("utf-8"))
        elif u.path == "/status":
            since = int((parse_qs(u.query).get("since", ["0"]) or ["0"])[0])
            with _LOCK:
                res = _STATE["result"]
                out = {
                    "running": _STATE["running"],
                    "log": _STATE["log"][since:],
                    "error": _STATE["error"],
                    "result": None,
                }
                if res is not None:
                    out["result"] = {
                        "confirm": res.get("confirm", 0), "total": res.get("total", 0),
                        "skips": res.get("skips", 0), "executed": res.get("executed", {}),
                        "files": [os.path.basename(res.get("skip_csv", "")),
                                  os.path.basename(res.get("csv", "")),
                                  os.path.basename(res.get("html", ""))],
                    }
            self._send(200, "application/json", json.dumps(out).encode("utf-8"))
        elif u.path == "/download":
            name = os.path.basename((parse_qs(u.query).get("name", [""]) or [""])[0])
            path = os.path.join(_STATE["output_dir"], name)
            if name and os.path.isfile(path):
                with open(path, "rb") as f:
                    self._send(200, "application/octet-stream", f.read())
            else:
                self._send(404, "text/plain", b"not found")
        else:
            self._send(404, "text/plain", b"not found")

    def do_POST(self):
        if urlparse(self.path).path == "/run":
            n = int(self.headers.get("Content-Length", 0))
            data = json.loads(self.rfile.read(n) or b"{}")
            with _LOCK:
                if not _STATE["running"]:
                    _STATE.update(running=True, log=[], result=None, error=None)
                    threading.Thread(target=_worker,
                                     args=(str(data.get("reg", "")).strip(),
                                           data.get("mode", "propose")),
                                     daemon=True).start()
            self._send(200, "application/json", b'{"ok":true}')
        else:
            self._send(404, "text/plain", b"not found")

    def log_message(self, *a):
        pass


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    p = s.getsockname()[1]
    s.close()
    return p


def main():
    try:
        from .bootstrap import bootstrap
        bootstrap(_log)
    except Exception:
        pass
    port = _free_port()
    srv = ThreadingHTTPServer(("127.0.0.1", port), _Handler)
    url = f"http://127.0.0.1:{port}/"
    print(f"ブラウザUIを開きます: {url}")
    try:
        webbrowser.open(url)
    except Exception:
        pass
    srv.serve_forever()


if __name__ == "__main__":
    main()
