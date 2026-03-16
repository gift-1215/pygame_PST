import json
import ipaddress
import secrets
import socket
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

from game_settings import (
    CONNECTION_STALE_SECONDS,
    INPUT_STALE_SECONDS,
    MAX_PLAYERS,
    MAX_LATENCY_MS,
    PLAYER_ASSIGNMENTS,
    TEAM_TYPES,
    clamp,
    player_goal_text,
)


def get_local_ip():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        return sock.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        sock.close()


def _is_private_ipv4(ip):
    try:
        parsed = ipaddress.ip_address(ip)
    except ValueError:
        return False
    return parsed.version == 4 and parsed.is_private and not parsed.is_loopback


def list_lan_ips():
    candidates = []

    def add(ip):
        if ip and _is_private_ipv4(ip) and ip not in candidates:
            candidates.append(ip)

    add(get_local_ip())

    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, family=socket.AF_INET, type=socket.SOCK_DGRAM):
            add(info[4][0])
    except OSError:
        pass

    try:
        for ip in socket.gethostbyname_ex(socket.gethostname())[2]:
            add(ip)
    except OSError:
        pass

    if not candidates:
        candidates.append("127.0.0.1")
    return candidates


def load_controller_html():
    html_file = Path(__file__).with_name("controller.html")
    if html_file.exists():
        return html_file.read_text(encoding="utf-8")
    return "<h1>Missing controller.html</h1>"


class MobileHub:
    def __init__(self, max_players=MAX_PLAYERS):
        self.max_players = max_players
        self.lock = threading.Lock()
        self.player_to_token = {}
        self.token_to_player = {}
        self.token_to_device = {}
        self.device_to_player = {}
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
            self._disconnect_player(player_id, token)

    def _disconnect_player(self, player_id, token):
        self.player_to_token.pop(player_id, None)
        self.token_to_player.pop(token, None)
        self.token_to_device.pop(token, None)
        self.last_seen.pop(token, None)
        self.inputs[player_id] = (0.0, 0.0)
        self.last_rtt_ms[player_id] = None

    def _assign_player_token(self, player_id, token, now, device_id=None):
        self.player_to_token[player_id] = token
        self.token_to_player[token] = player_id
        self.last_seen[token] = now
        self.inputs[player_id] = (0.0, 0.0)
        self.last_rtt_ms[player_id] = None
        if device_id:
            self.token_to_device[token] = device_id
            self.device_to_player[device_id] = player_id

    def join(self, existing_token=None, requested_group=None, device_id=None):
        with self.lock:
            self._cleanup_stale()
            now = time.monotonic()

            if existing_token and existing_token in self.token_to_player:
                player_id = self.token_to_player[existing_token]
                current_group = PLAYER_ASSIGNMENTS[player_id]["group"]
                if device_id:
                    self.token_to_device[existing_token] = device_id
                    self.device_to_player[device_id] = player_id

                if requested_group in TEAM_TYPES and requested_group != current_group:
                    target_player_id = self._first_free_slot(requested_group)
                    if target_player_id is None:
                        return False, None, None, "group_full"

                    self.player_to_token.pop(player_id, None)
                    self.inputs[player_id] = (0.0, 0.0)
                    self.last_rtt_ms[player_id] = None
                    self._assign_player_token(target_player_id, existing_token, now, device_id=device_id)
                    return True, target_player_id, existing_token, "switched_group"

                self.last_seen[existing_token] = now
                return True, player_id, existing_token, "reconnected"

            # If token is gone but same phone comes back, try reclaiming the remembered slot.
            if device_id and device_id in self.device_to_player:
                remembered_player = self.device_to_player[device_id]
                remembered_group = PLAYER_ASSIGNMENTS[remembered_player]["group"]
                if requested_group not in TEAM_TYPES or requested_group == remembered_group:
                    current_token = self.player_to_token.get(remembered_player)
                    if current_token is None:
                        token = secrets.token_urlsafe(12)
                        self._assign_player_token(remembered_player, token, now, device_id=device_id)
                        return True, remembered_player, token, "rejoined_device"

                    current_device = self.token_to_device.get(current_token)
                    if current_device == device_id:
                        self._disconnect_player(remembered_player, current_token)
                        token = secrets.token_urlsafe(12)
                        self._assign_player_token(remembered_player, token, now, device_id=device_id)
                        return True, remembered_player, token, "rejoined_device"

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
                self._assign_player_token(player_id, token, now, device_id=device_id)
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
                if measured is not None:
                    if measured > MAX_LATENCY_MS:
                        self._disconnect_player(player_id, token)
                        return False
                    if measured >= 0:
                        self.last_rtt_ms[player_id] = measured
            self.last_seen[token] = time.monotonic()
            return True

    def release_player(self, player_id):
        with self.lock:
            token = self.player_to_token.get(player_id)
            if token is None:
                return False
            self._disconnect_player(player_id, token)
            return True

    def snapshot(self):
        with self.lock:
            self._cleanup_stale()
            now = time.monotonic()
            connected = sorted(self.player_to_token.keys())
            inputs = dict(self.inputs)
            latency = {}
            disconnected = []
            for player_id in connected:
                token = self.player_to_token.get(player_id)
                if not token:
                    continue
                age_sec = max(0.0, now - self.last_seen.get(token, now))
                age_ms = age_sec * 1000.0
                base_ms = self.last_rtt_ms.get(player_id) or 0.0
                total_latency = age_ms + base_ms
                if total_latency > MAX_LATENCY_MS:
                    disconnected.append((player_id, token))
                    continue
                latency[player_id] = total_latency
                if age_sec > INPUT_STALE_SECONDS:
                    inputs[player_id] = (0.0, 0.0)

            for player_id, token in disconnected:
                self._disconnect_player(player_id, token)
                inputs[player_id] = (0.0, 0.0)

            connected = sorted(self.player_to_token.keys())
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
            ok, player_id, token, reason = self.hub.join(
                payload.get("token"),
                requested_group=requested_group,
                device_id=payload.get("device_id"),
            )
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


def start_server(hub, html, host, port):
    handler = type("BoundControllerHandler", (ControllerHandler,), {})
    handler.hub = hub
    handler.html = html
    httpd = ThreadingHTTPServer((host, port), handler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    return httpd
