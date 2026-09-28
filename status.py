#!/usr/bin/env python3
"""
status.py - read-only status page for sitewatch, served on the LAN.

    http://sitewatch.local:8080/          current state + recent events
    http://sitewatch.local:8080/log       tail of the newest sitewatch log (?n=500 for more)
    http://sitewatch.local:8080/update    tail of logs/update.log (GitHub pulls)
    http://sitewatch.local:8080/health    JSON: {"main": "UP", "beta": "UP", ...}

It only reads the log files sitewatch.py already writes; it cannot change anything.
"""

import json
import os
import re
import subprocess
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

BASE_DIR = Path(__file__).resolve().parent
LOG_DIR = BASE_DIR / "logs"
RUN_DIR = BASE_DIR / "run"
OVERRIDE_FILE = RUN_DIR / "override.json"
PORT = int(os.getenv("STATUS_PORT", "8080"))
try:
    from games import GAMES as _GAMES
    GAMES = ("tetris",) + tuple(_GAMES)
except ImportError:
    GAMES = ("tetris",)
OTHERS = ("ripple", "bars", "sonar", "ekg")


def current_override() -> str | None:
    try:
        data = json.loads(OVERRIDE_FILE.read_text())
        if not data.get("until") or data["until"] > datetime.now().timestamp():
            return data.get("pattern")
    except (OSError, ValueError):
        pass
    return None


def set_override(pattern: str | None) -> None:
    RUN_DIR.mkdir(exist_ok=True)
    if pattern:
        OVERRIDE_FILE.write_text(json.dumps({"pattern": pattern, "until": 0}))
    elif OVERRIDE_FILE.exists():
        OVERRIDE_FILE.unlink()

STATE_RE = re.compile(
    r"^(?P<ts>\S+ \S+) +(?P<lvl>\w+) +(?P<msg>.*(?:is DOWN|is BACK UP|internet appears to be down|Still up|Watching|TEST:).*)$"
)


def newest_log() -> Path | None:
    logs = sorted(LOG_DIR.glob("sitewatch_*.log"), key=lambda p: p.stat().st_mtime)
    return logs[-1] if logs else None


def tail(path: Path | None, n: int) -> str:
    if not path or not path.exists():
        return "(no log yet)"
    with path.open("rb") as f:
        f.seek(0, 2)
        size = f.tell()
        block = min(size, max(4096, n * 160))
        f.seek(size - block)
        lines = f.read().decode("utf-8", "replace").splitlines()
    return "\n".join(lines[-n:])


def wifi() -> str:
    try:
        for line in Path("/proc/net/wireless").read_text().splitlines()[2:]:
            f = line.split()
            if f and f[0].startswith("wlan"):
                return f"link {f[2].rstrip('.')}/70, signal {f[3].rstrip('.')} dBm"
    except OSError:
        pass
    return "n/a"


def summarize() -> dict:
    """Walk the last 24 h of logs and work out the current state of each site."""
    import time
    logs = sorted(LOG_DIR.glob("sitewatch_*.log"), key=lambda p: p.stat().st_mtime)
    recent = [p for p in logs if time.time() - p.stat().st_mtime < 86400] or logs[-1:]
    log = logs[-1] if logs else None
    state = {"main": "UP", "beta": "UP", "internet": "UP", "since": None, "events": [], "log": str(log) if log else None,
             "wifi": wifi()}
    if not log:
        return state
    lines = []
    for p in recent:
        lines += p.read_text(errors="replace").splitlines()
    for line in lines:
        m = STATE_RE.match(line)
        if not m:
            continue
        msg = m["msg"]
        if "Beta site is DOWN" in msg:
            state["beta"] = "DOWN"
        elif "Beta site is BACK UP" in msg:
            state["beta"] = "UP"
        elif "internet appears to be down" in msg:
            state["internet"] = "DOWN"
        elif "zeiglersdist.com is DOWN" in msg:
            state["main"], state["internet"] = "DOWN", "UP"
        elif "zeiglersdist.com is BACK UP" in msg:
            state["main"], state["internet"] = "UP", "UP"
        if "Still up" not in msg and "TEST:" not in msg:
            state["events"].append(f"{m['ts']}  {msg}")
            state["since"] = m["ts"]
    state["events"] = state["events"][-60:]
    state["service"] = subprocess.run(["systemctl", "is-active", "sitewatch"], capture_output=True, text=True).stdout.strip()
    try:
        state["commit"] = subprocess.run(["git", "-c", "safe.directory=*", "-C", str(BASE_DIR), "log", "-1", "--format=%h %cd %s", "--date=short"],
                                         capture_output=True, text=True).stdout.strip()
    except OSError:
        state["commit"] = ""
    state["checked_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return state


PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>sitewatch</title>
<meta http-equiv="refresh" content="30">
<style>
 body{{font-family:system-ui,sans-serif;margin:2rem;background:#111;color:#ddd}}
 .tile{{display:inline-block;padding:1rem 1.5rem;margin:0 1rem 1rem 0;border-radius:8px;font-size:1.4rem;font-weight:600;color:#000}}
 .UP{{background:#3c3}} .DOWN{{background:#e33}} .NET{{background:#a5f}}
 pre{{background:#000;padding:1rem;border-radius:8px;overflow:auto;font-size:.85rem}}
 a{{color:#8cf}} small{{color:#888}}
 button{{margin:.2rem;padding:.5rem .9rem;border:0;border-radius:6px;background:#333;color:#eee;font-size:1rem;cursor:pointer}}
 button.on{{background:#3c3;color:#000;font-weight:600}}
</style></head><body>
<h1>sitewatch</h1>
<div class="tile {main_cls}">zeiglersdist.com: {main}</div>
<div class="tile {beta_cls}">Aldrich beta: {beta}</div>
<div class="tile {net_cls}">internet: {internet}</div>
<p><small>service: {service} &middot; Wi-Fi: {wifi} &middot; version: {commit} &middot; page generated {checked_at} (auto-refreshes every 30 s)</small></p>
<p><a href="/log">full log tail</a> &middot; <a href="/update">update log</a> &middot; <a href="/health">json</a></p>
<h2>Pick the game</h2>
<form method="post" action="/set">{buttons}</form>
<p><small>{now_playing}</small></p>
<h2>Events, last 24 h</h2>
<pre>{events}</pre>
<h2>Last 40 log lines</h2>
<pre>{tail}</pre>
</body></html>"""


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # keep the journal quiet
        pass

    def _send(self, body: str, ctype: str = "text/plain; charset=utf-8", code: int = 200):
        data = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self):
        url = urlparse(self.path)
        if url.path == "/set":
            length = int(self.headers.get("Content-Length", "0"))
            q = parse_qs(self.rfile.read(length).decode("utf-8", "replace"))
            choice = q.get("pattern", [""])[0]
            try:
                set_override(choice if choice in GAMES + OTHERS else None)
            except OSError as exc:
                self._send(f"could not save your choice: {exc}\n\nOn the Pi run:  sudo install -d -o pi -g pi {RUN_DIR}", code=500)
                return
            self.send_response(303)
            self.send_header("Location", "/")
            self.end_headers()
        else:
            self._send("not found", code=404)

    def do_GET(self):
        url = urlparse(self.path)
        q = parse_qs(url.query)
        n = min(int(q.get("n", ["200"])[0]), 5000)
        if url.path == "/health":
            s = summarize()
            self._send(json.dumps({k: s[k] for k in ("main", "beta", "internet", "wifi", "service", "commit", "since", "checked_at")}),
                       "application/json")
        elif url.path == "/log":
            self._send(tail(newest_log(), n))
        elif url.path == "/update":
            self._send(tail(LOG_DIR / "update.log", n))
        elif url.path == "/":
            s = summarize()
            net_down = s["internet"] == "DOWN"
            ov = current_override()
            buttons = "".join(
                f'<button name="pattern" value="{n}" class="{"on" if n == ov else ""}">{n}</button>'
                for n in GAMES + OTHERS)
            buttons = f'<button name="pattern" value="" class="{"on" if not ov else ""}">auto (rotate)</button>' + buttons
            self._send(PAGE.format(
                buttons=buttons,
                now_playing=f"pinned to {ov} until you press auto" if ov else "rotating through the list every PATTERN_ROTATE minutes",
                main=s["main"], beta=s["beta"], internet=s["internet"],
                main_cls="NET" if net_down else s["main"], beta_cls="NET" if net_down else s["beta"],
                net_cls="NET" if net_down else "UP",
                service=s["service"], wifi=s["wifi"], commit=s["commit"] or "?", checked_at=s["checked_at"],
                events="\n".join(s["events"]) or "(none)", tail=tail(newest_log(), 40),
            ), "text/html; charset=utf-8")
        else:
            self._send("not found", code=404)


if __name__ == "__main__":
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()
