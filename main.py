"""Twin Stick Drift - top-down arena shooter for a PS4 controller (keyboard + mouse fallback).

Pad: left stick move | right stick aim | R2 fire | L1 dash | Options/Enter restart
Keys: WASD move | mouse aim | LMB fire | SPACE dash | R restart
"""
import math
import random
import sys
from array import array

import pygame

SR = 44100

W, H = 1280, 720
DEADZONE = 0.2
# SDL2 mapping for the PS4 pad in pygame 2.x
AX_LX, AX_LY, AX_RX, AX_RY, AX_L2, AX_R2 = 0, 1, 2, 3, 4, 5
BTN_L1, BTN_OPTIONS = 9, 6

CYAN, PINK, YELLOW, GREEN, WHITE = (0, 255, 230), (255, 60, 140), (255, 220, 60), (80, 255, 120), (255, 255, 255)
BTN_R1 = 10
ORANGE, BLUE = (255, 140, 40), (90, 150, 255)
# kind -> (letter, colour)
PICKUPS = {"triple": ("3", GREEN), "shield": ("S", BLUE), "bomb": ("B", ORANGE), "heal": ("+", PINK)}


def synth(f0, f1, dur, vol=0.5, wave="square", decay=3.0):
    """Procedural sound: pitch sweeps f0 -> f1 over dur seconds, exponential fade-out."""
    n = int(SR * dur)
    buf, phase = array("h"), 0.0
    for i in range(n):
        t = i / n
        phase += (f0 + (f1 - f0) * t) / SR
        if wave == "square":
            s = 1.0 if phase % 1 < 0.5 else -1.0
        elif wave == "sine":
            s = math.sin(phase * math.tau)
        else:
            s = random.uniform(-1, 1)
        buf.append(int(s * vol * math.exp(-decay * t) * 32767))
    return pygame.mixer.Sound(buffer=buf.tobytes())


def make_music():
    """Short synthwave loop: Am - F - C - G, bass + arpeggio."""
    step = 0.1875
    chords = [(55.0, [220, 262, 330, 262]), (43.65, [175, 220, 262, 220]),
              (65.41, [262, 330, 392, 330]), (49.0, [196, 247, 294, 247])]
    buf = array("h")
    for bass, arp in chords:
        for st in range(4):
            for k in range(2):  # two 8th-notes per step
                f = arp[st] * (2 if k else 1)
                n = int(SR * step / 2)
                for i in range(n):
                    t = i / n
                    env = math.exp(-4 * t)
                    a = (1.0 if (i * f / SR) % 1 < 0.5 else -1.0) * 0.12 * env
                    b = math.sin(i * bass / SR * math.tau) * 0.35 * (1 if st % 2 == 0 else 0.6)
                    buf.append(int((a + b) * 32767))
    return pygame.mixer.Sound(buffer=buf.tobytes())


def stick(joy, ax, ay):
    x, y = joy.get_axis(ax), joy.get_axis(ay)
    mag = math.hypot(x, y)
    if mag < DEADZONE:
        return pygame.Vector2()
    scale = min(1.0, (mag - DEADZONE) / (1 - DEADZONE)) / mag  # rescale so output ramps from 0 at the deadzone edge
    return pygame.Vector2(x * scale, y * scale)


def rumble(joy, low, high, ms):
    if joy:
        try:
            joy.rumble(low, high, ms)
        except pygame.error:
            pass


class Particle:
    def __init__(self, pos, color, speed=240, life=0.5):
        a = random.uniform(0, math.tau)
        self.pos = pygame.Vector2(pos)
        self.vel = pygame.Vector2(math.cos(a), math.sin(a)) * random.uniform(0.2, 1) * speed
        self.color, self.life, self.max = color, life, life

    def update(self, dt):
        self.pos += self.vel * dt
        self.vel *= 0.94
        self.life -= dt


class Enemy:
    def __init__(self, kind, wave):
        side = random.choice("tblr")
        self.pos = pygame.Vector2({"t": (random.randint(0, W), -30), "b": (random.randint(0, W), H + 30),
                                   "l": (-30, random.randint(0, H)), "r": (W + 30, random.randint(0, H))}[side])
        self.kind = kind
        spd = 1 + wave * 0.04
        if kind == "chaser":
            self.hp, self.r, self.speed, self.color = 1, 14, 150 * spd, PINK
        elif kind == "shooter":
            self.hp, self.r, self.speed, self.color = 3, 18, 80 * spd, YELLOW
        else:  # boss
            self.hp, self.r, self.speed, self.color = 40 + wave * 4, 48, 70, WHITE
        self.max_hp, self.cool = self.hp, random.uniform(1, 2)


class Game:
    def __init__(self):
        pygame.mixer.pre_init(SR, -16, 1, 512)
        pygame.init()
        try:
            self.sfx = {
                "shoot": synth(900, 300, 0.07, 0.15, "square", 5),
                "kill": synth(300, 40, 0.25, 0.5, "noise", 5),
                "boss": synth(120, 20, 0.8, 0.7, "noise", 3),
                "hurt": synth(220, 50, 0.4, 0.6, "square", 4),
                "dash": synth(200, 1200, 0.18, 0.3, "sine", 3),
                "wave": synth(400, 800, 0.35, 0.3, "sine", 2),
                "over": synth(400, 60, 1.2, 0.5, "square", 2),
                "start": synth(300, 1500, 0.4, 0.4, "square", 3),
                "pickup": synth(600, 1400, 0.15, 0.3, "sine", 2),
                "bomb": synth(200, 20, 1.0, 0.8, "noise", 2.5),
            }
            self.music = make_music()
            self.music.set_volume(0.5)
        except pygame.error:  # no audio device: play silently
            self.sfx, self.music = {}, None
        self.state = "title"
        self.tick = 0.0
        self.screen = pygame.display.set_mode((W, H))
        pygame.display.set_caption("Twin Stick Drift")
        self.clock = pygame.time.Clock()
        self.font = pygame.font.SysFont("consolas", 24)
        self.big = pygame.font.SysFont("consolas", 64, bold=True)
        self.trail = pygame.Surface((W, H), pygame.SRCALPHA)
        self.joy = None
        self.connect()
        self.reset()

    def play(self, name):
        if name in self.sfx:
            self.sfx[name].play()

    def begin(self):
        self.reset()
        self.state = "play"
        self.play("start")
        if self.music:
            self.music.play(loops=-1)

    def to_title(self):
        self.state = "title"
        if self.music:
            self.music.fadeout(500)

    def connect(self):
        if pygame.joystick.get_count() and not self.joy:
            self.joy = pygame.joystick.Joystick(0)
            self.joy.init()

    def reset(self):
        self.pos = pygame.Vector2(W / 2, H / 2)
        self.vel = pygame.Vector2()
        self.aim = pygame.Vector2(1, 0)
        self.hp, self.score, self.wave = 5, 0, 0
        self.mult, self.mult_t = 1, 0.0
        self.bullets, self.ebullets, self.enemies, self.parts = [], [], [], []
        self.pickups = []  # [pos, kind, time_left]
        self.triple_t, self.shield, self.bombs, self.bomb_held = 0.0, False, 0, True
        self.fire_cd = self.dash_cd = self.dash_t = self.inv = self.shake = 0.0
        self.to_spawn = []
        self.dead = False

    def start_wave(self):
        self.wave += 1
        self.play("wave")
        n = 4 + self.wave * 2
        self.to_spawn = ["chaser"] * n + ["shooter"] * (self.wave // 2)
        if self.wave % 5 == 0:
            self.to_spawn.append("boss")
        random.shuffle(self.to_spawn)
        self.spawn_t = 0.0

    def burst(self, pos, color, n=14, speed=240):
        self.parts += [Particle(pos, color, speed) for _ in range(n)]

    def collect(self, kind):
        self.play("pickup")
        self.burst(self.pos, PICKUPS[kind][1], 18, 260)
        rumble(self.joy, 0.0, 0.4, 100)
        if kind == "triple":
            self.triple_t = 10.0
        elif kind == "shield":
            self.shield = True
        elif kind == "bomb":
            self.bombs = min(3, self.bombs + 1)
        else:
            self.hp = min(5, self.hp + 1)

    def hurt(self):
        if self.inv > 0 or self.dash_t > 0:
            return
        if self.shield:
            self.shield = False
            self.inv = 0.8
            self.burst(self.pos, BLUE, 24, 350)
            rumble(self.joy, 0.5, 0.5, 150)
            self.play("hurt")
            return
        self.hp -= 1
        self.inv, self.shake, self.mult = 1.0, 14, 1
        self.burst(self.pos, CYAN, 30, 400)
        rumble(self.joy, 1.0, 1.0, 300)
        self.play("hurt")
        if self.hp <= 0:
            self.dead = True
            self.play("over")
            if self.music:
                self.music.fadeout(800)
            rumble(self.joy, 1.0, 1.0, 800)

    def read_input(self):
        """Returns (move, aim_dir_or_None, fire, dash)."""
        keys = pygame.key.get_pressed()
        if self.joy:
            move = stick(self.joy, AX_LX, AX_LY)
            aim = stick(self.joy, AX_RX, AX_RY)
            fire = self.joy.get_axis(AX_R2) > 0.0 or aim.length() > 0.9  # R2 rests at -1; auto-fire when flicking the stick hard
            dash = self.joy.get_button(BTN_L1)
            restart = self.joy.get_button(BTN_OPTIONS)
            if aim.length() > 0:
                return move, aim.normalize(), fire, dash, restart
            return move, None, fire, dash, restart
        move = pygame.Vector2(keys[pygame.K_d] - keys[pygame.K_a], keys[pygame.K_s] - keys[pygame.K_w])
        if move.length() > 1:
            move.scale_to_length(1)
        d = pygame.Vector2(pygame.mouse.get_pos()) - self.pos
        aim = d.normalize() if d.length() > 1 else None
        return move, aim, pygame.mouse.get_pressed()[0], keys[pygame.K_SPACE], keys[pygame.K_r]

    def update(self, dt):
        move, aim, fire, dash, restart = self.read_input()
        if self.dead:
            if restart:
                self.begin()
            return
        if aim:
            self.aim = aim

        # movement with drift (inertia)
        self.fire_cd -= dt; self.triple_t -= dt; self.dash_cd -= dt; self.dash_t -= dt; self.inv -= dt; self.shake = max(0, self.shake - 40 * dt)
        if dash and self.dash_cd <= 0:
            d = move.normalize() if move.length() > 0 else self.aim
            self.vel = d * 900
            self.dash_t, self.dash_cd = 0.18, 1.2
            rumble(self.joy, 0.0, 0.6, 150)
            self.play("dash")
        self.vel += move * 2200 * dt
        self.vel *= 0.985 if self.dash_t > 0 else 0.90 ** (dt * 60)
        self.pos += self.vel * dt
        self.pos.x = max(16, min(W - 16, self.pos.x)); self.pos.y = max(16, min(H - 16, self.pos.y))
        if self.dash_t > 0:
            self.parts.append(Particle(self.pos, CYAN, 40, 0.3))

        # shooting
        if fire and self.fire_cd <= 0:
            self.fire_cd = 0.11
            for off in ((-0.2, 0, 0.2) if self.triple_t > 0 else (0,)):
                v = self.aim.rotate_rad(off + random.uniform(-0.04, 0.04)) * 900
                self.bullets.append([pygame.Vector2(self.pos), v + self.vel * 0.3, 1.2])
            rumble(self.joy, 0.0, 0.15, 40)
            self.play("shoot")

        # bomb: R1 / E (edge-triggered)
        held = self.joy.get_button(BTN_R1) if self.joy else pygame.key.get_pressed()[pygame.K_e]
        if held and not self.bomb_held and self.bombs > 0:
            self.bombs -= 1
            self.shake = 22
            for e in self.enemies:
                e.hp -= 10
            self.ebullets.clear()
            for _ in range(70):
                self.parts.append(Particle(self.pos, ORANGE, 900, 0.8))
            rumble(self.joy, 1.0, 1.0, 500)
            self.play("bomb")
        self.bomb_held = held

        # pickups
        for pk in self.pickups:
            pk[2] -= dt
            if pk[0].distance_to(self.pos) < 26:
                pk[2] = 0
                self.collect(pk[1])
        self.pickups = [pk for pk in self.pickups if pk[2] > 0]

        # waves
        if self.to_spawn:
            self.spawn_t -= dt
            if self.spawn_t <= 0:
                self.enemies.append(Enemy(self.to_spawn.pop(), self.wave))
                self.spawn_t = max(0.25, 0.9 - self.wave * 0.04)
        elif not self.enemies:
            self.start_wave()

        # bullets
        for b in self.bullets:
            b[0] += b[1] * dt; b[2] -= dt
        self.bullets = [b for b in self.bullets if b[2] > 0 and -20 < b[0].x < W + 20 and -20 < b[0].y < H + 20]
        for b in self.ebullets:
            b[0] += b[1] * dt; b[2] -= dt
            if b[0].distance_to(self.pos) < 14:
                b[2] = 0
                self.hurt()
        self.ebullets = [b for b in self.ebullets if b[2] > 0]

        # enemies
        for e in self.enemies:
            to_p = self.pos - e.pos
            dist = to_p.length() or 1
            if e.kind == "chaser":
                e.pos += to_p / dist * e.speed * dt
            else:  # shooters/bosses keep their distance and fire
                if dist > 320:
                    e.pos += to_p / dist * e.speed * dt
                e.cool -= dt
                if e.cool <= 0:
                    e.cool = 1.6 if e.kind == "shooter" else 0.8
                    shots = 1 if e.kind == "shooter" else 8
                    for i in range(shots):
                        d = (to_p / dist) if shots == 1 else pygame.Vector2(1, 0).rotate(i * 360 / shots + e.pos.x)
                        self.ebullets.append([pygame.Vector2(e.pos), d * 320, 4])
            if dist < e.r + 12:
                self.hurt()
            for b in self.bullets:
                if b[2] > 0 and b[0].distance_to(e.pos) < e.r + 4:
                    b[2] = 0
                    e.hp -= 1
                    self.burst(b[0], e.color, 4, 150)
        for e in [e for e in self.enemies if e.hp <= 0]:
            self.enemies.remove(e)
            self.burst(e.pos, e.color, 30 if e.kind == "boss" else 16)
            self.score += 10 * self.mult * (20 if e.kind == "boss" else 1)
            self.mult, self.mult_t = min(10, self.mult + 1), 2.0
            self.shake = 8 if e.kind == "boss" else 3
            rumble(self.joy, 0.4, 0.2, 80)
            self.play("boss" if e.kind == "boss" else "kill")
            if e.kind == "boss" or random.random() < 0.10:
                kind = random.choice(list(PICKUPS)) if e.kind != "boss" else random.choice(["bomb", "shield", "heal"])
                if kind == "heal" and self.hp >= 5:
                    kind = "triple"
                self.pickups.append([pygame.Vector2(e.pos), kind, 9.0])
        self.mult_t -= dt
        if self.mult_t <= 0:
            self.mult = 1

        for p in self.parts:
            p.update(dt)
        self.parts = [p for p in self.parts if p.life > 0]

    def draw(self):
        # fading trail gives a cheap glow/motion blur effect
        self.trail.fill((8, 6, 20, 70))
        self.screen.blit(self.trail, (0, 0))
        ox, oy = (random.uniform(-self.shake, self.shake) for _ in range(2))
        s = self.screen
        pygame.draw.rect(s, (40, 30, 90), (4 + ox, 4 + oy, W - 8, H - 8), 2)

        for p in self.parts:
            c = tuple(int(v * p.life / p.max) for v in p.color)
            pygame.draw.circle(s, c, (p.pos.x + ox, p.pos.y + oy), 3)
        for b in self.bullets:
            pygame.draw.line(s, GREEN, (b[0].x + ox, b[0].y + oy), b[0] - b[1].normalize() * 14 + (ox, oy), 4)
        for b in self.ebullets:
            pygame.draw.circle(s, YELLOW, (b[0].x + ox, b[0].y + oy), 6)
        for e in self.enemies:
            pygame.draw.circle(s, e.color, (e.pos.x + ox, e.pos.y + oy), e.r, 3)
            if e.kind != "chaser":
                pygame.draw.circle(s, e.color, (e.pos.x + ox, e.pos.y + oy), e.r * e.hp / e.max_hp)

        for pos, kind, left in self.pickups:
            letter, col = PICKUPS[kind]
            if left < 3 and int(left * 8) % 2:
                continue  # blink when about to vanish
            r = 15 + math.sin(self.tick * 6) * 2
            c = (pos.x + ox, pos.y + oy)
            pygame.draw.polygon(s, col, [(c[0], c[1] - r), (c[0] + r, c[1]), (c[0], c[1] + r), (c[0] - r, c[1])], 2)
            t = self.font.render(letter, True, col)
            s.blit(t, t.get_rect(center=c))
        if self.shield and not self.dead:
            pygame.draw.circle(s, BLUE, (self.pos.x + ox, self.pos.y + oy), 26, 2)

        if not self.dead and (self.inv <= 0 or int(self.inv * 20) % 2):
            tip = self.pos + self.aim * 18
            l, r = self.pos + self.aim.rotate(140) * 14, self.pos + self.aim.rotate(-140) * 14
            pygame.draw.polygon(s, CYAN, [tip + (ox, oy), l + (ox, oy), r + (ox, oy)], 3)
            pygame.draw.line(s, (90, 90, 140), self.pos + self.aim * 30, self.pos + self.aim * 60, 1)

        s.blit(self.font.render(f"SCORE {int(self.score):,}   x{self.mult}", True, WHITE), (20, 16))
        s.blit(self.font.render(f"WAVE {self.wave}", True, WHITE), (W // 2 - 40, 16))
        for i in range(self.hp):
            pygame.draw.circle(s, PINK, (W - 30 - i * 28, 28), 9)
        if self.dash_cd > 0:
            pygame.draw.rect(s, (60, 60, 90), (20, 52, 120, 6))
            pygame.draw.rect(s, CYAN, (20, 52, 120 * (1 - self.dash_cd / 1.2), 6))
        for i in range(self.bombs):
            pygame.draw.polygon(s, ORANGE, [(W - 30 - i * 28, 56), (W - 22 - i * 28, 64), (W - 30 - i * 28, 72), (W - 38 - i * 28, 64)], 2)
        if self.triple_t > 0:
            pygame.draw.rect(s, (30, 70, 40), (20, 64, 120, 6))
            pygame.draw.rect(s, GREEN, (20, 64, 120 * self.triple_t / 10, 6))
        if not self.joy:
            s.blit(self.font.render("No controller - using keyboard/mouse", True, (140, 140, 170)), (20, H - 36))
        if self.dead:
            t = self.big.render("GAME OVER", True, PINK)
            s.blit(t, t.get_rect(center=(W / 2, H / 2 - 30)))
            t = self.font.render("OPTIONS / R: restart     CIRCLE / T: title", True, WHITE)
            s.blit(t, t.get_rect(center=(W / 2, H / 2 + 30)))
        pygame.display.flip()

    def draw_title(self, dt):
        self.tick += dt
        s = self.screen
        self.trail.fill((8, 6, 20, 60))
        s.blit(self.trail, (0, 0))
        if random.random() < 0.6:
            self.parts.append(Particle((random.randint(0, W), H + 10), random.choice([CYAN, PINK, YELLOW]), 60, 3))
            self.parts[-1].vel = pygame.Vector2(random.uniform(-20, 20), -random.uniform(60, 200))
        for p in self.parts:
            p.update(dt)
            c = tuple(int(v * max(0, p.life) / p.max) for v in p.color)
            pygame.draw.circle(s, c, p.pos, 3)
        self.parts = [p for p in self.parts if p.life > 0]
        bob = math.sin(self.tick * 2) * 8
        for text, col, off in (("TWIN STICK", PINK, 4), ("TWIN STICK", CYAN, 0)):
            t = self.big.render(text, True, col)
            s.blit(t, t.get_rect(center=(W / 2 + off, H / 3 - 20 + bob + off)))
        t = self.big.render("DRIFT", True, WHITE)
        s.blit(t, t.get_rect(center=(W / 2, H / 3 + 50 + bob)))
        if int(self.tick * 2) % 2 == 0:
            msg = "press X to start" if self.joy else "press ENTER or click to start"
            t = self.font.render(msg, True, YELLOW)
            s.blit(t, t.get_rect(center=(W / 2, H * 0.62)))
        lines = ["L stick  move    R stick  aim", "R2  fire    L1  dash    R1  bomb", "Esc  quit"] if self.joy else                 ["WASD  move    mouse  aim + fire", "SPACE  dash    E  bomb    Esc  quit"]
        for i, l in enumerate(lines):
            t = self.font.render(l, True, (140, 140, 190))
            s.blit(t, t.get_rect(center=(W / 2, H * 0.75 + i * 30)))
        pygame.display.flip()

    def run(self, max_frames=None):
        frames = 0
        while True:
            dt = min(self.clock.tick(60) / 1000, 0.05)
            self.tick += dt if self.state == "play" else 0  # title advances its own clock
            for e in pygame.event.get():
                if e.type == pygame.QUIT or (e.type == pygame.KEYDOWN and e.key == pygame.K_ESCAPE):
                    return
                if self.state == "title" and (
                        (e.type == pygame.JOYBUTTONDOWN and e.button in (0, BTN_OPTIONS))
                        or (e.type == pygame.KEYDOWN and e.key in (pygame.K_RETURN, pygame.K_SPACE))
                        or e.type == pygame.MOUSEBUTTONDOWN):
                    self.begin()
                elif self.state == "play" and self.dead and (
                        (e.type == pygame.JOYBUTTONDOWN and e.button == 1)
                        or (e.type == pygame.KEYDOWN and e.key == pygame.K_t)):
                    self.to_title()
                if e.type == pygame.JOYDEVICEADDED:
                    self.connect()
                if e.type == pygame.JOYDEVICEREMOVED:
                    self.joy = None
            if self.state == "title":
                self.draw_title(dt)
            else:
                self.update(dt)
                self.draw()
            frames += 1
            if max_frames and frames >= max_frames:
                return


if __name__ == "__main__":
    Game().run(max_frames=int(sys.argv[1]) if len(sys.argv) > 1 else None)
