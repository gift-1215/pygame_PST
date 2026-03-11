import random

# --------------------------
# Configuration
# --------------------------
WIDTH, HEIGHT = 1360, 750
FPS = 60
SPEED = 2.25
PLAYER_SPEED_MULT = 1.56
PLAYER_PUSH_IMPULSE = 0.9
MAX_FORCE = 0.2
DETECTION_RADIUS = 180
AGENT_RADIUS = 15
NPC_PER_TYPE = 26
EASY_TOTAL_PER_TEAM = 5
EASY_NPC_PER_TYPE = 3

SERVER_HOST = "0.0.0.0"
SERVER_PORT = 8765
MAX_PLAYERS = 6
COUNTDOWN_SECONDS = 3
TEST_SECONDS = 10
START_FULLSCREEN = False
CONNECTION_STALE_SECONDS = 20.0
INPUT_STALE_SECONDS = 0.35
MAX_LATENCY_MS = 5000.0
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


def player_goal_text(player_id):
    assignment = PLAYER_ASSIGNMENTS[player_id]
    assigned = assignment["type"].upper()
    group = TEAM_LABELS[assignment["group"]]
    return f"Team: {group}. Goal: Make {assigned} win."
