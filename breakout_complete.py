"""
breakout_complete.py
One-file complete Breakout game with:
- Cross-platform WAV playback (winsound / playsound / simpleaudio fallback)
- Pause menu: Resume (R), Quit (Q), Toggle Sound (S) with ESC
- Persistent highscores.json (top 10 per difficulty)
- Power-ups (multi, enlarge, slow), particles, enemies, background animation
- Menu with difficulty, shows highscores
Requirements:
- Python 3.8+
- Optional: playsound or simpleaudio for sound on non-Windows
Place WAV files in ./sounds/ as described in the README below.
"""

import tkinter as tk
import random, time, math, os, json, threading
from pathlib import Path

# ----------------------------
# AUDIO: cross-platform WAV playback
# ----------------------------
SOUNDS_DIR = Path(__file__).parent / "sounds"
SOUND_FILES = {
    "hit": SOUNDS_DIR / "hit.wav",
    "break": SOUNDS_DIR / "break.wav",
    "lose": SOUNDS_DIR / "lose.wav",
    "win": SOUNDS_DIR / "win.wav",
    "power": SOUNDS_DIR / "powerup.wav",
    "restart": SOUNDS_DIR / "restart.wav",
}

# Try winsound (Windows), else playsound, else simpleaudio; otherwise no-op
_sound_backend = None
try:
    import winsound
    _sound_backend = "winsound"
except Exception:
    try:
        from playsound import playsound as _playsound_fn  # may be blocking
        _sound_backend = "playsound"
    except Exception:
        try:
            import simpleaudio as sa
            _sound_backend = "simpleaudio"
        except Exception:
            _sound_backend = None

def play_wav_async(path):
    """Play a WAV file asynchronously. Safe no-op if unavailable."""
    if not GameSettings.sound_on:
        return
    if not Path(path).exists():
        return
    def _play():
        try:
            if _sound_backend == "winsound":
                winsound.PlaySound(str(path), winsound.SND_FILENAME | winsound.SND_ASYNC)
            elif _sound_backend == "playsound":
                # playsound is blocking, run in this thread
                _playsound_fn(str(path))
            elif _sound_backend == "simpleaudio":
                wave_obj = sa.WaveObject.from_wave_file(str(path))
                play_obj = wave_obj.play()
                # let it play asynchronously
            else:
                pass
        except Exception:
            pass
    # always spawn a thread so UI won't block (playsound may block)
    threading.Thread(target=_play, daemon=True).start()

# ----------------------------
# SETTINGS & CONFIG
# ----------------------------
class GameSettings:
    W, H = 900, 600
    MARGIN = 14
    R = 9
    BASE_PW = 110
    PH = 14
    START_LIVES = 3
    POWERUP_CHANCE = 0.18
    STAR_COUNT = 40
    PARTICLE_COUNT = 20
    PARTICLE_LIFE = 28
    sound_on = True

HIGHSCORE_FILE = Path(__file__).parent / "highscores.json"

DIFFICULTY_PRESETS = {
    "Easy":    {"rows": 4, "cols": 7, "ball_speed": 3.0, "enemy_freq": 0.015},
    "Normal":  {"rows": 5, "cols": 8, "ball_speed": 3.8, "enemy_freq": 0.035},
    "Hard":    {"rows": 6, "cols": 9, "ball_speed": 5.0, "enemy_freq": 0.06},
}

BLOCK_COLORS = ["#ff6b6b","#ffb86b","#fff56b","#7cff7c","#7cc8ff","#b78cff"]
POWERUP_TYPES = ["multi", "enlarge", "slow"]

# ----------------------------
# UTIL: highscores
# ----------------------------
def load_highscores():
    if not HIGHSCORE_FILE.exists():
        return {}
    try:
        with open(HIGHSCORE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}

def save_highscores(data):
    try:
        with open(HIGHSCORE_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except Exception:
        pass

def add_highscore(difficulty, score, name="PLAYER"):
    data = load_highscores()
    data.setdefault(difficulty, [])
    lst = data[difficulty]
    lst.append({"name": name, "score": score, "time": int(time.time())})
    lst.sort(key=lambda s: s["score"], reverse=True)
    data[difficulty] = lst[:10]
    save_highscores(data)

# ----------------------------
# GAME OBJECTS (Ball, Paddle, Block, PowerUp, Particle)
# ----------------------------
class Ball:
    def __init__(self, game, x, y, vx, vy, color="white"):
        self.game = game
        self.x = x; self.y = y
        self.vx = vx; self.vy = vy
        self.r = GameSettings.R
        self.color = color
        self.id = game.canvas.create_oval(self.x-self.r, self.y-self.r, self.x+self.r, self.y+self.r,
                                          fill=self.color, outline="#aaa")

    def update(self):
        g = self.game
        if g.paused or g.game_over: return
        self.x += self.vx
        self.y += self.vy

        # Walls
        if self.x - self.r <= GameSettings.MARGIN and self.vx < 0:
            self.x = GameSettings.MARGIN + self.r
            self.vx = -self.vx
            play_wav_async(SOUND_FILES["hit"])
        if self.x + self.r >= GameSettings.W - GameSettings.MARGIN and self.vx > 0:
            self.x = GameSettings.W - GameSettings.MARGIN - self.r
            self.vx = -self.vx
            play_wav_async(SOUND_FILES["hit"])
        if self.y - self.r <= GameSettings.MARGIN and self.vy < 0:
            self.y = GameSettings.MARGIN + self.r
            self.vy = -self.vy
            play_wav_async(SOUND_FILES["hit"])

        # Paddle collision
        p = g.paddle
        if p and (p.y - self.r <= self.y <= p.y + GameSettings.PH) and (p.x <= self.x <= p.x + p.w) and self.vy > 0:
            self.vy = -abs(self.vy)
            center = p.x + p.w / 2
            offset = (self.x - center) / (p.w / 2)
            self.vx += offset * 1.8
            # clamp speed
            maxv = g.max_ball_speed
            speed = math.hypot(self.vx, self.vy)
            if speed > maxv:
                scale = maxv / speed
                self.vx *= scale; self.vy *= scale
            self.y = p.y - self.r
            play_wav_async(SOUND_FILES["hit"])

        # Bottom -> remove ball; losing handled by game
        if self.y - self.r > GameSettings.H - GameSettings.MARGIN:
            g.remove_ball(self)
            return

        # Blocks / enemies collision
        hit = None
        for block in g.blocks + g.enemies:
            if not block.alive: continue
            collided, nx, ny = block.check_circle_collision(self.x, self.y, self.r)
            if collided:
                hit = (block, nx, ny)
                break
        if hit:
            block, nx, ny = hit
            if abs(nx) > abs(ny):
                self.vx = -self.vx
            else:
                self.vy = -self.vy
            # small correction
            self.x += self.vx * 0.45
            self.y += self.vy * 0.45
            block.on_hit(self)
            play_wav_async(SOUND_FILES["break"])

        # update drawing
        try:
            g.canvas.coords(self.id, self.x-self.r, self.y-self.r, self.x+self.r, self.y+self.r)
        except:
            pass

    def speed_scale(self, factor):
        self.vx *= factor
        self.vy *= factor

class Paddle:
    def __init__(self, game):
        self.game = game
        self.w = GameSettings.BASE_PW
        self.x = (GameSettings.W - self.w) // 2
        self.y = GameSettings.H - 60
        self.id = game.canvas.create_rectangle(self.x, self.y, self.x + self.w, self.y + GameSettings.PH,
                                               fill="#ddd", outline="#888", width=2)
        self.enlarge_until = 0

    def update(self):
        if time.time() > self.enlarge_until:
            if self.w != GameSettings.BASE_PW:
                center = self.x + self.w/2
                self.w = GameSettings.BASE_PW
                self.x = max(GameSettings.MARGIN, min(GameSettings.W-GameSettings.MARGIN-self.w, center - self.w/2))
                self.game.canvas.coords(self.id, self.x, self.y, self.x+self.w, self.y+GameSettings.PH)

    def set_x(self, newx):
        self.x = max(GameSettings.MARGIN, min(GameSettings.W - GameSettings.MARGIN - self.w, newx))
        self.game.canvas.coords(self.id, self.x, self.y, self.x+self.w, self.y+GameSettings.PH)

    def enlarge(self, duration=6.0):
        center = self.x + self.w/2
        self.w = int(GameSettings.BASE_PW * 1.6)
        self.x = max(GameSettings.MARGIN, min(GameSettings.W - GameSettings.MARGIN - self.w, center - self.w/2))
        self.enlarge_until = time.time() + duration
        self.game.canvas.coords(self.id, self.x, self.y, self.x+self.w, self.y+GameSettings.PH)

class Block:
    def __init__(self, game, x, y, w, h, color, hp=1, is_enemy=False, vx=0):
        self.game = game
        self.x = x; self.y = y; self.w = w; self.h = h
        self.color = color
        self.alive = True
        self.is_enemy = is_enemy
        self.vx = vx
        self.hp = hp
        outline = "#222" if not is_enemy else "#fff"
        width = 1 if not is_enemy else 2
        self.id = game.canvas.create_rectangle(self.x, self.y, self.x+self.w, self.y+self.h,
                                               fill=self.color, outline=outline, width=width)

    def check_circle_collision(self, cx, cy, r):
        qx = max(self.x, min(cx, self.x + self.w))
        qy = max(self.y, min(cy, self.y + self.h))
        dx = cx - qx
        dy = cy - qy
        return (dx*dx + dy*dy <= r*r), dx, dy

    def on_hit(self, ball):
        if not self.alive: return
        if self.is_enemy:
            self.hp -= 1
            self.vx = -self.vx
            if self.hp <= 0:
                self.break_block()
        else:
            self.break_block()

    def break_block(self):
        if not self.alive: return
        self.alive = False
        self.game.spawn_particles(self.x + self.w/2, self.y + self.h/2, self.color)
        if (not self.is_enemy) and random.random() < GameSettings.POWERUP_CHANCE:
            t = random.choice(POWERUP_TYPES)
            self.game.spawn_powerup(self.x + self.w/2, self.y + self.h/2, t)
        try:
            self.game.canvas.delete(self.id)
        except:
            pass
        if self in self.game.blocks:
            self.game.blocks.remove(self)
            self.game.score += 10
        if self in self.game.enemies:
            self.game.enemies.remove(self)
        self.game.update_hud()

    def update(self):
        if self.is_enemy and self.alive:
            self.x += self.vx
            left = GameSettings.MARGIN + 10
            right = GameSettings.W - GameSettings.MARGIN - self.w - 10
            if self.x <= left:
                self.x = left; self.vx = -self.vx
            if self.x >= right:
                self.x = right; self.vx = -self.vx
            self.game.canvas.coords(self.id, self.x, self.y, self.x+self.w, self.y+self.h)

class PowerUp:
    def __init__(self, game, x, y, kind):
        self.game = game
        self.x = x; self.y = y
        self.kind = kind
        self.vy = 2.2
        self.size = 12
        colors = {"multi":"#ffd700","enlarge":"#7cff7c","slow":"#7cc8ff"}
        self.color = colors.get(kind, "white")
        self.id = game.canvas.create_oval(self.x-self.size/2, self.y-self.size/2, self.x+self.size/2, self.y+self.size/2,
                                          fill=self.color, outline="#222")
        self.alive = True

    def update(self):
        if not self.alive or self.game.paused or self.game.game_over: return
        self.y += self.vy
        self.game.canvas.coords(self.id, self.x-self.size/2, self.y-self.size/2, self.x+self.size/2, self.y+self.size/2)
        p = self.game.paddle
        if p.x <= self.x <= p.x + p.w and p.y <= self.y + self.size/2 <= p.y + GameSettings.PH + 6:
            self.collect()
        if self.y - self.size/2 > GameSettings.H - GameSettings.MARGIN:
            self.destroy()

    def collect(self):
        if not self.alive: return
        self.alive = False
        play_wav_async(SOUND_FILES["power"])
        if self.kind == "multi":
            self.game.spawn_extra_balls(2)
        elif self.kind == "enlarge":
            self.game.paddle.enlarge(duration=8.0)
        elif self.kind == "slow":
            self.game.apply_slow(duration=6.0, factor=0.7)
        self.destroy()

    def destroy(self):
        try:
            self.game.canvas.delete(self.id)
        except:
            pass
        if self in self.game.powerups:
            self.game.powerups.remove(self)

class Particle:
    def __init__(self, game, x, y, color):
        self.game = game
        self.x = x; self.y = y
        self.vx = random.uniform(-3.0,3.0)
        self.vy = random.uniform(-4.0, -1.2)
        self.life = random.randint(GameSettings.PARTICLE_LIFE//2, GameSettings.PARTICLE_LIFE)
        self.color = color
        self.size = random.randint(2,5)
        self.id = game.canvas.create_oval(self.x, self.y, self.x+self.size, self.y+self.size, fill=self.color, outline="")

    def update(self):
        if self.life <= 0:
            try:
                self.game.canvas.delete(self.id)
            except:
                pass
            return False
        self.x += self.vx
        self.y += self.vy
        self.vy += 0.12
        self.life -= 1
        alpha = max(0, self.life / GameSettings.PARTICLE_LIFE)
        s = max(0.5, self.size * alpha)
        try:
            self.game.canvas.coords(self.id, self.x, self.y, self.x+s, self.y+s)
        except:
            pass
        return True

# ----------------------------
# MAIN GAME CLASS
# ----------------------------
class BreakoutGame:
    def __init__(self, root):
        self.root = root
        self.canvas = tk.Canvas(root, width=GameSettings.W, height=GameSettings.H, bg="#07070a")
        self.canvas.pack()
        self.state = "menu"  # menu, playing, gameover
        self.lives = GameSettings.START_LIVES
        self.score = 0
        self.paddle = None
        self.balls = []
        self.blocks = []
        self.enemies = []
        self.powerups = []
        self.particles = []
        self.paused = False
        self.game_over = False
        self.max_ball_speed = 10.0
        self.difficulty = "Normal"
        self.preset = DIFFICULTY_PRESETS[self.difficulty]
        self.hud_ids = {}
        # binds
        root.bind("<Left>", self.on_left)
        root.bind("<Right>", self.on_right)
        root.bind("<space>", self.on_space)
        root.bind("<Escape>", self.open_pause_menu)
        root.bind("p", self.toggle_pause)
        root.bind("P", self.toggle_pause)
        root.bind("r", self.restart)
        root.bind("R", self.restart)
        root.bind("<Motion>", self.on_mouse_move)
        self.setup_menu()

    # ----- MENU -----
    def setup_menu(self):
        self.canvas.delete("all")
        self.state = "menu"
        self.canvas.create_text(GameSettings.W//2, 70, text="BREAKOUT - COMPLETE", fill="white", font=("Arial", 36, "bold"))
        self.canvas.create_text(GameSettings.W//2, 120, text="Power-ups · Particles · Enemies · Sounds · Highscores", fill="#ccc", font=("Arial", 13))
        # Difficulty buttons
        ypos = 190; x = GameSettings.W//2 - 300
        for i, diff in enumerate(["Easy","Normal","Hard"]):
            rx = x + i*210
            rect = self.canvas.create_rectangle(rx, ypos, rx+180, ypos+60, fill="#222", outline="#555", width=2)
            text = self.canvas.create_text(rx+90, ypos+30, text=diff, fill="white", font=("Arial", 16))
            self.canvas.tag_bind(rect, "<Button-1>", lambda e, d=diff: self.select_difficulty(d))
            self.canvas.tag_bind(text, "<Button-1>", lambda e, d=diff: self.select_difficulty(d))
            if diff == self.difficulty:
                self.canvas.create_rectangle(rx-6, ypos-6, rx+186, ypos+66, outline="#6cf", width=3)
        # start button
        srx, sry = GameSettings.W//2 - 130, 300
        start_rect = self.canvas.create_rectangle(srx, sry, srx+260, sry+70, fill="#38a", outline="#6cf", width=2)
        start_text = self.canvas.create_text(GameSettings.W//2, sry+35, text="START GAME", fill="white", font=("Arial", 20, "bold"))
        self.canvas.tag_bind(start_rect, "<Button-1>", lambda e: self.start_game())
        self.canvas.tag_bind(start_text, "<Button-1>", lambda e: self.start_game())

        # highscores display
        hs_title = self.canvas.create_text(GameSettings.W//2, 400, text="High Scores", fill="#ddd", font=("Arial", 16, "bold"))
        hs = load_highscores().get(self.difficulty, [])
        y = 430
        if not hs:
            self.canvas.create_text(GameSettings.W//2, y, text="No highscores yet — break some blocks!", fill="#aaa", font=("Arial", 12))
        else:
            for i, entry in enumerate(hs[:10]):
                name = entry.get("name","?")
                scr = entry.get("score",0)
                txt = f"{i+1}. {name} — {scr}"
                self.canvas.create_text(GameSettings.W//2, y + i*20, text=txt, fill="#ccc", font=("Arial", 12))

        # animated stars background
        self.stars = []
        for _ in range(GameSettings.STAR_COUNT):
            sx = random.uniform(0, GameSettings.W)
            sy = random.uniform(0, GameSettings.H)
            sp = random.uniform(0.2,1.6)
            sid = self.canvas.create_oval(sx, sy, sx+2, sy+2, fill="#fff", outline="")
            self.stars.append([sid, sx, sy, sp])
        self.root.after(60, self.menu_stars)

    def select_difficulty(self, d):
        self.difficulty = d
        self.preset = DIFFICULTY_PRESETS[d]
        self.setup_menu()

    def menu_stars(self):
        if self.state != "menu": return
        for st in self.stars:
            sid, sx, sy, sp = st
            sx -= sp
            if sx < -6:
                sx = GameSettings.W + 6
                sy = random.uniform(0, GameSettings.H)
                sp = random.uniform(0.2,1.6)
            st[1] = sx; st[2] = sy; st[3] = sp
            try: self.canvas.coords(sid, sx, sy, sx+2, sy+2)
            except: pass
        self.root.after(60, self.menu_stars)

    # ----- START / SETUP GAME -----
    def start_game(self):
        self.state = "playing"
        self.canvas.delete("all")
        self.canvas.create_rectangle(GameSettings.MARGIN, GameSettings.MARGIN, GameSettings.W - GameSettings.MARGIN, GameSettings.H - GameSettings.MARGIN, outline="#444")
        self.lives = GameSettings.START_LIVES
        self.score = 0
        self.paddle = Paddle(self)
        self.balls = []
        self.blocks = []
        self.enemies = []
        self.powerups = []
        self.particles = []
        self.paused = False
        self.game_over = False
        self.max_ball_speed = 10.0
        self.preset = DIFFICULTY_PRESETS[self.difficulty]
        self.create_hud()
        self.create_blocks_and_enemies()
        speed = self.preset["ball_speed"]
        b = Ball(self, GameSettings.W//2, self.paddle.y - 28, speed * 0.6, -abs(speed))
        self.balls.append(b)
        self.star_ids = []
        for _ in range(GameSettings.STAR_COUNT):
            sx = random.uniform(GameSettings.MARGIN+10, GameSettings.W - GameSettings.MARGIN-10)
            sy = random.uniform(GameSettings.MARGIN+10, GameSettings.H - GameSettings.MARGIN-40)
            sid = self.canvas.create_oval(sx, sy, sx+2, sy+2, fill="#fff", outline="")
            self.star_ids.append([sid, sx, sy, random.uniform(0.2,1.6)])
        play_wav_async(SOUND_FILES["restart"])
        self.root.after(16, self.loop)

    def create_hud(self):
        self.hud_ids['score'] = self.canvas.create_text(GameSettings.W-120, GameSettings.H-24, text=f"Score: {self.score}", fill="white", font=("Arial", 14))
        self.hud_ids['lives'] = self.canvas.create_text(100, GameSettings.H-24, text=f"Lives: {self.lives}", fill="white", font=("Arial", 14))
        self.hud_ids['info'] = self.canvas.create_text(GameSettings.W//2, GameSettings.H-24, text=f"Difficulty: {self.difficulty}  |  ESC: Pause", fill="#bbb", font=("Arial", 12))

    def create_blocks_and_enemies(self):
        rows = self.preset['rows']; cols = self.preset['cols']
        bw = (GameSettings.W - 2*GameSettings.MARGIN - (cols-1)*6) / cols
        bh = 26
        x0 = GameSettings.MARGIN + 6; y0 = GameSettings.MARGIN + 30
        for r in range(rows):
            for c in range(cols):
                x = x0 + c * (bw + 6)
                y = y0 + r * (bh + 6)
                color = BLOCK_COLORS[r % len(BLOCK_COLORS)]
                block = Block(self, x, y, bw, bh, color)
                self.blocks.append(block)
        enemy_count = 1 if self.difficulty == "Easy" else (2 if self.difficulty == "Normal" else 3)
        for i in range(enemy_count):
            ex = random.uniform(GameSettings.MARGIN+20, GameSettings.W - GameSettings.MARGIN - 120)
            ey = y0 + rows*(bh+6) + 16 + i*30
            evx = random.choice([-1.8, 1.8])
            b = Block(self, ex, ey, 96, 18, "#8b5cf6", is_enemy=True, vx=evx)
            b.hp = 2
            self.enemies.append(b)

    # ----- MAIN LOOP -----
    def loop(self):
        if self.state != "playing": return
        if self.paused:
            self.root.after(80, self.loop)
            return
        if self.game_over:
            return
        # stars move
        for sid, sx, sy, sp in self.star_ids:
            sx += sp*0.2
            if sx > GameSettings.W - GameSettings.MARGIN: sx = GameSettings.MARGIN + 4; sy = random.uniform(GameSettings.MARGIN+20, GameSettings.H - GameSettings.MARGIN - 40)
            try: self.canvas.coords(sid, sx, sy, sx+2, sy+2)
            except: pass
        if self.paddle:
            self.paddle.update()
        for e in list(self.enemies):
            e.update()
        for b in list(self.balls):
            b.update()
        for pu in list(self.powerups):
            pu.update()
        for p in list(self.particles):
            alive = p.update()
            if not alive and p in self.particles:
                self.particles.remove(p)
        # occasional extra enemy spawn
        if random.random() < self.preset.get("enemy_freq", 0.03):
            if len(self.enemies) < 6:
                ex = random.uniform(GameSettings.MARGIN+20, GameSettings.W - GameSettings.MARGIN - 120)
                ey = random.uniform(GameSettings.MARGIN+60, GameSettings.H/2)
                evx = random.choice([-2.2, 2.2])
                b = Block(self, ex, ey, 86, 18, "#ff7ad6", is_enemy=True, vx=evx)
                b.hp = 2
                self.enemies.append(b)
        # ambient particle spawn
        if random.random() < 0.02:
            sx = random.uniform(GameSettings.MARGIN+10, GameSettings.W - GameSettings.MARGIN-10)
            sy = random.uniform(GameSettings.MARGIN+10, GameSettings.H - GameSettings.MARGIN-60)
            self.particles.append(Particle(self, sx, sy, "#ffffff"))
        # win check
        if not self.blocks:
            self.canvas.create_text(GameSettings.W//2, GameSettings.H//2, text="YOU WIN!", fill="#ffd86b", font=("Arial", 44, "bold"))
            play_wav_async(SOUND_FILES["win"])
            self.game_over = True
            add_highscore(self.difficulty, self.score)
            return
        self.update_hud()
        self.root.after(16, self.loop)

    def update_hud(self):
        try:
            self.canvas.itemconfig(self.hud_ids['score'], text=f"Score: {self.score}")
            self.canvas.itemconfig(self.hud_ids['lives'], text=f"Lives: {self.lives}")
        except:
            pass

    def remove_ball(self, ball):
        try: self.canvas.delete(ball.id)
        except: pass
        if ball in self.balls: self.balls.remove(ball)
        if not self.balls:
            self.lives -= 1
            play_wav_async(SOUND_FILES["lose"])
            self.update_hud()
            if self.lives <= 0:
                self.canvas.create_text(GameSettings.W//2, GameSettings.H//2, text="GAME OVER", fill="red", font=("Arial", 40, "bold"))
                self.game_over = True
                add_highscore(self.difficulty, self.score)
                return
            # respawn single ball on paddle
            nb = Ball(self, self.paddle.x + self.paddle.w//2, self.paddle.y - 28, -self.preset['ball_speed']*0.6, -abs(self.preset['ball_speed']))
            self.balls.append(nb)

    def spawn_particles(self, x, y, color):
        for _ in range(GameSettings.PARTICLE_COUNT):
            p = Particle(self, x + random.uniform(-10,10), y + random.uniform(-6,6), color)
            self.particles.append(p)

    def spawn_powerup(self, x, y, kind):
        pu = PowerUp(self, x, y, kind)
        self.powerups.append(pu)

    def spawn_extra_balls(self, n=1):
        templates = list(self.balls) if self.balls else []
        if not templates:
            templates = [Ball(self, GameSettings.W//2, self.paddle.y - 24, self.preset['ball_speed']*0.6, -abs(self.preset['ball_speed']))]
            self.balls.extend(templates)
        for i in range(n):
            src = random.choice(templates)
            angle = random.uniform(-1.0, 1.0)
            speed = math.hypot(src.vx, src.vy)
            nvx = speed * math.cos(angle) * (1 + random.uniform(-0.3,0.3))
            nvy = -abs(speed * math.sin(angle) + random.uniform(-1.2,1.2))
            b = Ball(self, src.x + random.uniform(-6,6), src.y + random.uniform(-6,6), nvx, nvy, color=random.choice(["#fff","#ffd","#aef","#f8a"]))
            self.balls.append(b)

    def apply_slow(self, duration=6.0, factor=0.7):
        for b in list(self.balls):
            b.speed_scale(factor)
        def restore():
            if self.game_over: return
            for b in list(self.balls):
                b.speed_scale(1.0/factor)
        self.root.after(int(duration*1000), restore)

    # ----- input & menus -----
    def on_left(self, event):
        if self.state != "playing" or not self.paddle: return
        self.paddle.set_x(self.paddle.x - 24)

    def on_right(self, event):
        if self.state != "playing" or not self.paddle: return
        self.paddle.set_x(self.paddle.x + 24)

    def on_mouse_move(self, event):
        if self.state == "playing" and self.paddle:
            self.paddle.set_x(event.x - self.paddle.w/2)

    def on_space(self, event):
        if self.state != "playing": return
        for b in self.balls:
            if abs(b.vx) < 0.01 and abs(b.vy) < 0.01:
                b.vx = random.choice([2.8, -2.8]); b.vy = -abs(self.preset['ball_speed'])

    def toggle_pause(self, event=None):
        if self.state != "playing": return
        self.paused = not self.paused
        if self.paused:
            self.canvas.create_text(GameSettings.W//2, GameSettings.H//2, text="PAUSED", fill="#fff", font=("Arial", 36), tag="paused")
        else:
            self.canvas.delete("paused")

    def open_pause_menu(self, event=None):
        if self.state != "playing": return
        self.paused = True
        # overlay
        overlay = self.canvas.create_rectangle(GameSettings.W//2-180, GameSettings.H//2-120, GameSettings.W//2+180, GameSettings.H//2+120, fill="#000", stipple="gray50", outline="#666")
        title = self.canvas.create_text(GameSettings.W//2, GameSettings.H//2-70, text="GAME PAUSED", fill="#fff", font=("Arial", 20, "bold"))
        t_resume = self.canvas.create_text(GameSettings.W//2, GameSettings.H//2-20, text="R - Resume", fill="#ddd", font=("Arial", 14))
        t_sound = self.canvas.create_text(GameSettings.W//2, GameSettings.H//2+10, text=f"S - Sound: {'ON' if GameSettings.sound_on else 'OFF'}", fill="#ddd", font=("Arial", 14))
        t_quit = self.canvas.create_text(GameSettings.W//2, GameSettings.H//2+40, text="Q - Quit to Menu", fill="#ddd", font=("Arial", 14))
        def on_key(e):
            if e.keysym.lower() == "r":
                self.canvas.delete(overlay, title, t_resume, t_sound, t_quit)
                self.paused = False
            elif e.keysym.lower() == "s":
                GameSettings.sound_on = not GameSettings.sound_on
                self.canvas.itemconfig(t_sound, text=f"S - Sound: {'ON' if GameSettings.sound_on else 'OFF'}")
            elif e.keysym.lower() == "q":
                self.canvas.delete("all")
                self.state = "menu"
                self.setup_menu()
            # swallow other keys
        self.root.bind("<Key>", on_key)

    def restart(self, event=None):
        if self.state == "menu":
            self.start_game()
            return
        # restart same difficulty
        self.start_game()

# ----------------------------
# RUN
# ----------------------------
def main():
    root = tk.Tk()
    root.title("Breakout - Complete (One file)")
    game = BreakoutGame(root)
    root.mainloop()

if __name__ == "__main__":
    main()

"""
README (quick):
- Put WAV files into a folder named 'sounds' next to this script, matching SOUND_FILES names.
- If you don't have sounds, the game still runs (sound is no-op).
- High scores saved into 'highscores.json' in same folder.
"""
