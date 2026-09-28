"""
games.py - tiny self-playing retro-style games for an 8x8 (or any WxH) LED panel.

Every game exposes:
    tick()            advance one game step (sitewatch calls it every `speed` frames)
    render(boost)     -> list of rows of (r, g, b); boost=True brightens the scene
                         briefly (sitewatch passes it right after a good check)

All sprites here are original; they borrow mechanics from the arcade classics,
not their characters.
"""

import random
from collections import deque

OFF = (0, 0, 0)


def dim(c, f):
    return (int(c[0] * f), int(c[1] * f), int(c[2] * f))


class Game:
    speed = 4           # frames per tick (~22 fps host loop, so 4 = ~5 ticks/s)

    def __init__(self, w, h):
        self.w, self.h = w, h
        self.reset()

    def blank(self):
        return [[OFF] * self.w for _ in range(self.h)]

    def put(self, g, x, y, c):
        if 0 <= x < self.w and 0 <= y < self.h:
            g[y][x] = c

    def reset(self):
        pass

    def tick(self):
        pass

    def render(self, boost=False):
        return self.blank()


# ------------------------------------------------------------------ runner --
class Runner(Game):
    """Side-scroller: an original little runner hops gaps and blocks; clouds drift behind."""
    speed = 3
    GROUND, BLOCK, COIN, CLOUD = (60, 40, 0), (170, 60, 0), (255, 200, 0), (40, 40, 60)
    HEAD, SHIRT, PANTS, SKIN = (250, 210, 150), (40, 120, 255), (30, 40, 150), (250, 210, 150)
    RX = 1                                   # runner's left column
    # 3-wide x 4-tall poses: rows top->bottom; H head, T torso, A arm, L leg, . empty
    POSES = {
        "stride": (".H.", "AT.", ".TA", "L.L"),
        "stand":  (".H.", ".TA", "AT.", ".L."),
        "jump":   (".H.", "ATA", ".T.", "L.L"),
    }

    def reset(self):
        self.ground = deque([1] * self.w, maxlen=self.w)     # 1 = ground present
        self.blocks = deque([0] * self.w, maxlen=self.w)     # block height on that column
        self.clouds = [(random.randrange(self.w), random.randrange(0, 2)) for _ in range(2)]
        self.t = 0
        self.jump = 0            # ticks left in jump arc
        self.coin = 0
        self.gap_cooldown = 5

    def tick(self):
        self.t += 1
        self.gap_cooldown -= 1
        r = random.random()
        if self.gap_cooldown <= 0 and r < 0.12:
            self.ground.append(0); self.blocks.append(0); self.gap_cooldown = 7
        elif self.gap_cooldown <= 0 and r < 0.24:
            self.ground.append(1); self.blocks.append(random.choice((1, 1, 2))); self.gap_cooldown = 7
        else:
            self.ground.append(1); self.blocks.append(0)
        if self.t % 3 == 0:
            self.clouds = [((x - 1) % self.w, y) for x, y in self.clouds]
        # jump when trouble is just ahead of the feet (feet span RX..RX+2)
        ahead = self.RX + 3
        trouble = any(not self.ground[x] or self.blocks[x] for x in range(ahead, min(ahead + 2, self.w)))
        if self.jump == 0 and trouble:
            self.jump = 7
        elif self.jump:
            self.jump -= 1
        if self.coin:
            self.coin -= 1

    def render(self, boost=False):
        g = self.blank()
        for x, y in self.clouds:
            self.put(g, x, y, self.CLOUD); self.put(g, x + 1, y, self.CLOUD)
        base = self.h - 1
        for x in range(self.w):
            if self.ground[x]:
                g[base][x] = self.GROUND
                for k in range(self.blocks[x]):
                    g[base - 1 - k][x] = self.BLOCK
        arc = (0, 1, 2, 3, 3, 2, 1, 0)
        lift = arc[7 - self.jump] if self.jump else 0
        pose = self.POSES["jump"] if self.jump else self.POSES["stride" if (self.t // 2) % 2 == 0 else "stand"]
        top = base - 4 - lift                    # row of the head
        colours = {"H": self.HEAD, "T": self.SHIRT, "A": self.SKIN, "L": self.PANTS}
        for dy, row in enumerate(pose):
            for dx, ch in enumerate(row):
                if ch != ".":
                    self.put(g, self.RX + dx, top + dy, colours[ch])
        if boost:
            self.coin = 3
        if self.coin:
            self.put(g, self.RX + 3, top - 1, self.COIN)
        return g


# ----------------------------------------------------------------- climber --
class Climber(Game):
    """Platforms and ladders; barrels roll down, an original climber zigzags up to the prize."""
    speed = 4
    PLAT, LADDER, BARREL, CLIMB, PRIZE = (0, 60, 200), (90, 60, 20), (200, 90, 0), (0, 220, 120), (255, 60, 200)

    def reset(self):
        h = self.h
        # platform rows from bottom up; ladder alternates sides
        self.plats = [h - 1, h - 3, h - 5, h - 7] if h >= 8 else [h - 1, h - 3]
        self.ladders = [(self.w - 1 if i % 2 == 0 else 0) for i in range(len(self.plats) - 1)]
        self.barrels = []
        self.cx, self.cy = 0, self.plats[0]
        self.t = 0
        self.win = 0

    def tick(self):
        self.t += 1
        # spawn barrels at the top platform, rolling toward its ladder side
        if self.t % 7 == 0 and len(self.barrels) < 4:
            self.barrels.append([self.w // 2, self.plats[-1], 1 if self.ladders[-1] == self.w - 1 else -1])
        for b in self.barrels:
            level = self.plats.index(b[1]) if b[1] in self.plats else None
            if level is None:
                continue
            if level > 0 and b[0] == self.ladders[level - 1]:
                b[1] = self.plats[level - 1]              # drop to the platform below
                b[2] = -b[2]
            else:
                b[0] += b[2]
        self.barrels = [b for b in self.barrels if 0 <= b[0] < self.w and not (b[1] == self.plats[0] and b[0] in (0, self.w - 1) and self.t % 2)]
        # climber: walk toward the ladder of the current level, then go up
        if self.win:
            self.win -= 1
            if self.win == 0:
                self.cx, self.cy = 0, self.plats[0]
            return
        level = self.plats.index(self.cy) if self.cy in self.plats else None
        if level is None:                                   # on a ladder rung
            self.cy -= 1
            return
        if level == len(self.plats) - 1:
            if self.cx == self.w // 2:
                self.win = 8
            else:
                self.cx += 1 if self.cx < self.w // 2 else -1
            return
        lx = self.ladders[level]
        if self.cx == lx:
            self.cy -= 1
        else:
            self.cx += 1 if lx > self.cx else -1

    def render(self, boost=False):
        g = self.blank()
        for i, py in enumerate(self.plats):
            for x in range(self.w):
                g[py][x] = self.PLAT
            if i < len(self.ladders):
                lx = self.ladders[i]
                for y in range(self.plats[i + 1] + 1, py):
                    g[y][lx] = self.LADDER
        self.put(g, self.w // 2, self.plats[-1] - 1, self.PRIZE if (self.t // 2) % 2 or boost else dim(self.PRIZE, 0.4))
        for b in self.barrels:
            self.put(g, b[0], b[1] - 1, self.BARREL)
        c = (255, 255, 255) if self.win and self.win % 2 else self.CLIMB
        self.put(g, self.cx, self.cy - 1, c)
        return g


# -------------------------------------------------------------------- pong --
class Pong(Game):
    speed = 3
    PAD, BALL, NET = (0, 200, 255), (255, 255, 255), (30, 30, 30)

    def reset(self):
        self.ly = self.ry = self.h // 2 - 1
        self.bx, self.by = self.w // 2, self.h // 2
        self.vx, self.vy = random.choice((-1, 1)), random.choice((-1, 1))
        self.miss = 0

    def tick(self):
        if self.miss:
            self.miss -= 1
            if self.miss == 0:
                self.bx, self.by = self.w // 2, self.h // 2
                self.vx = random.choice((-1, 1))
            return
        nx, ny = self.bx + self.vx, self.by + self.vy
        if ny < 0 or ny >= self.h:
            self.vy = -self.vy; ny = self.by + self.vy
        # paddles track where the ball is heading; the far paddle occasionally naps
        for attr, near in (("ly", self.vx < 0), ("ry", self.vx > 0)):
            py = getattr(self, attr)
            target = ny if ny <= py else ny - 1          # keep the ball within the 2-pixel paddle
            target = max(0, min(self.h - 2, target))
            if near or random.random() < 0.6:
                py += (target > py) - (target < py)
            if near and random.random() < 0.04:          # the deliberate whiff
                py -= (target > py) - (target < py)
            setattr(self, attr, max(0, min(self.h - 2, py)))
        if nx == 0 and self.ly <= ny <= self.ly + 1 or nx == self.w - 1 and self.ry <= ny <= self.ry + 1:
            self.vx = -self.vx; nx = self.bx + self.vx
            if random.random() < 0.3:
                self.vy = random.choice((-1, 1))
        elif nx < 0 or nx >= self.w:
            self.miss = 4
            return
        self.bx, self.by = nx, ny

    def render(self, boost=False):
        g = self.blank()
        for y in range(0, self.h, 2):
            self.put(g, self.w // 2, y, self.NET)
        for k in (0, 1):
            self.put(g, 0, self.ly + k, self.PAD)
            self.put(g, self.w - 1, self.ry + k, self.PAD)
        if not self.miss or self.miss % 2:
            self.put(g, self.bx, self.by, (255, 255, 0) if boost else self.BALL)
        return g


# ------------------------------------------------------------------- snake --
class Snake(Game):
    speed = 3
    HEAD, BODY, FOOD = (0, 255, 80), (0, 140, 40), (255, 40, 40)

    def reset(self):
        self.body = deque([(self.w // 2, self.h // 2)])
        self.food = self._spawn()
        self.dead = 0

    def _spawn(self):
        free = [(x, y) for x in range(self.w) for y in range(self.h) if (x, y) not in self.body]
        return random.choice(free) if free else None

    def _path(self):
        """BFS from head to food avoiding the body; returns first step or None."""
        start = self.body[0]
        blocked = set(self.body)
        blocked.discard(self.body[-1])                     # tail moves away
        prev = {start: None}
        q = deque([start])
        while q:
            cur = q.popleft()
            if cur == self.food:
                while prev[cur] != start and prev[cur] is not None:
                    cur = prev[cur]
                return cur
            x, y = cur
            for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
                if 0 <= nx < self.w and 0 <= ny < self.h and (nx, ny) not in blocked and (nx, ny) not in prev:
                    prev[(nx, ny)] = cur
                    q.append((nx, ny))
        return None

    def tick(self):
        if self.dead:
            self.dead -= 1
            if self.dead == 0:
                self.reset()
            return
        step = self._path()
        if step is None:                                    # trapped: any free neighbour, else die
            x, y = self.body[0]
            opts = [(nx, ny) for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1))
                    if 0 <= nx < self.w and 0 <= ny < self.h and (nx, ny) not in self.body]
            if not opts:
                self.dead = 6
                return
            step = random.choice(opts)
        self.body.appendleft(step)
        if step == self.food:
            self.food = self._spawn()
            if self.food is None:
                self.dead = 6
        else:
            self.body.pop()

    def render(self, boost=False):
        g = self.blank()
        n = len(self.body)
        for i, (x, y) in enumerate(self.body):
            c = self.HEAD if i == 0 else dim(self.BODY, 1.0 - 0.5 * i / max(1, n))
            if self.dead and self.dead % 2:
                c = (255, 255, 255)
            self.put(g, x, y, c)
        if self.food:
            self.put(g, *self.food, (255, 255, 120) if boost else self.FOOD)
        return g


# ---------------------------------------------------------------- breakout --
class Breakout(Game):
    speed = 3
    ROWS = ((255, 40, 40), (255, 160, 0), (255, 255, 0), (40, 220, 40))
    PAD, BALL = (0, 200, 255), (255, 255, 255)

    def reset(self):
        self.bricks = {(x, y) for y in range(min(3, self.h - 4)) for x in range(self.w)}
        self.px = self.w // 2 - 1
        self.bx, self.by = self.w // 2, self.h - 3
        self.vx, self.vy = random.choice((-1, 1)), -1
        self.pause = 0

    def tick(self):
        if self.pause:
            self.pause -= 1
            if self.pause == 0 and not self.bricks:
                self.reset()
            return
        nx, ny = self.bx + self.vx, self.by + self.vy
        if nx < 0 or nx >= self.w:
            self.vx = -self.vx; nx = self.bx + self.vx
        if ny < 0:
            self.vy = 1; ny = self.by + 1
        if (nx, ny) in self.bricks:
            self.bricks.discard((nx, ny)); self.vy = -self.vy; ny = self.by + self.vy
            if random.random() < 0.3:
                self.vx = random.choice((-1, 0, 1))
            if not self.bricks:
                self.pause = 8
        # paddle follows the ball, with a little lag
        target = nx - 1
        if random.random() < 0.95:
            self.px += (target > self.px) - (target < self.px)
        self.px = max(0, min(self.w - 2, self.px))
        if ny == self.h - 1:
            if self.px <= nx <= self.px + 1:
                self.vy = -1; ny = self.by - 1
                # the paddle steers: left cell angles left, right cell angles right, and
                # sometimes it goes straight up (which is what lets it reach every brick)
                if self.bricks and random.random() < 0.7:          # aim roughly at a remaining brick
                    bx = random.choice(sorted(self.bricks))[0]
                    self.vx = (bx > nx) - (bx < nx)
                else:
                    self.vx = random.choice((-1, 0, 1))
            else:
                self.pause = 4; self.bx, self.by, self.vy = self.w // 2, self.h - 3, -1
                return
        self.bx, self.by = nx, ny

    def render(self, boost=False):
        g = self.blank()
        for x, y in self.bricks:
            g[y][x] = self.ROWS[y % len(self.ROWS)]
        for k in (0, 1):
            self.put(g, self.px + k, self.h - 1, self.PAD)
        if not self.pause or self.pause % 2:
            self.put(g, self.bx, self.by, (255, 255, 0) if boost else self.BALL)
        return g


# ---------------------------------------------------------------- invaders --
class Invaders(Game):
    """Blocky original aliens march and descend; the ship below picks them off."""
    speed = 4
    ALIEN, SHIP, SHOT, BOOM = (200, 0, 255), (0, 255, 120), (255, 255, 255), (255, 120, 0)

    def reset(self):
        self.aliens = [[x, y] for y in range(0, 4, 2) for x in range(1, self.w - 1, 2)]
        self.dx = 1
        self.sx = self.w // 2
        self.shot = None
        self.booms = []
        self.t = 0

    def tick(self):
        self.t += 1
        self.booms = [(x, y, n - 1) for x, y, n in self.booms if n > 1]
        if not self.aliens:
            if self.t % 10 == 0:
                self.reset()
            return
        if self.t % 2 == 0:
            xs = [a[0] for a in self.aliens]
            if (self.dx > 0 and max(xs) >= self.w - 1) or (self.dx < 0 and min(xs) <= 0):
                self.dx = -self.dx
                for a in self.aliens:
                    a[1] += 1
                if max(a[1] for a in self.aliens) >= self.h - 2:
                    self.reset(); return
            else:
                for a in self.aliens:
                    a[0] += self.dx
        # ship hunts the lowest alien column
        target = min(self.aliens, key=lambda a: (-a[1], abs(a[0] - self.sx)))
        self.sx += (target[0] > self.sx) - (target[0] < self.sx)
        if self.shot is None and self.sx == target[0]:
            self.shot = [self.sx, self.h - 2]
        if self.shot:
            self.shot[1] -= 1
            hit = next((a for a in self.aliens if a[0] == self.shot[0] and a[1] == self.shot[1]), None)
            if hit:
                self.aliens.remove(hit); self.booms.append((hit[0], hit[1], 3)); self.shot = None
            elif self.shot[1] < 0:
                self.shot = None

    def render(self, boost=False):
        g = self.blank()
        for x, y in ((a[0], a[1]) for a in self.aliens):
            self.put(g, x, y, self.ALIEN if (self.t // 2 + x) % 2 else dim(self.ALIEN, 0.6))
        for x, y, n in self.booms:
            self.put(g, x, y, self.BOOM)
        self.put(g, self.sx, self.h - 1, (255, 255, 255) if boost else self.SHIP)
        if self.shot:
            self.put(g, self.shot[0], self.shot[1], self.SHOT)
        return g


# ----------------------------------------------------------------- frogger --
class Frogger(Game):
    """A frog crosses lanes of traffic, bottom to top, then starts again."""
    speed = 3
    FROG, CARS = (0, 255, 60), ((255, 60, 60), (255, 200, 0), (80, 120, 255), (255, 120, 200))

    def reset(self):
        self.lanes = []                                       # (y, dir, [car x positions])
        for i, y in enumerate(range(1, self.h - 1)):
            d = 1 if i % 2 else -1
            self.lanes.append([y, d, [random.randrange(self.w)]])
        self.fx, self.fy = self.w // 2, self.h - 1
        self.t = 0
        self.dead = 0

    def _occupied(self, x, y):
        for ly, d, cars in self.lanes:
            if ly == y and any((c + k) % self.w == x for c in cars for k in (0, 1)):
                return True
        return False

    def tick(self):
        self.t += 1
        if self.t % 2 == 0:
            for lane in self.lanes:
                lane[2] = [(c + lane[1]) % self.w for c in lane[2]]
                if random.random() < 0.06 and len(lane[2]) < 2:
                    lane[2].append((lane[2][0] + self.w // 2) % self.w)
        if self.dead:
            self.dead -= 1
            if self.dead == 0:
                self.fx, self.fy = self.w // 2, self.h - 1
            return
        if self._occupied(self.fx, self.fy):
            self.dead = 6; return
        if self.fy == 0:
            if self.t % 4 == 0:
                self.fx, self.fy = random.randrange(self.w), self.h - 1
            return

        def soon(x, y):                                     # occupied now, or after the next car move
            if self._occupied(x, y):
                return True
            for ly, d, cars in self.lanes:
                if ly == y and any((c + d + k) % self.w == x for c in cars for k in (0, 1)):
                    return True
            return False

        ny = self.fy - 1
        if not soon(self.fx, ny):
            self.fy = ny
        elif soon(self.fx, self.fy):                        # about to be hit: dodge sideways or back
            opts = [(self.fx + dx, self.fy) for dx in (-1, 1) if 0 <= self.fx + dx < self.w and not soon(self.fx + dx, self.fy)]
            if self.fy + 1 < self.h and not soon(self.fx, self.fy + 1):
                opts.append((self.fx, self.fy + 1))
            if opts:
                self.fx, self.fy = random.choice(opts)

    def render(self, boost=False):
        g = self.blank()
        for i, (ly, d, cars) in enumerate(self.lanes):
            for c in cars:
                for k in (0, 1):
                    self.put(g, (c + k) % self.w, ly, self.CARS[i % len(self.CARS)])
        c = (255, 255, 255) if (self.dead % 2) or boost else self.FROG
        self.put(g, self.fx, self.fy, c)
        return g


# ------------------------------------------------------------------- racer --
class Racer(Game):
    """Top-down racer: the road scrolls, the car dodges oncoming traffic."""
    speed = 3
    EDGE, CAR, OTHER = (255, 255, 255), (0, 220, 255), ((255, 60, 60), (255, 200, 0), (200, 80, 255))

    def reset(self):
        self.t = 0
        self.left = 1                                         # road spans left..right inclusive
        self.right = self.w - 2
        self.cx = self.w // 2
        self.traffic = []                                     # [x, y, colour]
        self.crash = 0

    def tick(self):
        self.t += 1
        if self.crash:
            self.crash -= 1
            if self.crash == 0:
                self.traffic = []
            return
        for car in self.traffic:
            car[1] += 1
        self.traffic = [c for c in self.traffic if c[1] < self.h]
        if self.t % 4 == 0 and len(self.traffic) < 3:
            self.traffic.append([random.randint(self.left, self.right), -1, random.choice(self.OTHER)])
        # steer away from the nearest car ahead in our column
        threats = [c for c in self.traffic if c[0] == self.cx and c[1] < self.h - 1]
        if threats:
            opts = [x for x in (self.cx - 1, self.cx + 1) if self.left <= x <= self.right
                    and not any(c[0] == x and c[1] >= self.h - 4 for c in self.traffic)]
            if opts:
                self.cx = random.choice(opts)
        if any(c[0] == self.cx and c[1] == self.h - 1 for c in self.traffic):
            self.crash = 6

    def render(self, boost=False):
        g = self.blank()
        for y in range(self.h):
            if (y + self.t) % 2 == 0:
                self.put(g, self.left - 1, y, dim(self.EDGE, 0.5)); self.put(g, self.right + 1, y, dim(self.EDGE, 0.5))
        for x, y, c in self.traffic:
            self.put(g, x, y, c)
        c = (255, 120, 0) if self.crash and self.crash % 2 else ((255, 255, 255) if boost else self.CAR)
        self.put(g, self.cx, self.h - 1, c)
        self.put(g, self.cx, self.h - 2, dim(c, 0.5))
        return g


# ------------------------------------------------------------------- simon --
class Simon(Game):
    """Four colour quadrants light in a growing sequence, then the sequence is replayed."""
    speed = 5
    COLS = ((255, 40, 40), (40, 220, 40), (40, 80, 255), (255, 220, 0))

    def reset(self):
        self.seq = [random.randrange(4)]
        self.pos = 0
        self.phase = "show"          # show -> replay -> grow
        self.on = 0                  # ticks the current pad stays lit

    def tick(self):
        if self.on:
            self.on -= 1
            return
        if self.phase in ("show", "replay"):
            if self.pos < len(self.seq):
                self.lit = self.seq[self.pos]
                self.on = 2 if self.phase == "show" else 1
                self.pos += 1
            else:
                self.lit = None
                self.pos = 0
                self.on = 2
                if self.phase == "show":
                    self.phase = "replay"
                else:
                    self.phase = "grow"
        else:
            if len(self.seq) >= 8:
                self.seq = []
                self.lit = "win"; self.on = 4
            self.seq.append(random.randrange(4))
            self.phase = "show"

    def render(self, boost=False):
        g = self.blank()
        hw, hh = self.w // 2, self.h // 2
        lit = getattr(self, "lit", None)
        for i, (qx, qy) in enumerate(((0, 0), (hw, 0), (0, hh), (hw, hh))):
            c = self.COLS[i]
            f = 1.0 if (lit == i or lit == "win") else (0.35 if boost else 0.15)
            for y in range(qy, qy + hh):
                for x in range(qx, qx + hw):
                    if (x - qx) in (0, hw - 1) or (y - qy) in (0, hh - 1) or lit == i or lit == "win":
                        g[y][x] = dim(c, f)
        return g


# ---------------------------------------------------------- missile command --
class MissileCommand(Game):
    speed = 3
    CITY, TRAIL, WARHEAD, BURST = (0, 200, 255), (120, 40, 40), (255, 60, 60), (255, 220, 120)

    def reset(self):
        self.cities = [1, self.w // 2, self.w - 2]
        self.missiles = []           # [x, y, tx (target x), trail list]
        self.bursts = []             # [x, y, r, ttl]
        self.t = 0
        self.pause = 0

    def tick(self):
        self.t += 1
        if self.pause:
            self.pause -= 1
            if self.pause == 0:
                self.reset()
            return
        if self.t % 5 == 0 and len(self.missiles) < 3 and self.cities:
            tx = random.choice(self.cities)
            self.missiles.append([random.randrange(self.w), 0, tx, []])
        for m in self.missiles:
            m[3] = ([(m[0], m[1])] + m[3])[:2]
            m[1] += 1
            if m[0] != m[2] and random.random() < 0.6:
                m[0] += 1 if m[2] > m[0] else -1
        # interceptor: burst above the lowest missile once it's halfway down
        for m in self.missiles:
            if m[1] == self.h - 4 and random.random() < 0.85:
                self.bursts.append([m[0], m[1] + 1, 0, 4])
        for b in self.bursts:
            b[2] = min(b[2] + 1, 2); b[3] -= 1
        self.bursts = [b for b in self.bursts if b[3] > 0]
        keep = []
        for m in self.missiles:
            if any(abs(m[0] - b[0]) <= b[2] and abs(m[1] - b[1]) <= b[2] for b in self.bursts):
                continue
            if m[1] >= self.h - 1:
                if m[0] in self.cities:
                    self.cities.remove(m[0])
                    self.bursts.append([m[0], self.h - 1, 1, 3])
                continue
            keep.append(m)
        self.missiles = keep
        if not self.cities:
            self.pause = 10

    def render(self, boost=False):
        g = self.blank()
        for cx in self.cities:
            self.put(g, cx, self.h - 1, (255, 255, 255) if boost else self.CITY)
            self.put(g, cx + 1, self.h - 1, self.CITY)
        for m in self.missiles:
            for i, (x, y) in enumerate(m[3]):
                self.put(g, x, y, dim(self.TRAIL, 1.0 - 0.4 * i))
            self.put(g, m[0], m[1], self.WARHEAD)
        for x, y, r, ttl in self.bursts:
            for dy in range(-r, r + 1):
                for dx in range(-r, r + 1):
                    if abs(dx) + abs(dy) <= r:
                        self.put(g, x + dx, y + dy, dim(self.BURST, ttl / 4))
        return g


# ---------------------------------------------------------------- asteroids --
class Asteroids(Game):
    speed = 3
    SHIP, NOSE, ROCK, SHOT = (255, 255, 255), (120, 120, 120), (160, 120, 90), (255, 255, 0)
    DIRS = ((0, -1), (1, -1), (1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0), (-1, -1))

    def reset(self):
        self.sx, self.sy = self.w // 2, self.h // 2
        self.heading = 0
        self.rocks = []
        self.shots = []               # [x, y, dx, dy]
        self.flash = []
        self.t = 0
        self._spawn()

    def _spawn(self):
        for _ in range(3):
            x, y = random.choice((0, self.w - 1)), random.randrange(self.h)
            self.rocks.append([float(x), float(y), random.choice((-0.5, 0.5)), random.choice((-0.5, 0.5)), 2])

    def tick(self):
        self.t += 1
        self.flash = [(x, y, n - 1) for x, y, n in self.flash if n > 1]
        for r in self.rocks:
            r[0] = (r[0] + r[2]) % self.w; r[1] = (r[1] + r[3]) % self.h
        if not self.rocks and self.t % 6 == 0:
            self._spawn()
        # aim at the nearest rock (8 directions), turn one step per tick, shoot when lined up
        if self.rocks:
            r = min(self.rocks, key=lambda r: abs(r[0] - self.sx) + abs(r[1] - self.sy))
            dx, dy = r[0] - self.sx, r[1] - self.sy
            want = self.DIRS.index((int((dx > 0.5) - (dx < -0.5)), int((dy > 0.5) - (dy < -0.5)))) if (abs(dx) > 0.5 or abs(dy) > 0.5) else self.heading
            if want != self.heading:
                self.heading = (self.heading + (1 if (want - self.heading) % 8 <= 4 else -1)) % 8
            elif self.t % 2 == 0 and len(self.shots) < 2:
                ddx, ddy = self.DIRS[self.heading]
                self.shots.append([self.sx + ddx, self.sy + ddy, ddx, ddy])
        keep = []
        for s in self.shots:
            s[0] += s[2]; s[1] += s[3]
            if not (0 <= s[0] < self.w and 0 <= s[1] < self.h):
                continue
            hit = next((r for r in self.rocks if int(r[0]) == s[0] and int(r[1]) == s[1]), None)
            if hit:
                self.rocks.remove(hit)
                self.flash.append((s[0], s[1], 3))
                if hit[4] == 2:
                    for vx, vy in ((0.7, 0.3), (-0.3, -0.7)):
                        self.rocks.append([hit[0], hit[1], vx, vy, 1])
                continue
            keep.append(s)
        self.shots = keep

    def render(self, boost=False):
        g = self.blank()
        for r in self.rocks:
            x, y = int(r[0]), int(r[1])
            self.put(g, x, y, self.ROCK)
            if r[4] == 2:
                self.put(g, (x + 1) % self.w, y, dim(self.ROCK, 0.7))
        for x, y, n in self.flash:
            self.put(g, x, y, (255, 200, 100))
        for s in self.shots:
            self.put(g, s[0], s[1], self.SHOT)
        ddx, ddy = self.DIRS[self.heading]
        self.put(g, self.sx + ddx, self.sy + ddy, self.NOSE)
        self.put(g, self.sx, self.sy, (255, 255, 0) if boost else self.SHIP)
        return g


# --------------------------------------------------------------- cave flyer --
class CaveFlyer(Game):
    speed = 3
    ROCK, SHIP, FLAME = (90, 60, 120), (0, 255, 200), (255, 140, 0)

    def reset(self):
        self.cols = deque([(2, 5)] * self.w, maxlen=self.w)   # (ceiling row, floor row) per column: open between
        self.top, self.bot = 2, 5
        self.y = 3.5
        self.crash = 0
        self.t = 0

    def tick(self):
        self.t += 1
        if self.crash:
            self.crash -= 1
            if self.crash == 0:
                self.reset()
            return
        if self.t % 3 == 0:
            gap = self.bot - self.top
            move = random.choice((-1, 0, 0, 1))
            self.top = max(0, min(self.h - 4, self.top + move))
            gap = max(3, min(4, gap + random.choice((-1, 0, 0, 1))))
            self.bot = min(self.h - 1, self.top + gap)
        self.cols.append((self.top, self.bot))
        # ship at column 2 steers toward the middle of the gap ahead, one row per tick at most
        top, bot = self.cols[3]
        target = (top + bot) / 2
        self.y += max(-1, min(1, target - self.y))
        top, bot = self.cols[2]
        if not (top < int(round(self.y)) < bot):
            if random.random() < 0.15:                      # now and then it really does clip the wall
                self.crash = 6
            else:
                self.y = max(top + 1, min(bot - 1, self.y))

    def render(self, boost=False):
        g = self.blank()
        for x, (top, bot) in enumerate(self.cols):
            for y in range(self.h):
                if y <= top or y >= bot:
                    g[y][x] = self.ROCK
        y = int(round(self.y))
        self.put(g, 2, y, (255, 255, 255) if (self.crash % 2) or boost else self.SHIP)
        if not self.crash and self.t % 2:
            self.put(g, 1, y, self.FLAME)
        return g


# ------------------------------------------------------------------ flappy --
class Flappy(Game):
    speed = 3
    WALL, BIRD, WING = (40, 200, 60), (255, 220, 0), (255, 140, 0)

    def reset(self):
        self.walls = deque([None] * self.w, maxlen=self.w)   # gap top row or None
        self.y, self.vy = self.h / 2, 0.0
        self.t = 0
        self.crash = 0
        self.flap = 0

    def tick(self):
        self.t += 1
        if self.crash:
            self.crash -= 1
            if self.crash == 0:
                self.reset()
            return
        prev = next((gt for gt in reversed(self.walls) if gt is not None), self.h // 2 - 1)
        self.walls.append(max(1, min(self.h - 4, prev + random.randint(-2, 2))) if self.t % 5 == 0 else None)
        nxt = next((gt for gt in list(self.walls)[2:] if gt is not None), self.h // 2 - 1)
        centre = nxt + 1
        self.vy = min(0.9, self.vy + 0.3)
        if self.y + self.vy > centre + 0.4:
            self.vy = -0.8; self.flap = 1
        else:
            self.flap = 0
        self.y = max(0, min(self.h - 1, self.y + self.vy))
        gt = self.walls[2]
        yi = int(round(self.y))
        if gt is not None and not (gt <= yi <= gt + 2):
            if random.random() < 0.3:
                self.crash = 6
            else:
                self.y = float(max(gt, min(gt + 2, yi)))

    def render(self, boost=False):
        g = self.blank()
        for x, gt in enumerate(self.walls):
            if gt is not None:
                for y in range(self.h):
                    if not (gt <= y <= gt + 2):
                        g[y][x] = self.WALL
        y = int(round(self.y))
        self.put(g, 2, y, (255, 255, 255) if (self.crash % 2) or boost else self.BIRD)
        self.put(g, 1, y - 1 if self.flap else y, self.WING)
        return g


# --------------------------------------------------------------- centipede --
class Centipede(Game):
    speed = 3
    SEG, HEAD, SHROOM, GUN, SHOT = (0, 200, 60), (120, 255, 60), (200, 60, 120), (0, 160, 255), (255, 255, 255)

    def reset(self):
        self.shrooms = {(random.randrange(self.w), random.randrange(1, self.h - 2)) for _ in range(6)}
        self.body = deque([(x, 0) for x in range(min(5, self.w))])   # head first
        self.dir = 1
        self.gx = self.w // 2
        self.shot = None
        self.t = 0
        self.pause = 0

    def tick(self):
        self.t += 1
        if self.pause:
            self.pause -= 1
            if self.pause == 0:
                self.reset()
            return
        if self.body:
            hx, hy = self.body[0]
            nx = hx + self.dir
            if nx < 0 or nx >= self.w or (nx, hy) in self.shrooms:
                self.dir = -self.dir
                nx, hy = hx, hy + 1
            self.body.appendleft((nx, hy))
            self.body.pop()
            if hy >= self.h - 1:
                self.pause = 6
        # gun shadows the head and shoots
        if self.body:
            self.gx += (self.body[0][0] > self.gx) - (self.body[0][0] < self.gx)
        if self.shot is None and self.t % 2 == 0:
            self.shot = [self.gx, self.h - 2]
        if self.shot:
            self.shot[1] -= 1
            pos = (self.shot[0], self.shot[1])
            if pos in self.body:
                idx = list(self.body).index(pos)
                self.shrooms.add(pos)
                body = list(self.body)
                del body[idx]
                self.body = deque(body)
                self.shot = None
                if not self.body:
                    self.pause = 6
            elif pos in self.shrooms:
                self.shrooms.discard(pos); self.shot = None
            elif self.shot[1] < 0:
                self.shot = None

    def render(self, boost=False):
        g = self.blank()
        for x, y in self.shrooms:
            self.put(g, x, y, self.SHROOM)
        for i, (x, y) in enumerate(self.body):
            self.put(g, x, y, self.HEAD if i == 0 else self.SEG)
        self.put(g, self.gx, self.h - 1, (255, 255, 255) if boost else self.GUN)
        if self.shot:
            self.put(g, self.shot[0], self.shot[1], self.SHOT)
        return g


# ------------------------------------------------------------------- tanks --
class Tanks(Game):
    speed = 3
    A, B, WALL, SHELL = (0, 220, 80), (255, 120, 0), (110, 110, 110), (255, 255, 255)

    def reset(self):
        self.ay, self.by = random.randrange(self.h), random.randrange(self.h)
        self.walls = {(self.w // 2 - 1 + random.randrange(2), y) for y in random.sample(range(self.h), 3)}
        self.shells = []             # [x, y, dx]
        self.hit = []                # [x, y, ttl]
        self.t = 0

    def tick(self):
        self.t += 1
        self.hit = [(x, y, n - 1) for x, y, n in self.hit if n > 1]
        # each tank creeps toward the other's row (with some dithering) and fires when level
        for me, other in (("ay", "by"), ("by", "ay")):
            y, oy = getattr(self, me), getattr(self, other)
            if random.random() < 0.7:
                y += (oy > y) - (oy < y)
            elif random.random() < 0.3:
                y += random.choice((-1, 1))
            setattr(self, me, max(0, min(self.h - 1, y)))
        if self.ay == self.by and self.t % 3 == 0:
            self.shells.append([1, self.ay, 1] if random.random() < 0.5 else [self.w - 2, self.by, -1])
        keep = []
        for s in self.shells:
            s[0] += s[2]
            pos = (s[0], s[1])
            if pos in self.walls:
                self.walls.discard(pos); self.hit.append((s[0], s[1], 2)); continue
            if s[0] <= 0 and s[1] == self.ay or s[0] >= self.w - 1 and s[1] == self.by:
                self.hit.append((s[0], s[1], 4))
                if s[0] <= 0:
                    self.ay = random.randrange(self.h)
                else:
                    self.by = random.randrange(self.h)
                continue
            if 0 <= s[0] < self.w:
                keep.append(s)
        self.shells = keep
        if len(self.walls) < 2 and self.t % 8 == 0:
            self.walls.add((self.w // 2 - 1 + random.randrange(2), random.randrange(self.h)))

    def render(self, boost=False):
        g = self.blank()
        for x, y in self.walls:
            self.put(g, x, y, self.WALL)
        self.put(g, 0, self.ay, (255, 255, 255) if boost else self.A); self.put(g, 1, self.ay, dim(self.A, 0.5))
        self.put(g, self.w - 1, self.by, self.B); self.put(g, self.w - 2, self.by, dim(self.B, 0.5))
        for x, y, ttl in self.hit:
            self.put(g, x, y, (255, 200, 80))
        for x, y, _ in self.shells:
            self.put(g, x, y, self.SHELL)
        return g


# ------------------------------------------------------------ lunar lander --
class LunarLander(Game):
    speed = 3
    LANDER, FLAME, PAD, GROUND = (220, 220, 220), (255, 160, 0), (0, 255, 120), (80, 60, 40)

    def reset(self):
        self.pad = random.randrange(1, self.w - 2)
        self.x, self.y = float(random.randrange(self.w)), 0.0
        self.vy, self.vx = 0.0, 0.0
        self.thrust = False
        self.done = 0
        self.ok = False

    def tick(self):
        if self.done:
            self.done -= 1
            if self.done == 0:
                self.reset()
            return
        self.vy += 0.18
        self.vx += 0.15 * ((self.pad + 0.5 > self.x + 0.5) - (self.pad + 0.5 < self.x - 0.5))
        self.vx = max(-0.5, min(0.5, self.vx))
        self.thrust = self.vy > 0.45 and self.y > 1 and random.random() < 0.9
        if self.thrust:
            self.vy -= 0.35
        self.x = max(0, min(self.w - 1, self.x + self.vx))
        self.y += self.vy
        if self.y >= self.h - 2:
            self.y = self.h - 2
            self.ok = self.vy < 0.9 and self.pad <= round(self.x) <= self.pad + 1
            self.done = 8

    def render(self, boost=False):
        g = self.blank()
        for x in range(self.w):
            g[self.h - 1][x] = self.GROUND
        self.put(g, self.pad, self.h - 1, self.PAD); self.put(g, self.pad + 1, self.h - 1, self.PAD)
        x, y = int(round(self.x)), int(round(self.y))
        if self.done:
            c = (0, 255, 0) if self.ok else (255, 60, 0)
            if self.done % 2:
                self.put(g, x, y, c); self.put(g, x - 1, y, dim(c, 0.5)); self.put(g, x + 1, y, dim(c, 0.5))
            return g
        self.put(g, x, y, (255, 255, 0) if boost else self.LANDER)
        if self.thrust:
            self.put(g, x, y + 1, self.FLAME)
        return g


# ----------------------------------------------------------------- pinball --
class Pinball(Game):
    speed = 2
    BALL, BUMP, FLIP, WALL = (220, 220, 220), (255, 60, 180), (0, 200, 255), (60, 60, 60)

    def reset(self):
        self.bumpers = [(2, 2), (5, 2), (self.w // 2, 4)]
        self.lit = {}
        self.x, self.y = float(self.w - 1), float(self.h - 3)
        self.vx, self.vy = -0.6, -1.6
        self.flip = 0
        self.lost = 0
        self.balls = 0

    def tick(self):
        for k in list(self.lit):
            self.lit[k] -= 1
            if self.lit[k] <= 0:
                del self.lit[k]
        if self.lost:
            self.lost -= 1
            if self.lost == 0:
                self.x, self.y, self.vx, self.vy = float(self.w - 1), float(self.h - 3), -0.6, -1.6
            return
        if self.flip:
            self.flip -= 1
        self.vy += 0.16
        nx, ny = self.x + self.vx, self.y + self.vy
        if nx < 0 or nx > self.w - 1:
            self.vx = -self.vx * 0.9; nx = max(0, min(self.w - 1, nx))
        if ny < 0:
            self.vy = -self.vy * 0.8; ny = 0
        for bx, by in self.bumpers:
            if abs(nx - bx) < 1 and abs(ny - by) < 1:
                self.lit[(bx, by)] = 3
                ang = random.uniform(-1, 1)
                self.vx = (nx - bx) * 1.2 + ang * 0.6
                self.vy = -abs(self.vy) * 0.9 - 0.6 if ny <= by else abs(self.vy) * 0.6 + 0.3
                nx, ny = self.x + self.vx, self.y + self.vy
        if ny >= self.h - 1:
            xi = int(round(nx))
            if xi <= 2 or xi >= self.w - 3 or random.random() < 0.6:   # flipper reach (the middle is a gamble)
                self.flip = 2
                self.vy = -1.9 - random.random() * 0.5
                self.vx = (0.4 + random.random() * 0.6) * (1 if xi <= 2 else -1)
                ny = self.h - 2
            else:                                              # drained
                self.lost = 5; self.balls += 1
                return
        self.x, self.y = max(0, min(self.w - 1, nx)), max(0, min(self.h - 1, ny))

    def render(self, boost=False):
        g = self.blank()
        for bx, by in self.bumpers:
            self.put(g, bx, by, self.BUMP if (bx, by) in self.lit else dim(self.BUMP, 0.35))
        for x in (0, 1, 2):
            self.put(g, x, self.h - 1 - (1 if self.flip and self.vx > 0 and x == 2 else 0), self.FLIP)
        for x in (self.w - 3, self.w - 2, self.w - 1):
            self.put(g, x, self.h - 1 - (1 if self.flip and self.vx < 0 and x == self.w - 3 else 0), self.FLIP)
        if not self.lost or self.lost % 2:
            self.put(g, int(round(self.x)), int(round(self.y)), (255, 255, 0) if boost else self.BALL)
        return g


# --------------------------------------------------------------- lights out --
class LightsOut(Game):
    """4x4 puzzle in 2x2 blocks: scrambles itself, then solves itself one press at a time."""
    speed = 5
    ON, OFFC, PRESS = (255, 200, 0), (30, 20, 0), (255, 255, 255)

    def reset(self):
        self.n = min(self.w, self.h) // 2
        self.grid = [[0] * self.n for _ in range(self.n)]
        self.todo = []
        self.pressing = None
        self.phase = "scramble"
        self.wait = 2

    def _press(self, x, y):
        for px, py in ((x, y), (x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if 0 <= px < self.n and 0 <= py < self.n:
                self.grid[py][px] ^= 1

    def tick(self):
        if self.wait:
            self.wait -= 1
            return
        if self.phase == "scramble":
            cells = random.sample([(x, y) for x in range(self.n) for y in range(self.n)], random.randint(3, 6))
            for c in cells:
                self._press(*c)
            self.todo = cells[::-1]
            self.phase = "solve"; self.wait = 3
        elif self.todo:
            self.pressing = self.todo.pop()
            self._press(*self.pressing)
            self.wait = 1
        else:
            self.pressing = None
            self.phase = "scramble"; self.wait = 4

    def render(self, boost=False):
        g = self.blank()
        for y in range(self.n):
            for x in range(self.n):
                c = self.ON if self.grid[y][x] else self.OFFC
                if self.pressing == (x, y) and self.wait:
                    c = self.PRESS
                elif boost and self.grid[y][x]:
                    c = (255, 255, 200)
                for dy in (0, 1):
                    for dx in (0, 1):
                        self.put(g, x * 2 + dx, y * 2 + dy, c)
        return g


# ------------------------------------------------------------------ skiing --
class Skiing(Game):
    speed = 3
    L, R, SKIER, TRAIL = (255, 60, 60), (60, 120, 255), (255, 255, 255), (200, 220, 255)

    def reset(self):
        self.gates = deque([None] * self.h, maxlen=self.h)   # per row: gap left x, or None
        self.x = self.w // 2
        self.t = 0
        self.miss = 0
        self.trail = deque(maxlen=3)

    def tick(self):
        self.t += 1
        if self.miss:
            self.miss -= 1
            return
        if self.t % 4 == 0:
            prev = next((gx for gx in reversed(self.gates) if gx is not None), self.w // 2 - 2)
            self.gates.append(max(0, min(self.w - 4, prev + random.randint(-2, 2))))   # enters at the bottom, scrolls up
        else:
            self.gates.append(None)
        nxt = next((gx for gx in list(self.gates)[1:] if gx is not None), None)
        if nxt is not None:
            target = nxt + 1 + (nxt % 2)                    # left or right side of the gate, per gate
            self.x += (target > self.x) - (target < self.x)
        self.trail.appendleft(self.x)
        gx = self.gates[1]
        if gx is not None and (not (gx < self.x < gx + 3) or random.random() < 0.05):
            self.miss = 4

    def render(self, boost=False):
        g = self.blank()
        for y, gx in enumerate(self.gates):
            if gx is not None:
                self.put(g, gx, y, self.L); self.put(g, gx + 3, y, self.R)
        for i, tx in enumerate(self.trail):
            self.put(g, tx, 0 if i == 0 else -1, self.TRAIL)
        c = (255, 80, 0) if self.miss and self.miss % 2 else ((255, 255, 0) if boost else self.SKIER)
        self.put(g, self.x, 1, c)
        return g


# ------------------------------------------------------------------ digger --
class Digger(Game):
    """A miner tunnels through dirt; two critters roam the tunnels after it."""
    speed = 3
    DIRT, TUNNEL, MINER, CRITTER, GEM = (110, 70, 30), (20, 12, 5), (255, 220, 0), (255, 60, 60), (0, 255, 200)

    def reset(self):
        self.dug = {(self.w // 2, 0)}
        self.mx, self.my = self.w // 2, 0
        self.dir = (0, 1)
        self.critters = []
        self.gems = {(random.randrange(self.w), random.randrange(2, self.h)) for _ in range(3)}
        self.t = 0
        self.caught = 0

    def tick(self):
        self.t += 1
        if self.caught:
            self.caught -= 1
            if self.caught == 0:
                self.reset()
            return
        # miner: keep going, prefer undug dirt, turn at walls / randomly
        opts = []
        for dx, dy in ((0, 1), (1, 0), (-1, 0), (0, -1)):
            nx, ny = self.mx + dx, self.my + dy
            if 0 <= nx < self.w and 0 <= ny < self.h:
                weight = 3 if (nx, ny) not in self.dug else 1
                if (dx, dy) == self.dir:
                    weight += 2
                if (nx, ny) in self.gems:
                    weight += 6
                opts += [(dx, dy)] * weight
        self.dir = random.choice(opts)
        self.mx += self.dir[0]; self.my += self.dir[1]
        self.dug.add((self.mx, self.my))
        self.gems.discard((self.mx, self.my))
        if len(self.gems) < 3 and self.t % 10 == 0:
            self.gems.add((random.randrange(self.w), random.randrange(1, self.h)))
        if self.t % 12 == 0 and len(self.critters) < 2:
            self.critters.append([self.w // 2, 0])
        if self.t % 2 == 0:
            for c in self.critters:
                steps = [(c[0] + dx, c[1] + dy) for dx, dy in ((0, 1), (1, 0), (-1, 0), (0, -1))
                         if (c[0] + dx, c[1] + dy) in self.dug]
                if steps:
                    best = min(steps, key=lambda p: abs(p[0] - self.mx) + abs(p[1] - self.my))
                    c[0], c[1] = best if random.random() < 0.7 else random.choice(steps)
                if (c[0], c[1]) == (self.mx, self.my):
                    self.caught = 6

    def render(self, boost=False):
        g = self.blank()
        for y in range(self.h):
            for x in range(self.w):
                g[y][x] = self.TUNNEL if (x, y) in self.dug else self.DIRT
        for x, y in self.gems:
            self.put(g, x, y, self.GEM)
        for c in self.critters:
            self.put(g, c[0], c[1], self.CRITTER)
        mc = (255, 255, 255) if (self.caught % 2) or boost else self.MINER
        self.put(g, self.mx, self.my, mc)
        return g


GAMES = {
    "runner": Runner,
    "climber": Climber,
    "pong": Pong,
    "snake": Snake,
    "breakout": Breakout,
    "invaders": Invaders,
    "frogger": Frogger,
    "racer": Racer,
    "simon": Simon,
    "missile": MissileCommand,
    "asteroids": Asteroids,
    "cave": CaveFlyer,
    "flappy": Flappy,
    "centipede": Centipede,
    "tanks": Tanks,
    "lander": LunarLander,
    "pinball": Pinball,
    "lightsout": LightsOut,
    "skiing": Skiing,
    "digger": Digger,
}
