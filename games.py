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
            if not self.bricks:
                self.pause = 8
        # paddle follows the ball, with a little lag
        target = nx - 1
        if random.random() < 0.85:
            self.px += (target > self.px) - (target < self.px)
        self.px = max(0, min(self.w - 2, self.px))
        if ny == self.h - 1:
            if self.px <= nx <= self.px + 1:
                self.vy = -1; ny = self.by - 1
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
        # hop up when the next lane cell is clear now and won't be next step
        ny = self.fy - 1
        if not self._occupied(self.fx, ny) and not any(
                ly == ny and any((c + d + k) % self.w == self.fx for c in cars for k in (0, 1))
                for ly, d, cars in self.lanes):
            self.fy = ny
        elif random.random() < 0.3:
            nx = self.fx + random.choice((-1, 1))
            if 0 <= nx < self.w and not self._occupied(nx, self.fy):
                self.fx = nx

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


GAMES = {
    "runner": Runner,
    "climber": Climber,
    "pong": Pong,
    "snake": Snake,
    "breakout": Breakout,
    "invaders": Invaders,
    "frogger": Frogger,
    "racer": Racer,
}
