#!/usr/bin/env python3
"""
sitewatch.py - desk alert light for zeiglersdist.com

Polls the website on a loop and drives an 8x8 WS2812B panel on GPIO18:

    dim green        site is up
    fast red flash   site is DOWN (office internet is fine)
    slow red pulse   office internet is down, so the site can't be checked
    dark             the Pi or this script is not running

Run with --test to cycle the three light states without touching the network
(useful for checking the wiring).

Logging: one file per run in logs/ next to this script, echoed to the console.
Log files older than LOG_RETENTION_DAYS are deleted at startup and once a day.
"""

import argparse
import json
import logging
import os
import subprocess
import sys
import threading
import time
from collections import deque
from datetime import datetime, timedelta
from pathlib import Path

import requests
from dotenv import load_dotenv

import games

BASE_DIR = Path(__file__).resolve().parent
LOG_DIR = BASE_DIR / "logs"
OVERRIDE_FILE = BASE_DIR / "run" / "override.json"   # written by status.py when you pick a game on the web page
ROTATION_FILE = BASE_DIR / "run" / "rotation.json"   # written by status.py: which patterns are in the rotation
load_dotenv(BASE_DIR / ".env")

# ---------------------------------------------------------------- settings --
SITE_URL = os.getenv("SITE_URL", "https://www.zeiglersdist.com/")
BETA_URL = os.getenv("BETA_URL", "")                   # optional second site shown as a strip along the bottom
LAYOUT = os.getenv("LAYOUT", "split").lower()          # split: two half-panels, one per site | strip: beta as a bottom strip
SPLIT = os.getenv("SPLIT", "full").lower()             # split layout: full = one game over the whole panel, a half flashes when its site is down | lr = live left / beta right | tb = live top / beta bottom
TETRIS_COLORS = os.getenv("TETRIS_COLORS", "1") == "1"  # tetris: classic piece colours (else the site colour)
PATTERN_ROTATE = int(os.getenv("PATTERN_ROTATE", "2"))  # minutes per pattern when PATTERNS lists more than one (0 = never rotate)
PATTERNS = [p.strip().lower() for p in os.getenv(
    "PATTERNS", "tetris,runner,climber,pong,snake,breakout,invaders,frogger,racer,simon,missile,asteroids,"
                "cave,flappy,centipede,tanks,lander,pinball,lightsout,skiing,digger,maze").split(",") if p.strip()]
PATTERN_NAMES = ("tetris", "ripple", "bars", "sonar", "ekg") + tuple(games.GAMES)   # everything the split layout can draw
MAIN_PATTERN = os.getenv("MAIN_PATTERN", "tetris").lower()  # used when PATTERN_ROTATE=0: tetris | runner | climber | pong | snake | breakout | invaders | frogger | racer | ripple | bars | sonar | ekg
BETA_PATTERN = os.getenv("BETA_PATTERN", "tetris").lower()  # SPLIT=lr/tb only, same choices
BAR_SCALE = float(os.getenv("BAR_SCALE", "2.0"))           # bars: response time (s) that fills the full height
BETA_ROWS = int(os.getenv("BETA_ROWS", "2"))           # strip layout only: how many bottom rows the beta strip uses
BETA_UP_COLOR = tuple(int(v) for v in os.getenv("BETA_UP_COLOR", "255,70,0").split(","))     # orange
BETA_DOWN_COLOR = tuple(int(v) for v in os.getenv("BETA_DOWN_COLOR", "255,190,0").split(","))  # yellow
REFERENCE_URL = os.getenv("REFERENCE_URL", "https://www.google.com/")
CHECK_TEXT = os.getenv("CHECK_TEXT", "")            # optional: text that must appear in the page
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", "30"))      # seconds between checks
FAIL_THRESHOLD = int(os.getenv("FAIL_THRESHOLD", "3"))       # consecutive failures before alarm
NET_GRACE = int(os.getenv("NET_GRACE", "2"))                 # reference-site failures in a row before "internet down"
HTTP_TIMEOUT = int(os.getenv("HTTP_TIMEOUT", "10"))
ALERT_WEBHOOK_URL = os.getenv("ALERT_WEBHOOK_URL", "")       # optional Teams/Slack-style webhook
LOG_RETENTION_DAYS = int(os.getenv("LOG_RETENTION_DAYS", "15"))

LED_PIN = int(os.getenv("LED_PIN", "18"))
LED_COUNT = int(os.getenv("LED_COUNT", "64"))
LED_BRIGHTNESS = int(os.getenv("LED_BRIGHTNESS", "64"))      # 0-255 hard cap; 64 = ~25%
GREEN_LEVEL = int(os.getenv("GREEN_LEVEL", "40"))            # 0-255 how bright the idle green is
RED_LEVEL = int(os.getenv("RED_LEVEL", "255"))
NET_COLOR = tuple(int(v) for v in os.getenv("NET_COLOR", "150,0,255").split(","))  # purple pulse: office internet down
FLASH_PERIOD = float(os.getenv("FLASH_PERIOD", "0.4"))       # seconds on / seconds off when down
GREEN_PATTERN = os.getenv("GREEN_PATTERN", "ekg").lower()  # ekg | heartbeat | snake | breathe | twinkle | solid
PANEL_WIDTH = int(os.getenv("PANEL_WIDTH", "8"))
PANEL_ROTATE = int(os.getenv("PANEL_ROTATE", "0"))           # 0 | 90 | 180 | 270 if the trace comes out sideways
PANEL_SERPENTINE = os.getenv("PANEL_SERPENTINE", "1") == "1"  # BTF 8x8 panels zig-zag row by row
PANEL_MIRROR_X = os.getenv("PANEL_MIRROR_X", "1") == "1"      # flip left/right (set 0 if scrolling text reads backwards)
GAME_SPEED = float(os.getenv("GAME_SPEED", "2.0"))            # >1 slows every game and banner down, <1 speeds them up

UP, DOWN, NET_DOWN = "UP", "DOWN", "NET_DOWN"

# ----------------------------------------------------------------- logging --
def setup_logging() -> logging.Logger:
    LOG_DIR.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    log_path = LOG_DIR / f"sitewatch_{stamp}.log"
    fmt = logging.Formatter("%(asctime)s %(levelname)-7s %(message)s", "%Y-%m-%d %H:%M:%S")
    log = logging.getLogger("sitewatch")
    log.setLevel(logging.INFO)
    for handler in (logging.FileHandler(log_path, encoding="utf-8"), logging.StreamHandler(sys.stdout)):
        handler.setFormatter(fmt)
        log.addHandler(handler)
    log.info("Logging to %s", log_path)
    return log


def cleanup_old_logs(log: logging.Logger) -> None:
    cutoff = datetime.now() - timedelta(days=LOG_RETENTION_DAYS)
    removed = 0
    for path in LOG_DIR.glob("sitewatch_*.log"):
        try:
            if datetime.fromtimestamp(path.stat().st_mtime) < cutoff:
                path.unlink()
                removed += 1
        except OSError as exc:
            log.warning("Could not remove %s: %s", path.name, exc)
    if removed:
        log.info("Removed %d log file(s) older than %d days", removed, LOG_RETENTION_DAYS)


# ------------------------------------------------------------------- panel --
class Panel(threading.Thread):
    """Owns the LED strip and animates it based on self.mode. Runs in its own
    thread so the light keeps flashing while the main loop waits on HTTP."""

    def __init__(self, log: logging.Logger):
        super().__init__(daemon=True)
        self.log = log
        self.mode = UP
        self.beta = None            # None (not configured) | UP | DOWN
        self.hist = {"main": deque(maxlen=PANEL_WIDTH), "beta": deque(maxlen=PANEL_WIDTH)}  # response times (s)
        self.last_ok = {"main": 0.0, "beta": 0.0}   # monotonic time of the last successful check
        self._halt = threading.Event()
        self._tetris = {}
        self._games = {}                        # (name, which) -> (game instance, frame counter)
        self._marquee = {}                      # which -> Marquee currently scrolling a banner
        self._x0, self._rw = 0, PANEL_WIDTH     # current draw region: x offset and width (set by _run_split)
        from rpi_ws281x import PixelStrip, Color  # imported here so --test on a PC can stub it
        self._Color = Color
        self.strip = PixelStrip(LED_COUNT, LED_PIN, brightness=LED_BRIGHTNESS)
        self.strip.begin()

    @property
    def main_rows(self) -> int:
        """Rows available to the main-site animation (the beta strip takes the rest)."""
        h = LED_COUNT // PANEL_WIDTH
        return h - BETA_ROWS if (LAYOUT == "strip" and self.beta is not None) else h

    def _show(self) -> None:
        """Push the frame, overlaying the beta strip. The strip stays through a main-site
        outage but not an internet outage (nothing is reachable, so purple takes it all)."""
        if LAYOUT == "strip" and self.beta is not None and self.mode != NET_DOWN:
            h = LED_COUNT // PANEL_WIDTH
            if self.beta == UP:
                r, g, b = BETA_UP_COLOR
            elif int(time.monotonic() * 3) % 2 == 0:   # flash ~1.5 Hz when down
                r, g, b = BETA_DOWN_COLOR
            else:
                r, g, b = 0, 0, 0
            color = self._Color(r, g, b)
            for y in range(h - BETA_ROWS, h):
                for x in range(PANEL_WIDTH):
                    self.strip.setPixelColor(self._xy(x, y), color)
        self.strip.show()

    def fill(self, r: int, g: int, b: int) -> None:
        color = self._Color(r, g, b)
        for i in range(LED_COUNT):
            self.strip.setPixelColor(i, color)
        self._show()

    def off(self) -> None:
        self.fill(0, 0, 0)

    def stop(self) -> None:
        self._halt.set()

    def _sleep(self, seconds: float) -> bool:
        """Sleep unless stopped. Returns False if stop was requested."""
        return not self._halt.wait(seconds)

    def _still(self, mode: str) -> bool:
        """True while we should keep animating this mode."""
        return self.mode == mode and not self._halt.is_set()

    # -- idle (site up) patterns --------------------------------------------
    def _idle_solid(self) -> None:
        self.fill(0, GREEN_LEVEL, 0)
        self._sleep(0.5)

    def _idle_breathe(self) -> None:
        steps = 40
        for i in list(range(steps)) + list(range(steps, 0, -1)):
            if not self._still(UP):
                return
            self.fill(0, int(GREEN_LEVEL * (0.25 + 0.75 * i / steps)), 0)
            self._sleep(0.05)

    def _idle_heartbeat(self) -> None:
        """Lub-dub: a strong beat, a softer second beat, then rest (~60 bpm)."""
        base = max(1, GREEN_LEVEL // 8)

        def beat(peak: float, up: int, down: int, step: float) -> bool:
            ramp = [i / up for i in range(1, up + 1)] + [i / down for i in range(down - 1, -1, -1)]
            for frac in ramp:
                if not self._still(UP):
                    return False
                level = base + int((GREEN_LEVEL - base) * peak * frac)
                self.fill(0, level, 0)
                self._sleep(step)
            return True

        while self._still(UP):
            if not beat(1.0, 4, 6, 0.03):        # lub: fast up, medium down
                return
            if not beat(0.55, 3, 8, 0.03):       # dub: smaller, longer tail
                return
            self.fill(0, base, 0)
            if not self._sleep(0.55):            # rest until next beat
                return

    # -- grid helpers -------------------------------------------------------
    @staticmethod
    def _xy(x: int, y: int) -> int:
        """Map (x, y) with (0,0) top-left to a pixel index on a serpentine panel."""
        w = PANEL_WIDTH
        h = LED_COUNT // w
        if PANEL_MIRROR_X:
            x = w - 1 - x
        if PANEL_ROTATE == 90:
            x, y = w - 1 - y, x
        elif PANEL_ROTATE == 180:
            x, y = w - 1 - x, h - 1 - y
        elif PANEL_ROTATE == 270:
            x, y = y, h - 1 - x
        if PANEL_SERPENTINE and y % 2 == 1:
            x = w - 1 - x
        return y * w + x

    # One heartbeat as a column-by-column trace height (0 = top row, 7 = bottom).
    # flat, P bump, flat, Q dip, R spike, S dip, flat, T bump, long flat.
    def _pxy(self, x: int, y: int) -> int:
        """Pixel index for (x, y) inside the current draw region."""
        return self._xy(self._x0 + x, y)

    _EKG = [5, 5, 5, 5, 4, 4, 5, 5, 6, 0, 7, 5, 5, 5, 4, 3, 4, 5, 5, 5, 5, 5, 5, 5, 5, 5]

    def _idle_ekg(self) -> None:
        """Hospital-monitor style trace scrolling right-to-left across the grid."""
        w = PANEL_WIDTH
        n = len(self._EKG)
        base = max(1, GREEN_LEVEL // 10)
        offset = 0
        while self._still(UP):
            h = self.main_rows
            # squeeze the 8-row waveform into however many rows we have
            wave = [round(v * (h - 1) / 7) for v in self._EKG]
            # clear to a very faint field
            for i in range(LED_COUNT):
                self.strip.setPixelColor(i, self._Color(0, base, 0))
            prev_y = None
            for x in range(w):
                y = wave[(offset + x) % n]
                # brighter toward the leading (right) edge, like the monitor's write head
                level = int(GREEN_LEVEL * (0.45 + 0.55 * x / (w - 1)))
                lo, hi = (y, y) if prev_y is None else (min(prev_y, y), max(prev_y, y))
                for yy in range(lo, hi + 1):
                    if 0 <= yy < h:
                        self.strip.setPixelColor(self._xy(x, yy), self._Color(0, level, 0))
                prev_y = y
            self._show()
            offset = (offset + 1) % n
            self._sleep(0.09)

    def _draw_trace(self, y0: int, rows: int, color: tuple, offset: int) -> None:
        """Draw one EKG trace in `color` into rows y0..y0+rows-1 (no show)."""
        w = self._rw
        n = len(self._EKG)
        wave = [round(v * (rows - 1) / 7) for v in self._EKG]
        cr, cg, cb = color
        base = tuple(max(1, c // 10) if c else 0 for c in color)
        for y in range(y0, y0 + rows):
            for x in range(w):
                self.strip.setPixelColor(self._pxy(x, y), self._Color(*base))
        prev_y = None
        for x in range(w):
            y = wave[(offset + x) % n]
            f = 0.45 + 0.55 * x / (w - 1)
            c = self._Color(int(cr * f), int(cg * f), int(cb * f))
            lo, hi = (y, y) if prev_y is None else (min(prev_y, y), max(prev_y, y))
            for yy in range(lo, hi + 1):
                if 0 <= yy < rows:
                    self.strip.setPixelColor(self._pxy(x, y0 + yy), c)
            prev_y = y

    def _draw_bars(self, y0: int, rows: int, color: tuple, which: str) -> None:
        """Last N response times as a bar chart, newest on the right, taller = slower."""
        w = self._rw
        hist = list(self.hist[which])
        cr, cg, cb = color
        base = tuple(max(1, c // 12) if c else 0 for c in color)
        for y in range(y0, y0 + rows):
            for x in range(w):
                self.strip.setPixelColor(self._pxy(x, y), self._Color(*base))
        start = w - len(hist)
        for i, secs in enumerate(hist):
            x = start + i
            height = max(1, min(rows, int(round(secs / BAR_SCALE * rows))))
            f = 1.0 if i == len(hist) - 1 else 0.6          # newest bar brightest
            c = self._Color(int(cr * f), int(cg * f), int(cb * f))
            for k in range(height):
                self.strip.setPixelColor(self._pxy(x, y0 + rows - 1 - k), c)

    def _draw_sonar(self, y0: int, rows: int, color: tuple, which: str) -> None:
        """Radar sweep left-to-right with a fading trail; a blip flashes after each good check."""
        w = self._rw
        t = time.monotonic()
        cr, cg, cb = color
        base = tuple(max(1, c // 14) if c else 0 for c in color)
        period = 1.6
        head = int((t % period) / period * w)
        for x in range(w):
            d = (head - x) % w
            f = max(0.0, 1.0 - d / 4) if d < 4 else 0.0     # 4-column trail
            c = self._Color(*base) if f == 0 else self._Color(int(cr * f), int(cg * f), int(cb * f))
            for y in range(y0, y0 + rows):
                self.strip.setPixelColor(self._pxy(x, y), c)
        age = t - self.last_ok[which]
        if age < 1.0:                                        # blip: 2x2 in the middle, fading for 1 s
            f = 1.0 - age
            c = self._Color(int(255 * f), int(255 * f), int(255 * f))
            cy = y0 + rows // 2 - 1
            for x in (w // 2 - 1, w // 2):
                for y in (cy, cy + 1):
                    self.strip.setPixelColor(self._pxy(x, y), c)

    def _draw_ripple(self, y0: int, rows: int, color: tuple, which: str, phase: float = 0.0) -> None:
        """Ring expanding out from the centre of the half every couple of seconds,
        fading as it grows. A good check drops a white spark in the middle."""
        w = self._rw
        t = time.monotonic() + phase
        cr, cg, cb = color
        base = tuple(max(1, c // 16) if c else 0 for c in color)
        period = 2.4
        cx, cy = (w - 1) / 2, y0 + (rows - 1) / 2
        rmax = ((cx + 0.5) ** 2 + (rows / 2 + 0.5) ** 2) ** 0.5
        prog = (t % period) / period
        radius = prog * rmax
        fade = 1.0 - prog * 0.7                              # ring dims as it spreads
        for y in range(y0, y0 + rows):
            for x in range(w):
                d = ((x - cx) ** 2 + (y - cy) ** 2) ** 0.5
                f = max(0.0, 1.0 - abs(d - radius) / 1.1) * fade
                if f <= 0.05:
                    c = self._Color(*base)
                else:
                    f = max(f, 0.0)
                    c = self._Color(max(base[0], int(cr * f)), max(base[1], int(cg * f)), max(base[2], int(cb * f)))
                self.strip.setPixelColor(self._pxy(x, y), c)
        age = t - phase - self.last_ok[which]
        if age < 0.8:                                        # spark: 2x2 white in the middle
            f = 1.0 - age / 0.8
            c = self._Color(int(255 * f), int(255 * f), int(255 * f))
            for x in (w // 2 - 1, w // 2):
                for y in (y0 + rows // 2 - 1, y0 + rows // 2):
                    self.strip.setPixelColor(self._pxy(x, y), c)

    # the seven tetrominoes in spawn orientation (list of (dx, dy) cells) and classic colours
    _TETROMINOES = (
        ((0, 0), (1, 0), (2, 0), (3, 0)),          # I
        ((0, 0), (1, 0), (0, 1), (1, 1)),          # O
        ((0, 0), (1, 0), (2, 0), (0, 1)),          # L
        ((0, 0), (1, 0), (2, 0), (2, 1)),          # J
        ((0, 0), (1, 0), (2, 0), (1, 1)),          # T
        ((1, 0), (2, 0), (0, 1), (1, 1)),          # S
        ((0, 0), (1, 0), (1, 1), (2, 1)),          # Z
    )
    _TETRIS_RGB = ((0, 200, 255), (255, 200, 0), (255, 90, 0), (0, 60, 255),
                   (170, 0, 255), (0, 220, 40), (255, 0, 30))

    @staticmethod
    def _rot(cells):
        """Rotate a piece 90 degrees clockwise and re-anchor it at (0, 0)."""
        maxy = max(dy for _, dy in cells)
        r = [(maxy - dy, dx) for dx, dy in cells]
        return tuple(sorted(r))

    def _draw_tetris(self, y0: int, rows: int, color: tuple, which: str) -> None:
        """Auto-playing Tetris: each piece spawns at the top, then slides and rotates
        into the spot a little AI picked while it falls. Full rows clear; a full
        stack flashes and resets. The stack pulses brighter on every good check."""
        import random
        w = self._rw
        st = self._tetris.setdefault(which, {"grid": [[0] * w for _ in range(rows)], "piece": None,
                                             "x": 0, "y": 0, "frame": 0, "flash": 0, "kind": 1,
                                             "tx": 0, "trot": 0, "rot": 0})
        st["frame"] += 1
        step = st["frame"] % max(1, round(5 * GAME_SPEED)) == 0   # one game tick every 5 frames at GAME_SPEED=1
        grid = st["grid"]

        def fits(cells, x, y):
            for dx, dy in cells:
                cx, cy = x + dx, y + dy
                if cx < 0 or cx >= w or cy >= rows:
                    return False
                if cy >= 0 and grid[cy][cx]:
                    return False
            return True

        def landing(cells, x):
            y = -max(dy for _, dy in cells) - 1
            while fits(cells, x, y + 1):
                y += 1
            return y

        def score(cells, x):
            """Lower is better: land high up = bad, holes underneath = bad, full rows = good."""
            y = landing(cells, x)
            if not fits(cells, x, y):
                return None
            filled = {(x + dx, y + dy) for dx, dy in cells}
            top = min(y + dy for _, dy in cells)
            holes = 0
            for cx, cy in filled:
                yy = cy + 1
                while yy < rows and not grid[yy][cx] and (cx, yy) not in filled:
                    holes += 1; yy += 1
            full = sum(1 for r in range(rows) if all(grid[r][c] or (c, r) in filled for c in range(w)))
            return (rows - top) * 2 + holes * 4 - full * 6 + random.random()

        marquee = self._marquee.get(which)
        if marquee is not None:                             # scrolling GAME OVER
            if st["frame"] % max(1, round(GAME_SPEED)) == 0:
                marquee.step()
            if marquee.done:
                self._marquee.pop(which, None)
            else:
                for yy, row in enumerate(marquee.render()):
                    for xx, (r, g, b) in enumerate(row):
                        self.strip.setPixelColor(self._pxy(xx, y0 + yy), self._Color(r, g, b))
                return
        if st["flash"]:                                     # game over: blink then wipe
            st["flash"] -= 1
            if st["flash"] == 0:
                for r in grid:
                    r[:] = [0] * w
                if st.pop("banner", None):
                    self._marquee[which] = games.Marquee("GAME OVER", w, rows, self._BANNER_RGB)
        elif st["piece"] is None:
            kind = random.randrange(7)
            base = self._TETROMINOES[kind]
            best = None
            cells = base
            for rot in range(4):
                pw = max(dx for dx, _ in cells) + 1
                for x in range(w - pw + 1):
                    sc = score(cells, x)
                    if sc is not None and (best is None or sc < best[0]):
                        best = (sc, rot, x)
                cells = self._rot(cells)
            if best is None:
                st["flash"] = 8; st["banner"] = True
            else:
                pw = max(dx for dx, _ in base) + 1
                st.update(piece=base, kind=kind + 1, rot=0, trot=best[1], tx=best[2],
                          x=max(0, min(w - pw, (w - pw) // 2)), y=-max(dy for _, dy in base) - 1)
        elif step:
            cells, x, y = st["piece"], st["x"], st["y"]
            moved = False
            if st["rot"] != st["trot"]:                     # turn first...
                rc = self._rot(cells)
                nx = min(x, w - (max(dx for dx, _ in rc) + 1))
                if fits(rc, nx, y):
                    st.update(piece=rc, x=nx, rot=(st["rot"] + 1) % 4); moved = True
            if not moved and x != st["tx"]:                 # ...then slide toward the chosen column
                nx = x + (1 if st["tx"] > x else -1)
                if fits(cells, nx, y):
                    st["x"] = nx; moved = True
            if fits(cells, st["x"], y + 1):                 # and always keep falling
                st["y"] = y + 1
            else:                                           # landed
                x, cells = st["x"], st["piece"]
                if any(y + dy < 0 for _, dy in cells):
                    st["piece"] = None
                    st["flash"] = 8; st["banner"] = True
                else:
                    for dx, dy in cells:
                        grid[y + dy][x + dx] = st["kind"]
                    full = [i for i, r in enumerate(grid) if all(r)]
                    for i in full:
                        del grid[i]
                        grid.insert(0, [0] * w)
                    st["piece"] = None

        t = time.monotonic()
        boost = 1.0 if t - self.last_ok[which] < 0.4 else 0.55          # stack pulses on a good check
        blink = st["flash"] and (st["flash"] // 2) % 2 == 0

        def rgb(kind, f):
            r, g, b = self._TETRIS_RGB[kind - 1] if TETRIS_COLORS else color
            return self._Color(int(r * f), int(g * f), int(b * f))

        off = self._Color(0, 0, 0)
        white = self._Color(255, 255, 255)
        for yy in range(rows):
            for xx in range(w):
                k = grid[yy][xx]
                c = (white if blink else rgb(k, boost)) if k else off
                self.strip.setPixelColor(self._pxy(xx, y0 + yy), c)
        if st["piece"]:
            c = rgb(st["kind"], 1.0)
            for dx, dy in st["piece"]:
                py = st["y"] + dy
                if py >= 0:
                    self.strip.setPixelColor(self._pxy(st["x"] + dx, y0 + py), c)

    def _draw_game(self, name: str, y0: int, rows: int, which: str) -> None:
        """Run one of the games.py mini-games inside the current region."""
        key = (name, which)
        if key not in self._games:
            self._games[key] = [games.GAMES[name](self._rw, rows), 0]
        game, frame = self._games[key]
        frame += 1
        self._games[key][1] = frame
        marquee = self._marquee.get(which)
        if marquee is None:
            if frame % max(1, round(game.speed * GAME_SPEED)) == 0:
                game.tick()
            if game.banner:                                 # the game just ended: scroll its message
                self._marquee[which] = marquee = games.Marquee(game.banner, self._rw, rows, self._BANNER_RGB)
                game.banner = None
        if marquee is not None:
            if frame % max(1, round(GAME_SPEED)) == 0:
                marquee.step()
            if marquee.done:
                self._marquee.pop(which, None)
            else:
                for yy, row in enumerate(marquee.render()):
                    for xx, (r, g, b) in enumerate(row):
                        self.strip.setPixelColor(self._pxy(xx, y0 + yy), self._Color(r, g, b))
                return
        boost = time.monotonic() - self.last_ok[which] < 0.4
        for yy, row in enumerate(game.render(boost)):
            for xx, (r, g, b) in enumerate(row):
                self.strip.setPixelColor(self._pxy(xx, y0 + yy), self._Color(r, g, b))

    _override = (0.0, None)      # (last check time, pattern name or None)
    _rotation = (0.0, None)      # (last check time, list from the web page or None)
    _BANNER_RGB = (255, 255, 255)

    def _current_pattern(self, default: str) -> str:
        """Which idle pattern to show now: the web-page override if set, else the
        PATTERNS rotation on the wall clock, else `default`."""
        now = time.time()
        checked, choice = self._override
        if now - checked > 1.0:                             # re-read the override file once a second
            choice = None
            try:
                data = json.loads(OVERRIDE_FILE.read_text())
                if data.get("pattern") in PATTERN_NAMES and (not data.get("until") or data["until"] > now):
                    choice = data["pattern"]
            except (OSError, ValueError):
                pass
            self._override = (now, choice)
        if choice:
            return choice
        checked, rotation = self._rotation
        if now - checked > 5.0:
            rotation = None
            try:
                data = json.loads(ROTATION_FILE.read_text())
                lst = [p for p in data.get("patterns", []) if p in PATTERN_NAMES]
                rotation = lst or None
            except (OSError, ValueError, AttributeError):
                pass
            self._rotation = (now, rotation)
        patterns = rotation or PATTERNS
        if PATTERN_ROTATE <= 0 or len(patterns) < 2:
            return patterns[0] if patterns else default
        slot = int(now // (PATTERN_ROTATE * 60))
        return patterns[slot % len(patterns)]

    def _pulse_net(self) -> None:
        """Slow purple breathing pulse over the whole panel while the internet is out."""
        steps = 30
        nr, ng, nb = NET_COLOR
        for i in list(range(steps)) + list(range(steps, 0, -1)):
            if self.mode != NET_DOWN or self._halt.is_set():
                return
            color = self._Color(int(nr * i / steps), int(ng * i / steps), int(nb * i / steps))
            for p in range(LED_COUNT):
                self.strip.setPixelColor(p, color)
            self.strip.show()
            self._sleep(0.05)

    def _run_split(self) -> None:
        """Two half-panels (live left / beta right, or top / bottom with SPLIT=tb). Each has its own trace
        while up and flashes its own colour when down. Internet-out is purple over all."""
        h = LED_COUNT // PANEL_WIDTH
        n = len(self._EKG)
        offset = frame = 0
        main_up, main_down = (0, GREEN_LEVEL, 0), (RED_LEVEL, 0, 0)
        half = PANEL_WIDTH // 2
        if SPLIT == "tb":                      # (x0, width, y0, rows) for each half
            main_box, beta_box = (0, PANEL_WIDTH, 0, h // 2), (0, PANEL_WIDTH, h // 2, h - h // 2)
        else:
            main_box, beta_box = (0, half, 0, h), (half, PANEL_WIDTH - half, 0, h)
        full_box = (0, PANEL_WIDTH, 0, h)
        self.hist["full"] = self.hist["main"]
        while not self._halt.is_set():
            if self.mode == NET_DOWN:
                self._pulse_net()
                continue
            beta = self.beta if self.beta is not None else UP
            if SPLIT == "full":
                # one animation over the whole panel; a down site flashes its own half on top of it
                self.last_ok["full"] = max(self.last_ok["main"], self.last_ok["beta"])
                regions = ((full_box, UP, main_up, main_down, 0, "full", self._current_pattern(MAIN_PATTERN)),
                           (main_box, self.mode, None, main_down, 0, "main", None),
                           (beta_box, beta, None, BETA_DOWN_COLOR, 0, "beta", None))
            else:
                regions = ((main_box, self.mode, main_up, main_down, 0, "main", self._current_pattern(MAIN_PATTERN)),
                           (beta_box, beta, BETA_UP_COLOR, BETA_DOWN_COLOR, n // 3, "beta", self._current_pattern(BETA_PATTERN)))
            for p in range(LED_COUNT):
                self.strip.setPixelColor(p, self._Color(0, 0, 0))
            for (x0, rw, y0, rows), state, up_c, down_c, phase, which, pattern in regions:
                self._x0, self._rw = x0, rw
                if pattern is None:
                    if state == UP:
                        continue
                    state = DOWN                 # overlay-only region: fall through to the flash below
                if state == UP:
                    if pattern == "bars":
                        self._draw_bars(y0, rows, up_c, which)
                    elif pattern == "sonar":
                        self._draw_sonar(y0, rows, up_c, which)
                    elif pattern == "tetris":
                        self._draw_tetris(y0, rows, up_c, which)
                    elif pattern in games.GAMES:
                        self._draw_game(pattern, y0, rows, which)
                    elif pattern == "ripple":
                        self._draw_ripple(y0, rows, up_c, which, 1.2 if which == "beta" else 0.0)
                    else:
                        self._draw_trace(y0, rows, up_c, offset + phase)
                elif int(time.monotonic() / FLASH_PERIOD) % 2 == 0:
                    c = self._Color(*down_c)
                    for y in range(y0, y0 + rows):
                        for x in range(rw):
                            self.strip.setPixelColor(self._pxy(x, y), c)
            self.strip.show()
            frame += 1
            if frame % 2 == 0:                       # trace scrolls at half the frame rate
                offset = (offset + 1) % n
            self._sleep(0.045)

    def _idle_snake(self) -> None:
        base = max(1, GREEN_LEVEL // 6)
        tail = 8
        for head in range(LED_COUNT):
            if not self._still(UP):
                return
            for i in range(LED_COUNT):
                d = (head - i) % LED_COUNT
                g = int(GREEN_LEVEL * (1 - d / tail)) if d < tail else base
                self.strip.setPixelColor(i, self._Color(0, max(g, base), 0))
            self._show()
            self._sleep(0.04)

    def _idle_twinkle(self) -> None:
        import random
        base = max(1, GREEN_LEVEL // 6)
        levels = [base] * LED_COUNT
        while self._still(UP):
            levels[random.randrange(LED_COUNT)] = GREEN_LEVEL
            for i in range(LED_COUNT):
                levels[i] = max(base, int(levels[i] * 0.85))
                self.strip.setPixelColor(i, self._Color(0, levels[i], 0))
            self._show()
            self._sleep(0.08)

    def run(self) -> None:
        idle = {"solid": self._idle_solid, "breathe": self._idle_breathe, "heartbeat": self._idle_heartbeat,
                "ekg": self._idle_ekg, "snake": self._idle_snake,
                "twinkle": self._idle_twinkle}.get(GREEN_PATTERN, self._idle_ekg)
        try:
            if BETA_URL and LAYOUT == "split":
                self._run_split()
                return
            while not self._halt.is_set():
                mode = self.mode
                if mode == UP:
                    idle()
                elif mode == DOWN:
                    self.fill(RED_LEVEL, 0, 0)
                    if not self._sleep(FLASH_PERIOD):
                        break
                    self.off()
                    self._sleep(FLASH_PERIOD)
                elif mode == NET_DOWN:
                    self._pulse_net()
        finally:
            self.off()


# ------------------------------------------------------------------ checks --
def fetch_ok(url: str, must_contain: str = "") -> tuple[bool, str, float]:
    """Returns (ok, detail, seconds)."""
    t0 = time.monotonic()
    try:
        r = requests.get(url, timeout=HTTP_TIMEOUT,
                         headers={"User-Agent": "ZDI-SiteWatch/1.0"})
    except requests.RequestException as exc:
        return False, f"{type(exc).__name__}: {exc}", time.monotonic() - t0
    secs = time.monotonic() - t0
    if r.status_code >= 400:
        return False, f"HTTP {r.status_code}", secs
    if must_contain and must_contain not in r.text:
        return False, f"HTTP {r.status_code} but expected text not found", secs
    return True, f"HTTP {r.status_code} in {secs:.2f}s", secs


def net_diag() -> str:
    """Wi-Fi signal + router reachability, for telling 'Pi lost Wi-Fi' from 'ISP is down'."""
    parts = []
    try:
        for line in Path("/proc/net/wireless").read_text().splitlines()[2:]:
            f = line.split()
            if f and f[0].startswith("wlan"):
                parts.append(f"wifi link {f[2].rstrip('.')}/70 signal {f[3].rstrip('.')} dBm")
    except OSError:
        pass
    try:
        route = subprocess.run(["ip", "route", "show", "default"], capture_output=True, text=True, timeout=3).stdout.split()
        gw = route[route.index("via") + 1] if "via" in route else ""
        if gw:
            ok = subprocess.run(["ping", "-c", "1", "-W", "2", gw], capture_output=True, timeout=5).returncode == 0
            parts.append(f"router {gw} {'reachable' if ok else 'NOT reachable'}")
        else:
            parts.append("no default route (Wi-Fi down)")
    except (OSError, ValueError, subprocess.SubprocessError):
        parts.append("router check failed")
    return "; ".join(parts) or "no diag"


def send_alert(log: logging.Logger, message: str) -> None:
    if not ALERT_WEBHOOK_URL:
        return
    try:
        requests.post(ALERT_WEBHOOK_URL, json={"text": message}, timeout=HTTP_TIMEOUT)
        log.info("Alert sent: %s", message)
    except requests.RequestException as exc:
        log.warning("Alert webhook failed: %s", exc)


# -------------------------------------------------------------------- main --
def monitor(log: logging.Logger, panel: Panel) -> None:
    state = UP
    fails = ref_fails = 0
    beta_state, beta_fails = UP, 0
    last_heartbeat = time.monotonic()
    last_cleanup = time.monotonic()
    log.info("Watching %s every %ds (alarm after %d consecutive failures)",
             SITE_URL, CHECK_INTERVAL, FAIL_THRESHOLD)
    if BETA_URL:
        panel.beta = UP
        log.info("Also watching beta site %s (bottom %d rows)", BETA_URL, BETA_ROWS)

    while True:
        if BETA_URL:
            beta_ok, beta_detail, beta_secs = fetch_ok(BETA_URL)
            beta_fails = 0 if beta_ok else beta_fails + 1
            if beta_ok:
                panel.hist["beta"].append(beta_secs)
                panel.last_ok["beta"] = time.monotonic()
            new_beta = UP if beta_ok else (DOWN if beta_fails >= FAIL_THRESHOLD else beta_state)
            if not beta_ok:
                log.warning("Beta check failed (%d/%d): %s", beta_fails, FAIL_THRESHOLD, beta_detail)
            if new_beta != beta_state:
                msg = f"Beta site is {'BACK UP' if new_beta == UP else 'DOWN'} ({beta_detail})"
                log.info(msg) if new_beta == UP else log.error(msg)
                panel.beta = new_beta
                send_alert(log, msg)
                beta_state = new_beta

        ok, detail, secs = fetch_ok(SITE_URL, CHECK_TEXT)
        new_state = state

        if ok:
            fails = ref_fails = 0
            new_state = UP
            panel.hist["main"].append(secs)
            panel.last_ok["main"] = time.monotonic()
        else:
            fails += 1
            log.warning("Check failed (%d/%d): %s", fails, FAIL_THRESHOLD, detail)
            if fails >= FAIL_THRESHOLD:
                ref_ok, ref_detail, _ = fetch_ok(REFERENCE_URL)
                ref_fails = 0 if ref_ok else ref_fails + 1
                if ref_ok:
                    new_state = DOWN
                else:
                    log.warning("Reference site also failed (%d/%d): %s [%s]", ref_fails, NET_GRACE, ref_detail, net_diag())
                    if ref_fails >= NET_GRACE:      # a single Wi-Fi hiccup doesn't count as an outage
                        new_state = NET_DOWN

        if new_state != state:
            if new_state == UP:
                msg = f"zeiglersdist.com is BACK UP ({detail})"
            elif new_state == DOWN:
                msg = f"zeiglersdist.com is DOWN ({detail})"
            else:
                msg = "Office internet appears to be down; cannot reach the site"
            log.error(msg) if new_state != UP else log.info(msg)
            panel.mode = new_state
            send_alert(log, msg)
            state = new_state
        elif state == UP and time.monotonic() - last_heartbeat > 3600:
            log.info("Still up (%s)", detail)
            last_heartbeat = time.monotonic()

        if time.monotonic() - last_cleanup > 86400:
            cleanup_old_logs(log)
            last_cleanup = time.monotonic()

        time.sleep(CHECK_INTERVAL)


def self_test(log: logging.Logger, panel: Panel) -> None:
    b = UP if BETA_URL else None
    steps = [(UP, b, 3), (DOWN, b, 5), (NET_DOWN, b, 6)]
    if BETA_URL:
        steps += [(UP, DOWN, 4)]
    for k in ("main", "beta"):                      # fake some history so bars have something to show
        panel.hist[k].extend([0.3, 0.4, 0.35, 0.9, 1.6, 0.7, 0.4, 0.3])
    for mode, beta, seconds in steps:
        log.info("TEST: %s%s for %ds", mode, f" + beta {beta}" if beta else "", seconds)
        panel.beta = beta
        panel.mode = mode
        for _ in range(seconds):                    # a blip every second while testing
            panel.last_ok["main"] = panel.last_ok["beta"] = time.monotonic()
            time.sleep(1)
    log.info("TEST: done")


def main() -> int:
    parser = argparse.ArgumentParser(description="Desk alert light for zeiglersdist.com")
    parser.add_argument("--test", action="store_true", help="cycle the light states and exit")
    args = parser.parse_args()

    log = setup_logging()
    cleanup_old_logs(log)

    try:
        panel = Panel(log)
    except Exception as exc:  # noqa: BLE001
        log.critical("Could not initialise LED panel: %s", exc)
        return 1
    panel.start()

    try:
        if args.test:
            self_test(log, panel)
        else:
            monitor(log, panel)
    except KeyboardInterrupt:
        log.info("Stopped by user")
    finally:
        panel.stop()
        panel.join(timeout=2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
