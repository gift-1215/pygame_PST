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
PLAYER_SPEED_MULT = 2.45
PLAYER_PUSH_IMPULSE = 0.9
MAX_FORCE = 0.2
DETECTION_RADIUS = 180
AGENT_RADIUS = 15
NPC_PER_TYPE = 26

SERVER_HOST = "0.0.0.0"
SERVER_PORT = 8765
MAX_PLAYERS = 6
COUNTDOWN_SECONDS = 3
TEST_SECONDS = 10
START_FULLSCREEN = False
CONNECTION_STALE_SECONDS = 20.0
INPUT_STALE_SECONDS = 0.35
POSITIONING_RADIUS = 26
POSITIONING_SPEED_MULT = 0.42

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
TEAM_TYPES = ("scissors", "rock", "paper")
TEAM_LABELS = {
    "scissors": "Scissors Team",
    "rock": "Rock Team",
    "paper": "Paper Team",
}
TEAM_COLORS = {
    "scissors": (255, 70, 70),
    "rock": (0, 114, 178),
    "paper": (230, 159, 0),
}
PLAYER_ASSIGNMENTS = {
    1: {"type": "scissors", "group": "scissors", "label": "S1"},
    2: {"type": "scissors", "group": "scissors", "label": "S2"},
    3: {"type": "rock", "group": "rock", "label": "R1"},
    4: {"type": "rock", "group": "rock", "label": "R2"},
    5: {"type": "paper", "group": "paper", "label": "P1"},
    6: {"type": "paper", "group": "paper", "label": "P2"},
}
PLAYER_LABELS = {slot_id: data["label"] for slot_id, data in PLAYER_ASSIGNMENTS.items()}
PLAYER_HIGHLIGHTS = {slot_id: TEAM_COLORS[data["group"]] for slot_id, data in PLAYER_ASSIGNMENTS.items()}
SPRITE_FORWARD_DEG = {
    "rock": 0.0,
    "paper": 90.0,
    "scissors": 90.0,
}

BG_TOP = (242, 246, 252)
BG_BOTTOM = (226, 232, 242)
GRID_COLOR = (214, 220, 232)
SPAWN_MARGIN = 70
NPC_SPAWN_MIN_DIST = AGENT_RADIUS * 2 + 10
PLAYER_SPAWN_MIN_DIST = 130


def clamp(value, low, high):
    return max(low, min(high, value))


def _distance_sq(a, b):
    dx = a[0] - b[0]
    dy = a[1] - b[1]
    return dx * dx + dy * dy


def _sample_spawn(existing, min_dist, margin=SPAWN_MARGIN, max_tries=250):
    min_dist_sq = min_dist * min_dist
    for _ in range(max_tries):
        pt = (random.randint(margin, WIDTH - margin), random.randint(margin, HEIGHT - margin))
        if all(_distance_sq(pt, other) >= min_dist_sq for other in existing):
            return pt
    # Fallback if map is too crowded.
    return (random.randint(margin, WIDTH - margin), random.randint(margin, HEIGHT - margin))


def _build_player_spawns():
    spawns = {}
    taken = []
    for player_id in range(1, MAX_PLAYERS + 1):
        pt = _sample_spawn(taken, PLAYER_SPAWN_MIN_DIST)
        spawns[player_id] = pt
        taken.append(pt)
    return spawns


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


def player_goal_text(player_id):
    assignment = PLAYER_ASSIGNMENTS[player_id]
    assigned = assignment["type"].upper()
    group = TEAM_LABELS[assignment["group"]]
    return f"Team: {group}. Goal: Make {assigned} win."


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
        self.group_slots = {
            group: [slot_id for slot_id, data in PLAYER_ASSIGNMENTS.items() if data["group"] == group]
            for group in TEAM_TYPES
        }

    def _first_free_slot(self, group):
        for slot_id in self.group_slots.get(group, ()):
            if slot_id not in self.player_to_token:
                return slot_id
        return None

    def _cleanup_stale(self, timeout_sec=CONNECTION_STALE_SECONDS):
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

    def join(self, existing_token=None, requested_group=None):
        with self.lock:
            self._cleanup_stale()

            if existing_token and existing_token in self.token_to_player:
                player_id = self.token_to_player[existing_token]
                now = time.monotonic()
                current_group = PLAYER_ASSIGNMENTS[player_id]["group"]

                if requested_group in TEAM_TYPES and requested_group != current_group:
                    target_player_id = self._first_free_slot(requested_group)
                    if target_player_id is None:
                        return False, None, None, "group_full"

                    self.player_to_token.pop(player_id, None)
                    self.player_to_token[target_player_id] = existing_token
                    self.token_to_player[existing_token] = target_player_id
                    self.inputs[player_id] = (0.0, 0.0)
                    self.last_rtt_ms[player_id] = None
                    self.inputs[target_player_id] = (0.0, 0.0)
                    self.last_rtt_ms[target_player_id] = None
                    self.last_seen[existing_token] = now
                    return True, target_player_id, existing_token, "switched_group"

                self.last_seen[existing_token] = now
                return True, player_id, existing_token, "reconnected"

            candidate_groups = []
            if requested_group in TEAM_TYPES:
                candidate_groups = [requested_group]
            else:
                candidate_groups = list(TEAM_TYPES)

            for group in candidate_groups:
                player_id = self._first_free_slot(group)
                if player_id is None:
                    continue
                token = secrets.token_urlsafe(12)
                self.player_to_token[player_id] = token
                self.token_to_player[token] = player_id
                self.last_seen[token] = time.monotonic()
                self.inputs[player_id] = (0.0, 0.0)
                return True, player_id, token, "joined"

            if requested_group in TEAM_TYPES:
                return False, None, None, "group_full"
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
            inputs = dict(self.inputs)
            latency = {}
            for player_id in connected:
                token = self.player_to_token.get(player_id)
                if not token:
                    continue
                age_sec = max(0.0, now - self.last_seen.get(token, now))
                age_ms = age_sec * 1000.0
                base_ms = self.last_rtt_ms.get(player_id) or 0.0
                latency[player_id] = age_ms + base_ms
                if age_sec > INPUT_STALE_SECONDS:
                    inputs[player_id] = (0.0, 0.0)
            return inputs, connected, latency


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
            requested_group = payload.get("group")
            ok, player_id, token, reason = self.hub.join(payload.get("token"), requested_group=requested_group)
            assigned_type = PLAYER_ASSIGNMENTS[player_id]["type"] if ok and player_id in PLAYER_ASSIGNMENTS else None
            assigned_group = PLAYER_ASSIGNMENTS[player_id]["group"] if ok and player_id in PLAYER_ASSIGNMENTS else None
            assigned_label = PLAYER_ASSIGNMENTS[player_id]["label"] if ok and player_id in PLAYER_ASSIGNMENTS else None
            goal_text = player_goal_text(player_id) if ok and player_id in PLAYER_ASSIGNMENTS else None
            self._send_json(
                200,
                {
                    "ok": ok,
                    "player_id": player_id,
                    "token": token,
                    "reason": reason,
                    "assigned_type": assigned_type,
                    "assigned_group": assigned_group,
                    "assigned_label": assigned_label,
                    "goal_text": goal_text,
                },
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


def build_team_preview_surfaces(sprites):
    previews = {}
    for group in TEAM_TYPES:
        base = sprites[group]
        previews[group] = pygame.transform.smoothscale(base, (96, 96))
    return previews


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
        self.anchor = pygame.Vector2(x, y)
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
        self.vel = input_vec * (SPEED * PLAYER_SPEED_MULT) if input_vec.length() > 0.03 else self.vel * 0.85
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

    def move_in_positioning(self, mobile_inputs):
        if not self.is_mobile:
            self.vel = pygame.Vector2(0, 0)
            return

        x, y = mobile_inputs.get(self.mobile_id, (0.0, 0.0))
        input_vec = pygame.Vector2(x, y)
        if input_vec.length() > 1:
            input_vec = input_vec.normalize()

        prep_speed = SPEED * PLAYER_SPEED_MULT * POSITIONING_SPEED_MULT
        if input_vec.length() > 0.03:
            self.vel = input_vec * prep_speed
        else:
            self.vel *= 0.78

        self.pos += self.vel
        offset = self.pos - self.anchor
        if offset.length() > POSITIONING_RADIUS:
            offset.scale_to_length(POSITIONING_RADIUS)
            self.pos = self.anchor + offset
            self.vel *= 0.45

        self._limit_inside()

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
                if self.is_mobile and not other.is_mobile:
                    self_share, other_share = 0.20, 0.80
                    other.vel -= n * PLAYER_PUSH_IMPULSE
                elif not self.is_mobile and other.is_mobile:
                    self_share, other_share = 0.80, 0.20
                    self.vel += n * PLAYER_PUSH_IMPULSE
                else:
                    self_share, other_share = 0.50, 0.50

                self.pos += n * (overlap * self_share)
                other.pos -= n * (overlap * other_share)

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
    occupied = []
    player_spawns = _build_player_spawns()

    for kind in ("rock", "paper", "scissors"):
        for _ in range(NPC_PER_TYPE):
            sx, sy = _sample_spawn(occupied, NPC_SPAWN_MIN_DIST)
            occupied.append((sx, sy))
            agents.append(
                Agent(
                    sx,
                    sy,
                    kind,
                )
            )

    for player_id in range(1, MAX_PLAYERS + 1):
        assignment = PLAYER_ASSIGNMENTS[player_id]
        sx, sy = player_spawns[player_id]
        mobile_id = player_id if player_id in connected_set else None
        agents.append(Agent(sx, sy, assignment["type"], mobile_id=mobile_id, slot_id=player_id))

    return agents


def create_positioning_agents(connected_players):
    agents = create_agents(connected_players)
    for agent in agents:
        agent.vel = pygame.Vector2(0, 0)
        agent.acc = pygame.Vector2(0, 0)
    return agents


def create_test_agents(connected_players):
    connected_set = set(connected_players)
    agents = []
    player_spawns = _build_player_spawns()
    for player_id in range(1, MAX_PLAYERS + 1):
        assignment = PLAYER_ASSIGNMENTS[player_id]
        sx, sy = player_spawns[player_id]
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


def draw_player_controlled_hud(screen, font, agents, y=12):
    controlled = sorted(a.slot_id for a in agents if a.slot_id is not None and a.is_mobile)
    ctrl_text = ", ".join(PLAYER_LABELS[p] for p in controlled) if controlled else "none"
    color = (40, 40, 40)
    text = font.render("Player-controlled: " + ctrl_text, True, color)
    screen.blit(text, (15, y))
    return y + text.get_height() + 8


def draw_network_hud(screen, font, connected_players, latency_ms, start_y=44):
    if not connected_players:
        return

    x = 15
    y = start_y
    for player_id in sorted(connected_players):
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
        text = font.render(line, True, color)
        screen.blit(text, (x, y))
        y += 22


def draw_menu_network_info(screen, font, connected_players, latency_ms):
    panel = pygame.Rect(50, HEIGHT - 245, 390, 185)
    pygame.draw.rect(screen, (255, 255, 255), panel, border_radius=14)
    pygame.draw.rect(screen, (210, 218, 232), panel, 1, border_radius=14)
    screen.blit(font.render("Connection", True, (45, 52, 66)), (panel.x + 16, panel.y + 14))

    if not connected_players:
        msg = font.render("No mobile connected", True, (120, 128, 142))
        screen.blit(msg, (panel.x + 16, panel.y + 60))
        return

    y = panel.y + 52
    for player_id in connected_players:
        ms = latency_ms.get(player_id, 9999.0)
        ms = round(ms / 5.0) * 5.0
        if ms < 90:
            dot = (54, 170, 95)
            text_color = (38, 110, 62)
            quality = "GOOD"
        elif ms < 180:
            dot = (224, 166, 43)
            text_color = (124, 94, 25)
            quality = "OK"
        else:
            dot = (226, 84, 78)
            text_color = (140, 55, 52)
            quality = "LAG"

        pygame.draw.circle(screen, dot, (panel.x + 22, y + 9), 6)
        line = f"{PLAYER_LABELS[player_id]}  {int(ms)}ms  {quality}"
        screen.blit(font.render(line, True, text_color), (panel.x + 36, y))
        y += 24


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


def draw_player_tags(screen, agents, font, connected_players):
    connected_set = set(connected_players)
    hide_non_connected = len(connected_set) == 1

    for agent in agents:
        if agent.slot_id is None:
            continue
        if hide_non_connected and agent.slot_id not in connected_set:
            continue

        kind = PLAYER_ASSIGNMENTS[agent.slot_id]["type"].upper()
        label = font.render(f"{PLAYER_LABELS[agent.slot_id]} {kind}", True, PLAYER_HIGHLIGHTS[agent.slot_id])
        x = int(agent.pos.x - label.get_width() / 2)
        y = max(8, int(agent.pos.y) - 28)
        screen.blit(label, (x, y))


def draw_player_legend(screen, font, small_font, connected_players):
    connected = set(connected_players)
    panel = pygame.Rect(WIDTH - 420, HEIGHT - 245, 370, 185)
    pygame.draw.rect(screen, (255, 255, 255), panel, border_radius=14)
    pygame.draw.rect(screen, (210, 218, 232), panel, 1, border_radius=14)
    screen.blit(font.render("Player Slots", True, (45, 52, 66)), (panel.x + 16, panel.y + 14))

    slot_order = [1, 2, 3, 4, 5, 6]
    for idx, player_id in enumerate(slot_order):
        col = idx % 2
        row = idx // 2
        x = panel.x + 18 + col * 172
        y = panel.y + 52 + row * 40
        is_connected = player_id in connected
        status_color = (54, 170, 95) if is_connected else (154, 162, 176)
        status_text = "connected" if is_connected else "waiting"
        label = PLAYER_LABELS[player_id]
        kind = PLAYER_ASSIGNMENTS[player_id]["type"].upper()

        pygame.draw.circle(screen, status_color, (x + 8, y + 11), 6)
        title = small_font.render(f"{label} {kind}", True, PLAYER_HIGHLIGHTS[player_id])
        screen.blit(title, (x + 18, y))
        meta = font.render(status_text, True, (96, 104, 120))
        screen.blit(meta, (x + 18, y + 18))


def draw_menu(
    screen,
    bg_surface,
    title_font,
    font,
    small_font,
    tiny_font,
    button_font,
    team_join_urls,
    team_qr_surfaces,
    team_preview_surfaces,
    connected_players,
    latency_ms,
):
    screen.blit(bg_surface, (0, 0))

    title = title_font.render("RPS BATTLE LOBBY", True, (31, 36, 46))
    screen.blit(title, (WIDTH // 2 - title.get_width() // 2, 34))
    sub = small_font.render("Scan one QR to join a team. Each team has 2 mobile slots.", True, (79, 89, 106))
    screen.blit(sub, (WIDTH // 2 - sub.get_width() // 2, 96))

    qr_box_y = 135
    qr_w = 390
    gap = 25
    for idx, group in enumerate(TEAM_TYPES):
        box_x = 60 + idx * (qr_w + gap)
        box = pygame.Rect(box_x, qr_box_y, qr_w, 290)
        shadow = box.move(0, 4)
        pygame.draw.rect(screen, (187, 196, 212), shadow, border_radius=14)
        pygame.draw.rect(screen, (255, 255, 255), box, border_radius=14)
        pygame.draw.rect(screen, (214, 220, 232), box, 1, border_radius=14)
        header = pygame.Rect(box_x, qr_box_y, qr_w, 44)
        tint = tuple(min(255, int(c * 0.28 + 184)) for c in TEAM_COLORS[group])
        pygame.draw.rect(screen, tint, header, border_top_left_radius=14, border_top_right_radius=14)

        team_title = font.render(TEAM_LABELS[group], True, TEAM_COLORS[group])
        screen.blit(team_title, (box_x + 16, qr_box_y + 8))

        qr_surface = team_qr_surfaces.get(group)
        if qr_surface is not None:
            qr_x = box_x + 23
            qr_y = qr_box_y + 65
            max_qr_bottom = box.bottom - 36
            if qr_y + qr_surface.get_height() > max_qr_bottom:
                qr_y = max(qr_box_y + 52, max_qr_bottom - qr_surface.get_height())

            qr_bg = pygame.Rect(qr_x - 7, qr_y - 7, qr_surface.get_width() + 14, qr_surface.get_height() + 14)
            pygame.draw.rect(screen, (249, 251, 255), qr_bg, border_radius=10)
            screen.blit(qr_surface, (qr_x, qr_y))

            preview_panel = pygame.Rect(box.right - 126, qr_box_y + 62, 104, 186)
            pygame.draw.rect(screen, (247, 250, 255), preview_panel, border_radius=10)
            pygame.draw.rect(screen, (220, 227, 239), preview_panel, 1, border_radius=10)
            preview_surface = team_preview_surfaces.get(group)
            if preview_surface is not None:
                preview_x = preview_panel.centerx - preview_surface.get_width() // 2
                preview_y = preview_panel.y + 36
                screen.blit(preview_surface, (preview_x, preview_y))
            look_text = tiny_font.render("In-game look", True, (88, 96, 112))
            screen.blit(
                look_text,
                (preview_panel.centerx - look_text.get_width() // 2, preview_panel.bottom - 22),
            )
            short_url = f"/join?group={group}"
            url_text = tiny_font.render(short_url, True, (63, 78, 112))
            screen.blit(url_text, (box_x + 18, box.bottom - 30))
        else:
            screen.blit(tiny_font.render(QR_MISSING_MSG, True, (140, 50, 50)), (box_x + 16, qr_box_y + 74))
            install = "Or: pip3 install -r requirements.txt"
            screen.blit(tiny_font.render(install, True, (140, 50, 50)), (box_x + 16, qr_box_y + 102))

    if connected_players:
        connected_text = "Connected: " + "  ".join(PLAYER_LABELS[p] for p in connected_players)
    else:
        connected_text = "Connected: none"
    screen.blit(font.render(connected_text, True, (40, 46, 58)), (50, HEIGHT - 300))
    draw_menu_network_info(screen, small_font, connected_players, latency_ms)
    draw_player_legend(screen, tiny_font, small_font, connected_players)

    test_button = pygame.Rect(WIDTH // 2 - 180, HEIGHT - 180, 360, 56)
    pygame.draw.rect(screen, (237, 242, 251), test_button, border_radius=12)
    pygame.draw.rect(screen, (88, 120, 176), test_button, 2, border_radius=12)
    test_text = button_font.render("TEST CONTROLS", True, (62, 92, 148))
    screen.blit(test_text, (test_button.centerx - test_text.get_width() // 2, test_button.centery - test_text.get_height() // 2))

    button = pygame.Rect(WIDTH // 2 - 180, HEIGHT - 112, 360, 68)
    pygame.draw.rect(screen, (38, 178, 96), button, border_radius=12)
    button_text = f"START ({len(connected_players)}/6 connected)"
    label = button_font.render(button_text, True, (255, 255, 255))
    screen.blit(label, (button.centerx - label.get_width() // 2, button.centery - label.get_height() // 2))

    hint = "Missing players will be AI-controlled."
    screen.blit(tiny_font.render(hint, True, (98, 104, 118)), (WIDTH // 2 - 98, HEIGHT - 26))
    fs_hint = tiny_font.render("F: Toggle Fullscreen", True, (98, 104, 118))
    screen.blit(fs_hint, (WIDTH - fs_hint.get_width() - 22, HEIGHT - 24))

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

    pygame.display.set_caption("RPS Battle - 6 Mobile Players")
    clock = pygame.time.Clock()
    font = pygame.font.Font(None, 38)
    small_font = pygame.font.Font(None, 30)
    button_font = pygame.font.Font(None, 28)
    tiny_font = pygame.font.Font(None, 24)
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
    base_join_url = f"http://{local_ip}:{SERVER_PORT}/join"
    team_join_urls = {
        group: f"{base_join_url}?group={group}" for group in TEAM_TYPES
    }
    team_qr_surfaces = {
        group: build_qr_surface(url) for group, url in team_join_urls.items()
    }
    if any(surface is None for surface in team_qr_surfaces.values()):
        print(QR_MISSING_MSG)

    sprites = build_sprites()
    team_preview_surfaces = build_team_preview_surfaces(sprites)
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
                    tiny_font,
                    button_font,
                    team_join_urls,
                    team_qr_surfaces,
                    team_preview_surfaces,
                    connected_players,
                    display_latency_ms,
                )
                for event in events:
                    if event.type == pygame.MOUSEBUTTONDOWN and start_btn.collidepoint(mouse_pos):
                        agents = create_positioning_agents(connected_players)
                        trail_surface.fill((0, 0, 0, 0))
                        state = "positioning"
                    elif event.type == pygame.MOUSEBUTTONDOWN and test_btn.collidepoint(mouse_pos):
                        agents = create_test_agents(connected_players)
                        trail_surface.fill((0, 0, 0, 0))
                        test_start = time.monotonic()
                        state = "test"
                    elif event.type == pygame.KEYDOWN and event.key == pygame.K_RETURN:
                        agents = create_positioning_agents(connected_players)
                        trail_surface.fill((0, 0, 0, 0))
                        state = "positioning"
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
                draw_network_hud(screen, small_font, connected_players, display_latency_ms, start_y=12)
                pause_btn = draw_pause_button(screen, small_font, paused=False)

                elapsed = time.monotonic() - test_start
                remain = max(0.0, TEST_SECONDS - elapsed)
                title = font.render(f"Control Test: {remain:0.1f}s", True, (45, 45, 45))
                screen.blit(title, (WIDTH // 2 - title.get_width() // 2, 14))
                hint = small_font.render("Press ENTER for match setup, ESC to menu", True, (45, 45, 45))
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
                        agents = create_positioning_agents(connected_players)
                        trail_surface.fill((0, 0, 0, 0))
                        state = "positioning"
                    elif event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                        state = "menu"

            elif state == "positioning":
                for agent in agents:
                    if agent.slot_id is not None:
                        agent.move_in_positioning(mobile_inputs)
                    else:
                        agent.vel = pygame.Vector2(0, 0)

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
                hud_next_y = draw_player_controlled_hud(screen, small_font, agents, y=12)
                draw_network_hud(screen, small_font, connected_players, display_latency_ms, start_y=hud_next_y)

                title = font.render("Match Setup: Find your character", True, (45, 45, 45))
                screen.blit(title, (WIDTH // 2 - title.get_width() // 2, 14))
                hint = small_font.render("NPC are paused. Move slightly to confirm your position.", True, (48, 48, 48))
                screen.blit(hint, (WIDTH // 2 - hint.get_width() // 2, 46))
                hint2 = small_font.render("Press S when everyone is ready (ESC to menu)", True, (40, 108, 63))
                screen.blit(hint2, (WIDTH // 2 - hint2.get_width() // 2, 76))

                for event in events:
                    if event.type == pygame.KEYDOWN and event.key == pygame.K_s:
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
                hud_next_y = draw_player_controlled_hud(screen, small_font, agents, y=12)
                draw_network_hud(screen, small_font, connected_players, display_latency_ms, start_y=hud_next_y)

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
                hud_next_y = draw_player_controlled_hud(screen, small_font, agents, y=12)
                draw_network_hud(screen, small_font, connected_players, display_latency_ms, start_y=hud_next_y)

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
                        agents = create_positioning_agents(connected_players)
                        trail_surface.fill((0, 0, 0, 0))
                        state = "positioning"
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
