import json
import math
import random
import secrets
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

import pygame

try:
    import qrcode
except ImportError:
    qrcode = None

# --------------------------
# Configuration
# --------------------------
WIDTH, HEIGHT = 1360, 750
FPS = 60
SPEED = 2.5
MAX_FORCE = 0.2
DETECTION_RADIUS = 180
AGENT_RADIUS = 15
NPC_PER_TYPE = 26

SERVER_HOST = "0.0.0.0"
SERVER_PORT = 8765
MAX_PLAYERS = 3
COUNTDOWN_SECONDS = 3
TEST_SECONDS = 10
START_FULLSCREEN = False

QR_MISSING_MSG = "QR package missing: run `pip3 install qrcode` and restart game."

RULES = {
    "rock": "scissors",
    "scissors": "paper",
    "paper": "rock",
}
PREDATOR_RULES = {v: k for k, v in RULES.items()}

TYPE_COLORS = {
    "rock": (135, 146, 166),
    "paper": (245, 245, 245),
    "scissors": (248, 116, 96),
}
PLAYER_LABELS = {1: "P1", 2: "P2", 3: "P3"}
PLAYER_HIGHLIGHTS = {
    1: (255, 70, 70),
    2: (0, 114, 178),
    3: (230, 159, 0),
}
PLAYER_ASSIGNMENTS = {
    1: {"type": "scissors", "spawn": (WIDTH - 120, HEIGHT // 2)},
    2: {"type": "rock", "spawn": (120, HEIGHT // 2)},
    3: {"type": "paper", "spawn": (WIDTH // 2, 90)},
}
SPRITE_FORWARD_DEG = {
    "rock": 0.0,
    "paper": 90.0,
    "scissors": 90.0,
}

BG_TOP = (238, 242, 250)
BG_BOTTOM = (214, 220, 232)
GRID_COLOR = (198, 206, 220)


def clamp(value, low, high):
    return max(low, min(high, value))


def get_local_ip():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        sock.close()


def load_controller_html():
    html_file = Path(__file__).with_name("controller.html")
    if html_file.exists():
        return html_file.read_text(encoding="utf-8")
    return "<h1>Missing controller.html</h1>"


def create_screen(fullscreen):
    flags = pygame.SCALED
    if fullscreen:
        flags |= pygame.FULLSCREEN
    return pygame.display.set_mode((WIDTH, HEIGHT), flags)


class MobileHub:
    def __init__(self, max_players=MAX_PLAYERS):
        self.max_players = max_players
        self.lock = threading.Lock()
        self.player_to_token = {}
        self.token_to_player = {}
        self.inputs = {pid: (0.0, 0.0) for pid in range(1, max_players + 1)}
        self.last_seen = {}
        self.last_rtt_ms = {pid: None for pid in range(1, max_players + 1)}

    def _cleanup_stale(self, timeout_sec=20.0):
        now = time.monotonic()
        stale_players = []
        for player_id, token in self.player_to_token.items():
            ts = self.last_seen.get(token, now)
            if now - ts > timeout_sec:
                stale_players.append((player_id, token))

        for player_id, token in stale_players:
            self.player_to_token.pop(player_id, None)
            self.token_to_player.pop(token, None)
            self.last_seen.pop(token, None)
            self.inputs[player_id] = (0.0, 0.0)
            self.last_rtt_ms[player_id] = None

    def join(self, existing_token=None):
        with self.lock:
            self._cleanup_stale()

            if existing_token and existing_token in self.token_to_player:
                player_id = self.token_to_player[existing_token]
                self.last_seen[existing_token] = time.monotonic()
                return True, player_id, existing_token, "reconnected"

            for player_id in range(1, self.max_players + 1):
                if player_id in self.player_to_token:
                    continue
                token = secrets.token_urlsafe(12)
                self.player_to_token[player_id] = token
                self.token_to_player[token] = player_id
                self.last_seen[token] = time.monotonic()
                self.inputs[player_id] = (0.0, 0.0)
                return True, player_id, token, "joined"

            return False, None, None, "room_full"

    def set_input(self, token, x, y, rtt_ms=None):
        with self.lock:
            player_id = self.token_to_player.get(token)
            if not player_id:
                return False
            try:
                x_val = float(x)
                y_val = float(y)
            except (TypeError, ValueError):
                return False
            self.inputs[player_id] = (
                clamp(x_val, -1.0, 1.0),
                clamp(y_val, -1.0, 1.0),
            )
            if rtt_ms is not None:
                try:
                    measured = float(rtt_ms)
                except (TypeError, ValueError):
                    measured = None
                if measured is not None and 0 <= measured <= 5000:
                    self.last_rtt_ms[player_id] = measured
            self.last_seen[token] = time.monotonic()
            return True

    def snapshot(self):
        with self.lock:
            self._cleanup_stale()
            now = time.monotonic()
            connected = sorted(self.player_to_token.keys())
            latency = {}
            for player_id in connected:
                token = self.player_to_token.get(player_id)
                if not token:
                    continue
                age_ms = max(0.0, (now - self.last_seen.get(token, now)) * 1000.0)
                base_ms = self.last_rtt_ms.get(player_id) or 0.0
                latency[player_id] = age_ms + base_ms
            return dict(self.inputs), connected, latency


class ControllerHandler(BaseHTTPRequestHandler):
    hub = None
    html = ""

    def _send_json(self, status, payload):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_html(self, html):
        body = html.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        path = urlparse(self.path).path
        if path in {"/", "/join"}:
            self._send_html(self.html)
            return
        if path == "/health":
            self._send_json(200, {"ok": True})
            return
        self._send_json(404, {"ok": False, "error": "not_found"})

    def do_POST(self):
        path = urlparse(self.path).path
        size = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(size) if size > 0 else b"{}"

        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            self._send_json(400, {"ok": False, "error": "bad_json"})
            return

        if path == "/api/join":
            ok, player_id, token, reason = self.hub.join(payload.get("token"))
            self._send_json(
                200,
                {"ok": ok, "player_id": player_id, "token": token, "reason": reason},
            )
            return

        if path == "/api/input":
            ok = self.hub.set_input(
                payload.get("token", ""),
                payload.get("x", 0),
                payload.get("y", 0),
                payload.get("rtt_ms"),
            )
            if ok:
                self._send_json(200, {"ok": True})
            else:
                self._send_json(401, {"ok": False, "error": "invalid_token"})
            return

        self._send_json(404, {"ok": False, "error": "not_found"})

    def log_message(self, _fmt, *_args):
        return


def start_server(hub, html, host=SERVER_HOST, port=SERVER_PORT):
    handler = type("BoundControllerHandler", (ControllerHandler,), {})
    handler.hub = hub
    handler.html = html
    httpd = ThreadingHTTPServer((host, port), handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return httpd


def build_qr_surface(link, box_size=6, border=2):
    if qrcode is None:
        return None

    qr_obj = qrcode.QRCode(border=border, box_size=1)
    qr_obj.add_data(link)
    qr_obj.make(fit=True)
    matrix = qr_obj.get_matrix()

    rows, cols = len(matrix), len(matrix[0])
    surface = pygame.Surface((cols * box_size, rows * box_size))
    surface.fill((255, 255, 255))

    for y in range(rows):
        for x in range(cols):
            if matrix[y][x]:
                pygame.draw.rect(
                    surface,
                    (0, 0, 0),
                    pygame.Rect(x * box_size, y * box_size, box_size, box_size),
                )
    return surface


def make_agent_sprite(kind):
    size = AGENT_RADIUS * 2 + 10
    center = size // 2
    surf = pygame.Surface((size, size), pygame.SRCALPHA)

    pygame.draw.circle(surf, TYPE_COLORS[kind], (center, center), AGENT_RADIUS + 2)
    pygame.draw.circle(surf, (40, 40, 40), (center, center), AGENT_RADIUS + 2, 2)

    if kind == "rock":
        points = [
            (center - 9, center + 4),
            (center - 7, center - 6),
            (center - 1, center - 10),
            (center + 6, center - 8),
            (center + 10, center - 2),
            (center + 8, center + 7),
            (center + 1, center + 10),
            (center - 6, center + 9),
        ]
        pygame.draw.polygon(surf, (86, 96, 112), points)
        pygame.draw.polygon(surf, (25, 25, 25), points, 2)
    elif kind == "paper":
        rect = pygame.Rect(center - 9, center - 11, 18, 22)
        pygame.draw.rect(surf, (255, 255, 255), rect, border_radius=2)
        pygame.draw.rect(surf, (30, 30, 30), rect, 2, border_radius=2)
        fold = [(center + 3, center - 11), (center + 9, center - 11), (center + 9, center - 5)]
        pygame.draw.polygon(surf, (230, 230, 230), fold)
        pygame.draw.line(surf, (30, 30, 30), (center + 3, center - 11), (center + 9, center - 5), 2)
    else:
        pygame.draw.circle(surf, (245, 245, 245), (center - 5, center + 6), 4, 2)
        pygame.draw.circle(surf, (245, 245, 245), (center + 5, center + 6), 4, 2)
        pygame.draw.line(surf, (235, 235, 235), (center - 2, center + 2), (center - 10, center - 9), 3)
        pygame.draw.line(surf, (235, 235, 235), (center + 2, center + 2), (center + 10, center - 9), 3)
        pygame.draw.line(surf, (35, 35, 35), (center - 2, center + 2), (center - 10, center - 9), 1)
        pygame.draw.line(surf, (35, 35, 35), (center + 2, center + 2), (center + 10, center - 9), 1)

    return surf


def build_sprites():
    return {kind: make_agent_sprite(kind) for kind in RULES}


def build_background_surface():
    surface = pygame.Surface((WIDTH, HEIGHT))
    for y in range(HEIGHT):
        t = y / max(1, HEIGHT - 1)
        r = int(BG_TOP[0] + (BG_BOTTOM[0] - BG_TOP[0]) * t)
        g = int(BG_TOP[1] + (BG_BOTTOM[1] - BG_TOP[1]) * t)
        b = int(BG_TOP[2] + (BG_BOTTOM[2] - BG_TOP[2]) * t)
        pygame.draw.line(surface, (r, g, b), (0, y), (WIDTH, y))

    spacing = 42
    for x in range(0, WIDTH, spacing):
        pygame.draw.line(surface, GRID_COLOR, (x, 0), (x, HEIGHT), 1)
    for y in range(0, HEIGHT, spacing):
        pygame.draw.line(surface, GRID_COLOR, (0, y), (WIDTH, y), 1)
    return surface


class Agent:
    def __init__(self, x, y, kind, mobile_id=None, slot_id=None):
        self.pos = pygame.Vector2(x, y)
        self.kind = kind
        self.mobile_id = mobile_id
        self.slot_id = slot_id
        self.vel = pygame.Vector2(random.uniform(-1, 1), random.uniform(-1, 1)).normalize() * SPEED
        self.acc = pygame.Vector2(0, 0)
        self.heading_deg = math.degrees(math.atan2(-self.vel.y, self.vel.x))

    @property
    def is_mobile(self):
        return self.mobile_id is not None

    def _limit_inside(self):
        self.pos.x = clamp(self.pos.x, AGENT_RADIUS, WIDTH - AGENT_RADIUS)
        self.pos.y = clamp(self.pos.y, AGENT_RADIUS, HEIGHT - AGENT_RADIUS)

    def _move_mobile(self, input_vec):
        if input_vec.length() > 1:
            input_vec = input_vec.normalize()
        self.vel = input_vec * (SPEED * 1.8) if input_vec.length() > 0.03 else self.vel * 0.85
        self.pos += self.vel
        self._limit_inside()

    def _move_ai(self, all_agents):
        target_kind = RULES[self.kind]
        predator_kind = PREDATOR_RULES[self.kind]

        desired = pygame.Vector2(0, 0)
        separation = pygame.Vector2(0, 0)
        nearest_target = None
        nearest_dist = float("inf")
        chased = False

        for other in all_agents:
            if other is self:
                continue
            delta = self.pos - other.pos
            dist = delta.length()
            if dist < 0.1:
                continue

            if dist < AGENT_RADIUS * 3:
                separation += delta.normalize() / dist

            if dist < DETECTION_RADIUS:
                if other.kind == target_kind:
                    desired += (other.pos - self.pos).normalize()
                elif other.kind == predator_kind:
                    desired -= (other.pos - self.pos).normalize()
                    chased = True

            if other.kind == target_kind and dist < nearest_dist:
                nearest_dist = dist
                nearest_target = other

        if desired.length() == 0 and nearest_target:
            desired = (nearest_target.pos - self.pos).normalize()

        boundary = pygame.Vector2(0, 0)
        if chased:
            margin = 100
            if self.pos.x < margin:
                boundary.x = 1
            elif self.pos.x > WIDTH - margin:
                boundary.x = -1
            if self.pos.y < margin:
                boundary.y = 1
            elif self.pos.y > HEIGHT - margin:
                boundary.y = -1

        wander = pygame.Vector2(random.uniform(-1, 1), random.uniform(-1, 1)) * 0.2
        goal = desired + separation * 3 + boundary * 2 + wander

        if goal.length() > 0:
            target_vel = goal.normalize() * SPEED
            steer = target_vel - self.vel
            if steer.length() > MAX_FORCE:
                steer.scale_to_length(MAX_FORCE)
            self.acc += steer

        self.vel += self.acc
        if self.vel.length() > SPEED:
            self.vel.scale_to_length(SPEED)

        self.pos += self.vel
        self.acc *= 0

        if self.pos.x <= AGENT_RADIUS or self.pos.x >= WIDTH - AGENT_RADIUS:
            self.vel.x *= -1
        if self.pos.y <= AGENT_RADIUS or self.pos.y >= HEIGHT - AGENT_RADIUS:
            self.vel.y *= -1
        self._limit_inside()

    def move(self, all_agents, mobile_inputs):
        if self.is_mobile:
            x, y = mobile_inputs.get(self.mobile_id, (0.0, 0.0))
            self._move_mobile(pygame.Vector2(x, y))
        else:
            self._move_ai(all_agents)

    def move_in_test(self, mobile_inputs):
        if not self.is_mobile:
            return
        x, y = mobile_inputs.get(self.mobile_id, (0.0, 0.0))
        self._move_mobile(pygame.Vector2(x, y))

    def collide_and_convert(self, all_agents):
        for other in all_agents:
            if other is self:
                continue
            delta = self.pos - other.pos
            dist = delta.length()
            if dist >= AGENT_RADIUS * 2:
                continue

            if dist > 0:
                overlap = AGENT_RADIUS * 2 - dist
                n = delta.normalize()
                self.pos += n * (overlap / 2)
                other.pos -= n * (overlap / 2)

            if other.kind == PREDATOR_RULES[self.kind]:
                self.kind = PREDATOR_RULES[self.kind]

    def draw(self, screen, sprites):
        if self.slot_id is not None:
            ring = PLAYER_HIGHLIGHTS[self.slot_id]
            pygame.draw.circle(
                screen,
                ring,
                (int(self.pos.x), int(self.pos.y)),
                AGENT_RADIUS + 6,
                3 if self.is_mobile else 1,
            )

        if self.vel.length() > 0.05:
            self.heading_deg = math.degrees(math.atan2(-self.vel.y, self.vel.x))

        base = sprites[self.kind]
        rotated = pygame.transform.rotate(base, self.heading_deg - SPRITE_FORWARD_DEG[self.kind])
        rect = rotated.get_rect(center=(int(self.pos.x), int(self.pos.y)))
        screen.blit(rotated, rect)


def create_agents(connected_players):
    connected_set = set(connected_players)
    agents = []

    for kind in ("rock", "paper", "scissors"):
        for _ in range(NPC_PER_TYPE):
            agents.append(
                Agent(
                    random.randint(50, WIDTH - 50),
                    random.randint(50, HEIGHT - 50),
                    kind,
                )
            )

    for player_id in range(1, MAX_PLAYERS + 1):
        assignment = PLAYER_ASSIGNMENTS[player_id]
        sx, sy = assignment["spawn"]
        mobile_id = player_id if player_id in connected_set else None
        agents.append(Agent(sx, sy, assignment["type"], mobile_id=mobile_id, slot_id=player_id))

    return agents


def create_test_agents(connected_players):
    connected_set = set(connected_players)
    agents = []
    for player_id in range(1, MAX_PLAYERS + 1):
        assignment = PLAYER_ASSIGNMENTS[player_id]
        sx, sy = assignment["spawn"]
        mobile_id = player_id if player_id in connected_set else None
        agent = Agent(sx, sy, assignment["type"], mobile_id=mobile_id, slot_id=player_id)
        if not agent.is_mobile:
            agent.vel = pygame.Vector2(0, 0)
        agents.append(agent)
    return agents


def draw_pause_button(screen, font, paused):
    rect = pygame.Rect(WIDTH - 162, 12, 146, 38)
    color = (61, 126, 219) if not paused else (52, 162, 106)
    pygame.draw.rect(screen, color, rect, border_radius=8)
    label = "PAUSE (P)" if not paused else "RESUME (P)"
    text = font.render(label, True, (255, 255, 255))
    screen.blit(text, (rect.centerx - text.get_width() // 2, rect.centery - text.get_height() // 2))
    return rect


def draw_network_hud(screen, font, connected_players, latency_ms):
    x = 15
    y = 12
    for player_id in range(1, MAX_PLAYERS + 1):
        if player_id in connected_players:
            ms = latency_ms.get(player_id, 9999.0)
            ms = round(ms / 5.0) * 5.0
            if ms < 90:
                quality = "GOOD"
                color = (40, 145, 60)
            elif ms < 180:
                quality = "OK"
                color = (205, 150, 25)
            else:
                quality = "LAG"
                color = (200, 65, 65)
            line = f"{PLAYER_LABELS[player_id]}: {int(ms)}ms {quality}"
        else:
            line = f"{PLAYER_LABELS[player_id]}: --"
            color = (120, 120, 120)
        text = font.render(line, True, color)
        screen.blit(text, (x, y))
        y += 22


def draw_menu_network_info(screen, font, connected_players, latency_ms):
    if not connected_players:
        return

    x = 60
    y = HEIGHT - 128
    title = font.render("Network:", True, (50, 50, 50))
    screen.blit(title, (x, y))
    y += 24

    for player_id in connected_players:
        ms = latency_ms.get(player_id, 9999.0)
        ms = round(ms / 5.0) * 5.0
        if ms < 90:
            color = (40, 145, 60)
            quality = "GOOD"
        elif ms < 180:
            color = (205, 150, 25)
            quality = "OK"
        else:
            color = (200, 65, 65)
            quality = "LAG"

        line = f"{PLAYER_LABELS[player_id]} {int(ms)}ms {quality}"
        screen.blit(font.render(line, True, color), (x + 8, y))
        y += 22


def update_and_draw_trails(screen, trail_surface, agents):
    trail_surface.fill((255, 255, 255, 226), special_flags=pygame.BLEND_RGBA_MULT)
    for agent in agents:
        color = TYPE_COLORS[agent.kind]
        trail_color = (color[0], color[1], color[2], 85)
        head = (int(agent.pos.x), int(agent.pos.y))
        tail = (int(agent.pos.x - agent.vel.x * 4), int(agent.pos.y - agent.vel.y * 4))
        pygame.draw.line(trail_surface, trail_color, tail, head, 2)
        pygame.draw.circle(trail_surface, trail_color, head, max(3, AGENT_RADIUS - 6))
    screen.blit(trail_surface, (0, 0))


def render_arena(screen, bg_surface, trail_surface, agents, sprites, tag_font, connected_players, latency_ms, hud_font, animate_trail=True):
    screen.blit(bg_surface, (0, 0))
    if animate_trail:
        update_and_draw_trails(screen, trail_surface, agents)
    else:
        screen.blit(trail_surface, (0, 0))

    for agent in agents:
        agent.draw(screen, sprites)
    draw_player_tags(screen, agents, tag_font, connected_players)
    draw_network_hud(screen, hud_font, connected_players, latency_ms)


def draw_player_tags(screen, agents, font, connected_players):
    connected_set = set(connected_players)
    hide_non_connected = len(connected_set) == 1

    for agent in agents:
        if agent.slot_id is None:
            continue
        if hide_non_connected and agent.slot_id not in connected_set:
            continue

        kind = PLAYER_ASSIGNMENTS[agent.slot_id]["type"].upper()
        label = font.render(f"P{agent.slot_id} {kind}", True, PLAYER_HIGHLIGHTS[agent.slot_id])
        x = int(agent.pos.x - label.get_width() / 2)
        y = max(8, int(agent.pos.y) - 28)
        screen.blit(label, (x, y))


def draw_player_legend(screen, font, connected_players):
    connected = set(connected_players)
    one_player_mode = len(connected) == 1
    y = 190

    for player_id in range(1, MAX_PLAYERS + 1):
        kind = PLAYER_ASSIGNMENTS[player_id]["type"].upper()
        if player_id in connected:
            text = f"P{player_id} -> {kind}: Connected"
        elif one_player_mode:
            text = f"P{player_id} -> {kind}"
        else:
            text = f"P{player_id} -> {kind}: Waiting"

        rendered = font.render(text, True, PLAYER_HIGHLIGHTS[player_id])
        screen.blit(rendered, (450, y))
        y += 34


def draw_menu(
    screen,
    bg_surface,
    title_font,
    font,
    small_font,
    button_font,
    join_url,
    qr_surface,
    connected_players,
    latency_ms,
):
    screen.blit(bg_surface, (0, 0))

    title = title_font.render("RPS Battle - 3P Mobile", True, (35, 35, 35))
    screen.blit(title, (WIDTH // 2 - title.get_width() // 2, 40))

    screen.blit(font.render("Scan QR or open this URL on phone:", True, (60, 60, 60)), (60, 120))
    screen.blit(small_font.render(join_url, True, (20, 55, 145)), (60, 160))

    if qr_surface is not None:
        screen.blit(qr_surface, (60, 210))
        tip = "Players scan this QR and move joystick in browser."
        screen.blit(small_font.render(tip, True, (70, 70, 70)), (60, 210 + qr_surface.get_height() + 12))
    else:
        screen.blit(small_font.render(QR_MISSING_MSG, True, (140, 50, 50)), (60, 210))
        install = "Or install all deps: pip3 install -r requirements.txt"
        screen.blit(small_font.render(install, True, (140, 50, 50)), (60, 242))

    if connected_players:
        connected_text = "Connected: " + " ".join(PLAYER_LABELS[p] for p in connected_players)
    else:
        connected_text = "Connected: none"
    screen.blit(font.render(connected_text, True, (30, 30, 30)), (60, HEIGHT - 170))
    draw_menu_network_info(screen, small_font, connected_players, latency_ms)
    draw_player_legend(screen, small_font, connected_players)

    test_button = pygame.Rect(WIDTH // 2 - 140, HEIGHT - 184, 280, 58)
    pygame.draw.rect(screen, (58, 105, 172), test_button, border_radius=10)
    test_text = button_font.render("TEST CONTROLS (10s)", True, (255, 255, 255))
    screen.blit(test_text, (test_button.centerx - test_text.get_width() // 2, test_button.centery - test_text.get_height() // 2))

    button = pygame.Rect(WIDTH // 2 - 140, HEIGHT - 110, 280, 62)
    pygame.draw.rect(screen, (40, 170, 80), button, border_radius=10)
    button_text = f"START ({len(connected_players)}/3 connected)"
    label = button_font.render(button_text, True, (255, 255, 255))
    screen.blit(label, (button.centerx - label.get_width() // 2, button.centery - label.get_height() // 2))

    hint = "Missing players will be AI-controlled."
    screen.blit(small_font.render(hint, True, (70, 70, 70)), (WIDTH // 2 - 175, HEIGHT - 38))

    return button, test_button


def main():
    pygame.init()
    pygame.font.init()

    try:
        is_fullscreen = START_FULLSCREEN
        screen = create_screen(is_fullscreen)
    except pygame.error as error:
        print(f"Failed to open game window: {error}")
        pygame.quit()
        return

    pygame.display.set_caption("RPS Battle - 3 Mobile Players")
    clock = pygame.time.Clock()
    font = pygame.font.Font(None, 38)
    small_font = pygame.font.Font(None, 30)
    button_font = pygame.font.Font(None, 28)
    tag_font = pygame.font.Font(None, 22)
    title_font = pygame.font.Font(None, 76)

    hub = MobileHub(MAX_PLAYERS)
    try:
        server = start_server(hub, load_controller_html(), host=SERVER_HOST, port=SERVER_PORT)
    except OSError as error:
        print(f"Failed to start local controller server on port {SERVER_PORT}: {error}")
        pygame.quit()
        return

    local_ip = get_local_ip()
    join_url = f"http://{local_ip}:{SERVER_PORT}/join"
    qr_surface = build_qr_surface(join_url)
    if qr_surface is None:
        print(QR_MISSING_MSG)

    sprites = build_sprites()
    bg_surface = build_background_surface()
    trail_surface = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
    agents = []
    state = "menu"
    countdown_start = 0.0
    test_start = 0.0
    pause_return_state = "playing"
    display_latency_ms = {}
    next_latency_update = 0.0

    try:
        running = True
        while running:
            mobile_inputs, connected_players, latency_ms = hub.snapshot()
            now = time.monotonic()
            if now >= next_latency_update:
                display_latency_ms = dict(latency_ms)
                next_latency_update = now + 0.45
            events = pygame.event.get()
            mouse_pos = pygame.mouse.get_pos()

            for event in events:
                if event.type == pygame.QUIT:
                    running = False
                elif event.type == pygame.KEYDOWN and event.key == pygame.K_f:
                    is_fullscreen = not is_fullscreen
                    screen = create_screen(is_fullscreen)

            if state == "menu":
                start_btn, test_btn = draw_menu(
                    screen,
                    bg_surface,
                    title_font,
                    font,
                    small_font,
                    button_font,
                    join_url,
                    qr_surface,
                    connected_players,
                    display_latency_ms,
                )
                for event in events:
                    if event.type == pygame.MOUSEBUTTONDOWN and start_btn.collidepoint(mouse_pos):
                        agents = create_agents(connected_players)
                        trail_surface.fill((0, 0, 0, 0))
                        countdown_start = time.monotonic()
                        state = "countdown"
                    elif event.type == pygame.MOUSEBUTTONDOWN and test_btn.collidepoint(mouse_pos):
                        agents = create_test_agents(connected_players)
                        trail_surface.fill((0, 0, 0, 0))
                        test_start = time.monotonic()
                        state = "test"
                    elif event.type == pygame.KEYDOWN and event.key == pygame.K_RETURN:
                        agents = create_agents(connected_players)
                        trail_surface.fill((0, 0, 0, 0))
                        countdown_start = time.monotonic()
                        state = "countdown"
                    elif event.type == pygame.KEYDOWN and event.key == pygame.K_t:
                        agents = create_test_agents(connected_players)
                        trail_surface.fill((0, 0, 0, 0))
                        test_start = time.monotonic()
                        state = "test"

            elif state == "test":
                for agent in agents:
                    agent.move_in_test(mobile_inputs)
                render_arena(
                    screen,
                    bg_surface,
                    trail_surface,
                    agents,
                    sprites,
                    tag_font,
                    connected_players,
                    display_latency_ms,
                    small_font,
                    animate_trail=True,
                )
                pause_btn = draw_pause_button(screen, small_font, paused=False)

                elapsed = time.monotonic() - test_start
                remain = max(0.0, TEST_SECONDS - elapsed)
                title = font.render(f"Control Test: {remain:0.1f}s", True, (45, 45, 45))
                screen.blit(title, (WIDTH // 2 - title.get_width() // 2, 14))
                hint = small_font.render("Press ENTER to start match, ESC to menu", True, (45, 45, 45))
                screen.blit(hint, (WIDTH // 2 - hint.get_width() // 2, 42))

                if elapsed >= TEST_SECONDS:
                    state = "menu"

                for event in events:
                    if event.type == pygame.MOUSEBUTTONDOWN and pause_btn.collidepoint(mouse_pos):
                        pause_return_state = "test"
                        state = "paused"
                    elif event.type == pygame.KEYDOWN and event.key == pygame.K_p:
                        pause_return_state = "test"
                        state = "paused"
                    elif event.type == pygame.KEYDOWN and event.key == pygame.K_RETURN:
                        agents = create_agents(connected_players)
                        trail_surface.fill((0, 0, 0, 0))
                        countdown_start = time.monotonic()
                        state = "countdown"
                    elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                        state = "menu"

            elif state == "countdown":
                render_arena(
                    screen,
                    bg_surface,
                    trail_surface,
                    agents,
                    sprites,
                    tag_font,
                    connected_players,
                    display_latency_ms,
                    small_font,
                    animate_trail=True,
                )

                elapsed = time.monotonic() - countdown_start
                remain = max(1, COUNTDOWN_SECONDS - int(elapsed))
                num = title_font.render(str(remain), True, (35, 35, 35))
                screen.blit(num, (WIDTH // 2 - num.get_width() // 2, HEIGHT // 2 - num.get_height() // 2))

                hint = font.render("Get ready! Check your position.", True, (55, 55, 55))
                screen.blit(hint, (WIDTH // 2 - hint.get_width() // 2, HEIGHT // 2 + 70))

                if elapsed >= COUNTDOWN_SECONDS:
                    state = "playing"

                for event in events:
                    if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                        state = "menu"

            elif state == "playing":
                for agent in agents:
                    agent.move(agents, mobile_inputs)
                for agent in agents:
                    agent.collide_and_convert(agents)
                render_arena(
                    screen,
                    bg_surface,
                    trail_surface,
                    agents,
                    sprites,
                    tag_font,
                    connected_players,
                    display_latency_ms,
                    small_font,
                    animate_trail=True,
                )
                pause_btn = draw_pause_button(screen, small_font, paused=False)

                controlled = sorted(a.slot_id for a in agents if a.slot_id is not None and a.is_mobile)
                ctrl_text = ", ".join(PLAYER_LABELS[p] for p in controlled) if controlled else "none"
                screen.blit(small_font.render("Player-controlled: " + ctrl_text, True, (40, 40, 40)), (15, 82))

                for event in events:
                    if event.type == pygame.MOUSEBUTTONDOWN and pause_btn.collidepoint(mouse_pos):
                        pause_return_state = "playing"
                        state = "paused"
                    elif event.type == pygame.KEYDOWN and event.key == pygame.K_p:
                        pause_return_state = "playing"
                        state = "paused"

                if len({agent.kind for agent in agents}) == 1:
                    state = "game_over"

            elif state == "paused":
                render_arena(
                    screen,
                    bg_surface,
                    trail_surface,
                    agents,
                    sprites,
                    tag_font,
                    connected_players,
                    display_latency_ms,
                    small_font,
                    animate_trail=False,
                )
                resume_btn = draw_pause_button(screen, small_font, paused=True)

                overlay = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
                overlay.fill((0, 0, 0, 90))
                screen.blit(overlay, (0, 0))
                paused_text = title_font.render("PAUSED", True, (255, 255, 255))
                screen.blit(paused_text, (WIDTH // 2 - paused_text.get_width() // 2, HEIGHT // 2 - 80))
                hint = small_font.render("Press P or click RESUME to continue", True, (255, 255, 255))
                screen.blit(hint, (WIDTH // 2 - hint.get_width() // 2, HEIGHT // 2 - 28))
                hint2 = small_font.render("Press ESC to menu", True, (235, 235, 235))
                screen.blit(hint2, (WIDTH // 2 - hint2.get_width() // 2, HEIGHT // 2 + 2))

                for event in events:
                    if event.type == pygame.MOUSEBUTTONDOWN and resume_btn.collidepoint(mouse_pos):
                        state = pause_return_state
                    elif event.type == pygame.KEYDOWN and event.key == pygame.K_p:
                        state = pause_return_state
                    elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                        state = "menu"

            elif state == "game_over":
                render_arena(
                    screen,
                    bg_surface,
                    trail_surface,
                    agents,
                    sprites,
                    tag_font,
                    connected_players,
                    display_latency_ms,
                    small_font,
                    animate_trail=False,
                )

                overlay = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
                overlay.fill((0, 0, 0, 100))
                screen.blit(overlay, (0, 0))

                winner = agents[0].kind.upper()
                win_text = title_font.render(f"{winner} WINS!", True, (255, 255, 255))
                screen.blit(win_text, (WIDTH // 2 - win_text.get_width() // 2, HEIGHT // 2 - 60))

                info = small_font.render("Press R to replay, ESC to menu", True, (255, 255, 255))
                screen.blit(info, (WIDTH // 2 - info.get_width() // 2, HEIGHT // 2 + 10))

                for event in events:
                    if event.type == pygame.KEYDOWN and event.key == pygame.K_r:
                        agents = create_agents(connected_players)
                        trail_surface.fill((0, 0, 0, 0))
                        countdown_start = time.monotonic()
                        state = "countdown"
                    elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                        state = "menu"

            pygame.display.flip()
            clock.tick(FPS)
    finally:
        server.shutdown()
        server.server_close()
        pygame.quit()


if __name__ == "__main__":
    main()
