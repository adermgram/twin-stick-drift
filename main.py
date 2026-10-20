"""Twin Stick Drift - top-down arena shooter for a PS4 controller (keyboard + mouse fallback).

Pad: left stick move | right stick aim | R2 fire | L1 dash | Options/Enter restart
Keys: WASD move | mouse aim | LMB fire | SPACE dash | R restart
"""
import math
import random
import sys

import pygame

W, H = 1280, 720
DEADZONE = 0.2
# SDL2 mapping for the PS4 pad in pygame 2.x
AX_LX, AX_LY, AX_RX, AX_RY, AX_L2, AX_R2 = 0, 1, 2, 3, 4, 5
BTN_L1, BTN_OPTIONS = 9, 6

CYAN, PINK, YELLOW, GREEN, WHITE = (0, 255, 230), (255, 60, 140), (255, 220, 60), (80, 255, 120), (255, 255, 255)


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
        pygame.init()
        self.screen = pygame.display.set_mode((W, H))
        pygame.display.set_caption("Twin Stick Drift")
        self.clock = pygame.time.Clock()
        self.font = pygame.font.SysFont("consolas", 24)
        self.big = pygame.font.SysFont("consolas", 64, bold=True)
        self.trail = pygame.Surface((W, H), pygame.SRCALPHA)
        self.joy = None
        self.connect()
        self.reset()

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
        self.fire_cd = self.dash_cd = self.dash_t = self.inv = self.shake = 0.0
        self.to_spawn = []
        self.dead = False

    def start_wave(self):
        self.wave += 1
        n = 4 + self.wave * 2
        self.to_spawn = ["chaser"] * n + ["shooter"] * (self.wave // 2)
        if self.wave % 5 == 0:
            self.to_spawn.append("boss")
        random.shuffle(self.to_spawn)
        self.spawn_t = 0.0

    def burst(self, pos, color, n=14, speed=240):
        self.parts += [Particle(pos, color, speed) for _ in range(n)]

    def hurt(self):
        if self.inv > 0 or self.dash_t > 0:
            return
        self.hp -= 1
        self.inv, self.shake, self.mult = 1.0, 14, 1
        self.burst(self.pos, CYAN, 30, 400)
        rumble(self.joy, 1.0, 1.0, 300)
        if self.hp <= 0:
            self.dead = True
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
                self.reset()
            return
        if aim:
            self.aim = aim

        # movement with drift (inertia)
        self.fire_cd -= dt; self.dash_cd -= dt; self.dash_t -= dt; self.inv -= dt; self.shake = max(0, self.shake - 40 * dt)
        if dash and self.dash_cd <= 0:
            d = move.normalize() if move.length() > 0 else self.aim
            self.vel = d * 900
            self.dash_t, self.dash_cd = 0.18, 1.2
            rumble(self.joy, 0.0, 0.6, 150)
        self.vel += move * 2200 * dt
        self.vel *= 0.985 if self.dash_t > 0 else 0.90 ** (dt * 60)
        self.pos += self.vel * dt
        self.pos.x = max(16, min(W - 16, self.pos.x)); self.pos.y = max(16, min(H - 16, self.pos.y))
        if self.dash_t > 0:
            self.parts.append(Particle(self.pos, CYAN, 40, 0.3))

        # shooting
        if fire and self.fire_cd <= 0:
            self.fire_cd = 0.11
            spread = random.uniform(-0.04, 0.04)
            v = self.aim.rotate_rad(spread) * 900
            self.bullets.append([pygame.Vector2(self.pos), v + self.vel * 0.3, 1.2])
            rumble(self.joy, 0.0, 0.15, 40)

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
        if not self.joy:
            s.blit(self.font.render("No controller - using keyboard/mouse", True, (140, 140, 170)), (20, H - 36))
        if self.dead:
            t = self.big.render("GAME OVER", True, PINK)
            s.blit(t, t.get_rect(center=(W / 2, H / 2 - 30)))
            t = self.font.render("press OPTIONS (or R) to restart", True, WHITE)
            s.blit(t, t.get_rect(center=(W / 2, H / 2 + 30)))
        pygame.display.flip()

    def run(self, max_frames=None):
        frames = 0
        while True:
            dt = min(self.clock.tick(60) / 1000, 0.05)
            for e in pygame.event.get():
                if e.type == pygame.QUIT or (e.type == pygame.KEYDOWN and e.key == pygame.K_ESCAPE):
                    return
                if e.type == pygame.JOYDEVICEADDED:
                    self.connect()
                if e.type == pygame.JOYDEVICEREMOVED:
                    self.joy = None
            self.update(dt)
            self.draw()
            frames += 1
            if max_frames and frames >= max_frames:
                return


if __name__ == "__main__":
    Game().run(max_frames=int(sys.argv[1]) if len(sys.argv) > 1 else None)
