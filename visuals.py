from pathlib import Path

import pygame

from game_settings import (
    AGENT_RADIUS,
    BG_BOTTOM,
    BG_TOP,
    GRID_COLOR,
    PLAYER_ASSIGNMENTS,
    PLAYER_HIGHLIGHTS,
    PLAYER_LABELS,
    QR_MISSING_MSG,
    RULES,
    TEAM_COLORS,
    TEAM_LABELS,
    TEAM_TYPES,
    TYPE_COLORS,
    WIDTH,
    HEIGHT,
)

try:
    import qrcode
except ImportError:
    qrcode = None


ICON_ASSET_DIR = Path(__file__).with_name("assets") / "icons"


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


def load_agent_sprite_asset(kind, size):
    path = ICON_ASSET_DIR / f"{kind}.png"
    if not path.exists():
        return None
    try:
        source = pygame.image.load(str(path)).convert_alpha()
    except pygame.error:
        return None
    return pygame.transform.smoothscale(source, (size, size))


def make_team_preview_icon(kind, size=96):
    center = size // 2
    surf = pygame.Surface((size, size), pygame.SRCALPHA)

    pygame.draw.circle(surf, TYPE_COLORS[kind], (center, center), size // 2 - 6)
    pygame.draw.circle(surf, (42, 48, 58), (center, center), size // 2 - 6, 4)

    if kind == "rock":
        points = [
            (center - 23, center + 12),
            (center - 18, center - 14),
            (center - 5, center - 24),
            (center + 13, center - 20),
            (center + 24, center - 6),
            (center + 21, center + 16),
            (center + 4, center + 24),
            (center - 15, center + 20),
        ]
        pygame.draw.polygon(surf, (86, 96, 112), points)
        pygame.draw.polygon(surf, (25, 25, 25), points, 4)
    elif kind == "paper":
        rect = pygame.Rect(center - 20, center - 26, 40, 52)
        pygame.draw.rect(surf, (255, 255, 255), rect, border_radius=5)
        pygame.draw.rect(surf, (30, 30, 30), rect, 4, border_radius=5)
        fold = [(center + 6, center - 26), (center + 20, center - 26), (center + 20, center - 12)]
        pygame.draw.polygon(surf, (232, 232, 232), fold)
        pygame.draw.line(surf, (40, 40, 40), (center + 6, center - 26), (center + 20, center - 12), 3)
    else:
        blade = (242, 242, 242)
        outline = (34, 34, 34)
        pygame.draw.circle(surf, blade, (center - 12, center + 14), 10, 4)
        pygame.draw.circle(surf, blade, (center + 12, center + 14), 10, 4)
        pygame.draw.line(surf, blade, (center - 5, center + 8), (center - 25, center - 18), 7)
        pygame.draw.line(surf, blade, (center + 5, center + 8), (center + 25, center - 18), 7)
        pygame.draw.line(surf, outline, (center - 5, center + 8), (center - 25, center - 18), 2)
        pygame.draw.line(surf, outline, (center + 5, center + 8), (center + 25, center - 18), 2)

    return surf


def build_sprites():
    sprite_size = 192
    sprites = {}
    for kind in RULES:
        asset_sprite = load_agent_sprite_asset(kind, sprite_size)
        sprites[kind] = asset_sprite if asset_sprite is not None else make_agent_sprite(kind)
    return sprites


def build_team_preview_surfaces(_sprites):
    previews = {}
    for group in TEAM_TYPES:
        from_asset = load_agent_sprite_asset(group, 96)
        previews[group] = from_asset if from_asset is not None else make_team_preview_icon(group, 96)
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


def draw_pause_button(screen, font, paused, top_y=12):
    rect = pygame.Rect(WIDTH - 162, top_y, 146, 38)
    color = (61, 126, 219) if not paused else (52, 162, 106)
    pygame.draw.rect(screen, color, rect, border_radius=8)
    label = "PAUSE (P)" if not paused else "RESUME (P)"
    text = font.render(label, True, (255, 255, 255))
    screen.blit(text, (rect.centerx - text.get_width() // 2, rect.centery - text.get_height() // 2))
    return rect


def draw_soft_text_block(
    screen,
    font,
    text,
    x,
    y,
    text_color=(40, 40, 40),
    align="left",
    pad_x=9,
    pad_y=4,
):
    text_surface = font.render(text, True, text_color)
    tx = x if align == "left" else x - text_surface.get_width() // 2
    panel = pygame.Rect(
        tx - pad_x,
        y - pad_y,
        text_surface.get_width() + pad_x * 2,
        text_surface.get_height() + pad_y * 2,
    )
    panel_surf = pygame.Surface((panel.width, panel.height), pygame.SRCALPHA)
    pygame.draw.rect(panel_surf, (252, 254, 255, 145), panel_surf.get_rect(), border_radius=8)
    pygame.draw.rect(panel_surf, (188, 198, 215, 130), panel_surf.get_rect(), 1, border_radius=8)
    screen.blit(panel_surf, (panel.x, panel.y))
    screen.blit(text_surface, (tx, y))
    return panel


def draw_soft_text_panel(screen, lines, center_x, top_y, pad_x=14, pad_y=10, line_gap=6):
    rendered = [font.render(text, True, color) for font, text, color in lines]
    content_w = max((surface.get_width() for surface in rendered), default=0)

    content_h = 0
    for idx, surface in enumerate(rendered):
        content_h += surface.get_height()
        if idx < len(rendered) - 1:
            content_h += line_gap

    panel = pygame.Rect(
        center_x - (content_w // 2) - pad_x,
        top_y - pad_y,
        content_w + pad_x * 2,
        content_h + pad_y * 2,
    )
    panel_surf = pygame.Surface((panel.width, panel.height), pygame.SRCALPHA)
    pygame.draw.rect(panel_surf, (252, 254, 255, 145), panel_surf.get_rect(), border_radius=10)
    pygame.draw.rect(panel_surf, (188, 198, 215, 130), panel_surf.get_rect(), 1, border_radius=10)
    screen.blit(panel_surf, (panel.x, panel.y))

    y = panel.y + pad_y
    for surface in rendered:
        x = center_x - surface.get_width() // 2
        screen.blit(surface, (x, y))
        y += surface.get_height() + line_gap

    return panel


def format_elapsed_mmss(elapsed_seconds):
    total = max(0, int(elapsed_seconds))
    mins = total // 60
    secs = total % 60
    return f"{mins:02d}:{secs:02d}"


def draw_match_timer_hud(screen, font, elapsed_seconds, top_y=12):
    timer_text = f"TIME {format_elapsed_mmss(elapsed_seconds)}"
    text = font.render(timer_text, True, (42, 52, 68))
    panel = pygame.Rect(
        WIDTH - 184 - text.get_width() - 18,
        top_y,
        text.get_width() + 18,
        text.get_height() + 10,
    )
    panel_surf = pygame.Surface((panel.width, panel.height), pygame.SRCALPHA)
    pygame.draw.rect(panel_surf, (252, 254, 255, 150), panel_surf.get_rect(), border_radius=8)
    pygame.draw.rect(panel_surf, (188, 198, 215, 132), panel_surf.get_rect(), 1, border_radius=8)
    screen.blit(panel_surf, (panel.x, panel.y))
    screen.blit(text, (panel.x + 9, panel.y + 5))
    return panel


def _draw_keycap(screen, font, label, x, y, active=False):
    w = max(30, 12 + len(label) * 11)
    h = 28
    rect = pygame.Rect(x, y, w, h)
    fill = (78, 126, 214) if active else (239, 243, 250)
    border = (57, 104, 191) if active else (137, 149, 173)
    text_color = (255, 255, 255) if active else (71, 82, 106)
    pygame.draw.rect(screen, fill, rect, border_radius=7)
    pygame.draw.rect(screen, border, rect, 2, border_radius=7)
    text = font.render(label, True, text_color)
    screen.blit(text, (rect.centerx - text.get_width() // 2, rect.centery - text.get_height() // 2))
    return rect


def draw_hotkey_bar(screen, font, items, active_labels):
    if not items:
        return

    measured = []
    total_w = 26
    for label, desc in items:
        cap_w = max(30, 12 + len(label) * 11)
        desc_w = font.size(desc)[0]
        measured.append((label, desc, cap_w, desc_w))
        total_w += cap_w + 8 + desc_w + 18

    panel = pygame.Rect(WIDTH // 2 - total_w // 2, HEIGHT - 40, total_w, 36)
    panel_surf = pygame.Surface((panel.width, panel.height), pygame.SRCALPHA)
    pygame.draw.rect(panel_surf, (250, 253, 255, 155), panel_surf.get_rect(), border_radius=11)
    pygame.draw.rect(panel_surf, (186, 196, 214, 145), panel_surf.get_rect(), 1, border_radius=11)
    screen.blit(panel_surf, (panel.x, panel.y))

    x = panel.x + 12
    y = panel.y + 4
    for label, desc, cap_w, _desc_w in measured:
        cap_rect = _draw_keycap(screen, font, label, x, y, active=label in active_labels)
        x = cap_rect.right + 8
        desc_text = font.render(desc, True, (82, 93, 116))
        screen.blit(desc_text, (x, panel.centery - desc_text.get_height() // 2))
        x += desc_text.get_width() + 18


def _wrap_single_line(font, text, max_width):
    if font.size(text)[0] <= max_width:
        return [text]

    parts = []
    remaining = text
    while remaining:
        chunk = remaining
        while chunk and font.size(chunk)[0] > max_width:
            chunk = chunk[:-1]
        if not chunk:
            break
        parts.append(chunk)
        remaining = remaining[len(chunk):]
    return parts or [text]


def draw_player_controlled_hud(screen, font, agents, y=12):
    controlled = sorted(a.slot_id for a in agents if a.slot_id is not None and a.is_mobile)
    ctrl_text = ", ".join(PLAYER_LABELS[p] for p in controlled) if controlled else "none"
    panel = draw_soft_text_block(screen, font, "Player-controlled: " + ctrl_text, 15, y, text_color=(40, 40, 40))
    return panel.bottom + 6


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

        panel = draw_soft_text_block(
            screen,
            font,
            f"{PLAYER_LABELS[player_id]}: {int(ms)}ms {quality}",
            x,
            y,
            text_color=color,
        )
        y = panel.bottom + 4


def draw_menu_network_info(screen, font, tiny_font, connected_players, latency_ms, pressed_buttons):
    panel = pygame.Rect(50, HEIGHT - 304, 390, 244)
    pygame.draw.rect(screen, (255, 255, 255), panel, border_radius=14)
    pygame.draw.rect(screen, (210, 218, 232), panel, 1, border_radius=14)

    if connected_players:
        connected_text = "Connected: " + "  ".join(PLAYER_LABELS[p] for p in connected_players)
    else:
        connected_text = "Connected: none"
    header = tiny_font.render(connected_text, True, (45, 52, 66))
    screen.blit(header, (panel.x + 16, panel.y + 15))

    if not connected_players:
        msg = font.render("No mobile connected", True, (120, 128, 142))
        screen.blit(msg, (panel.x + 16, panel.y + 60))
        return {}

    release_buttons = {}
    y = panel.y + 52
    for player_id in sorted(connected_players):
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

        release_rect = pygame.Rect(panel.right - 94, y - 1, 80, 22)
        release_id = f"release_{player_id}"
        pressed = release_id in pressed_buttons
        draw_rect = release_rect.move(0, 2 if pressed else 0)
        fill = (69, 117, 204) if pressed else (237, 242, 251)
        border = (58, 98, 175) if pressed else (88, 120, 176)
        label_color = (255, 255, 255) if pressed else (62, 92, 148)
        pygame.draw.rect(screen, fill, draw_rect, border_radius=7)
        pygame.draw.rect(screen, border, draw_rect, 2, border_radius=7)
        release_text = tiny_font.render("Release", True, label_color)
        screen.blit(
            release_text,
            (draw_rect.centerx - release_text.get_width() // 2, draw_rect.centery - release_text.get_height() // 2),
        )
        release_buttons[player_id] = draw_rect
        y += 30

    return release_buttons


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


def render_arena(screen, bg_surface, trail_surface, agents, sprites, tag_font, connected_players, animate_trail=True):
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
    if not connected_set:
        return

    for agent in agents:
        if agent.slot_id is None:
            continue
        if agent.slot_id not in connected_set:
            continue

        kind = PLAYER_ASSIGNMENTS[agent.slot_id]["type"].upper()
        draw_soft_text_block(
            screen,
            font,
            f"{PLAYER_LABELS[agent.slot_id]} {kind}",
            int(agent.pos.x),
            max(8, int(agent.pos.y) - 28),
            text_color=PLAYER_HIGHLIGHTS[agent.slot_id],
            align="center",
            pad_x=7,
            pad_y=3,
        )


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
    team_qr_surfaces,
    team_join_urls,
    team_preview_surfaces,
    connected_players,
    latency_ms,
    selected_difficulty,
    pressed_buttons,
):
    pressed_buttons = pressed_buttons or set()
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
            preview_panel = pygame.Rect(box.right - 126, qr_box_y + 62, 104, 186)
            full_url = str(team_join_urls.get(group, f"/join?group={group}"))
            url_x = box_x + 18
            url_w = max(80, preview_panel.x - url_x - 12)
            if "/join?" in full_url:
                prefix, suffix = full_url.split("/join?", 1)
                source_lines = [prefix, "/join?" + suffix]
            else:
                source_lines = [full_url]

            wrapped_lines = []
            for line in source_lines:
                wrapped_lines.extend(_wrap_single_line(tiny_font, line, url_w))

            line_height = tiny_font.get_height()
            total_height = len(wrapped_lines) * line_height + max(0, len(wrapped_lines) - 1) * 2
            url_y = box.bottom - 14 - total_height

            qr_x = box_x + 23
            qr_y = qr_box_y + 65
            max_qr_bottom = url_y - 8
            if qr_y + qr_surface.get_height() > max_qr_bottom:
                qr_y = max(qr_box_y + 52, max_qr_bottom - qr_surface.get_height())

            qr_bg = pygame.Rect(qr_x - 7, qr_y - 7, qr_surface.get_width() + 14, qr_surface.get_height() + 14)
            pygame.draw.rect(screen, (249, 251, 255), qr_bg, border_radius=10)
            screen.blit(qr_surface, (qr_x, qr_y))

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
            for idx, line in enumerate(wrapped_lines):
                line_surface = tiny_font.render(line, True, (63, 78, 112))
                screen.blit(line_surface, (url_x, url_y + idx * (line_height + 2)))
        else:
            screen.blit(tiny_font.render(QR_MISSING_MSG, True, (140, 50, 50)), (box_x + 16, qr_box_y + 74))
            install = "Or: pip3 install -r requirements.txt"
            screen.blit(tiny_font.render(install, True, (140, 50, 50)), (box_x + 16, qr_box_y + 102))

    release_buttons = draw_menu_network_info(
        screen,
        small_font,
        tiny_font,
        connected_players,
        latency_ms,
        pressed_buttons,
    )
    draw_player_legend(screen, tiny_font, small_font, connected_players)

    test_button = pygame.Rect(WIDTH // 2 - 180, HEIGHT - 214, 360, 56)
    diff_btn_y = test_button.y - 40
    diff_label = tiny_font.render("Difficulty", True, (79, 89, 106))
    screen.blit(diff_label, (test_button.centerx - diff_label.get_width() // 2, diff_btn_y - 22))

    easy_btn = pygame.Rect(test_button.centerx - 108, diff_btn_y, 98, 34)
    hard_btn = pygame.Rect(test_button.centerx + 10, diff_btn_y, 98, 34)
    easy_active = selected_difficulty == "easy"
    hard_active = selected_difficulty == "hard"

    easy_pressed = "menu_easy" in pressed_buttons
    hard_pressed = "menu_hard" in pressed_buttons
    test_pressed = "menu_test" in pressed_buttons
    rules_pressed = "menu_rules" in pressed_buttons
    start_pressed = "menu_start" in pressed_buttons

    easy_draw = easy_btn.move(0, 2 if easy_pressed else 0)
    hard_draw = hard_btn.move(0, 2 if hard_pressed else 0)
    test_draw = test_button.move(0, 2 if test_pressed else 0)
    rules_button = pygame.Rect(WIDTH - 210, 78, 160, 44)
    rules_draw = rules_button.move(0, 2 if rules_pressed else 0)
    button = pygame.Rect(WIDTH // 2 - 180, HEIGHT - 146, 360, 68)
    start_draw = button.move(0, 2 if start_pressed else 0)

    pygame.draw.rect(screen, (198, 228, 210) if (easy_active or easy_pressed) else (244, 247, 252), easy_draw, border_radius=8)
    pygame.draw.rect(screen, (53, 126, 83) if (easy_active or easy_pressed) else (142, 153, 176), easy_draw, 2, border_radius=8)
    easy_text = tiny_font.render("EASY", True, (255, 255, 255) if easy_pressed else ((45, 120, 74) if easy_active else (82, 93, 112)))
    screen.blit(easy_text, (easy_draw.centerx - easy_text.get_width() // 2, easy_draw.centery - easy_text.get_height() // 2))

    pygame.draw.rect(screen, (214, 225, 250) if (hard_active or hard_pressed) else (244, 247, 252), hard_draw, border_radius=8)
    pygame.draw.rect(screen, (62, 96, 170) if (hard_active or hard_pressed) else (142, 153, 176), hard_draw, 2, border_radius=8)
    hard_text = tiny_font.render("HARD", True, (255, 255, 255) if hard_pressed else ((50, 83, 164) if hard_active else (82, 93, 112)))
    screen.blit(hard_text, (hard_draw.centerx - hard_text.get_width() // 2, hard_draw.centery - hard_text.get_height() // 2))

    pygame.draw.rect(screen, (88, 120, 176) if test_pressed else (237, 242, 251), test_draw, border_radius=12)
    pygame.draw.rect(screen, (71, 101, 156), test_draw, 2, border_radius=12)
    test_text = button_font.render("TEST CONTROLS", True, (255, 255, 255) if test_pressed else (62, 92, 148))
    screen.blit(test_text, (test_draw.centerx - test_text.get_width() // 2, test_draw.centery - test_text.get_height() // 2))

    pygame.draw.rect(screen, (120, 136, 166) if rules_pressed else (246, 248, 252), rules_draw, border_radius=10)
    pygame.draw.rect(screen, (92, 108, 138), rules_draw, 2, border_radius=10)
    rules_text = tiny_font.render("RULES", True, (255, 255, 255) if rules_pressed else (77, 90, 116))
    screen.blit(rules_text, (rules_draw.centerx - rules_text.get_width() // 2, rules_draw.centery - rules_text.get_height() // 2))

    pygame.draw.rect(screen, (27, 158, 83) if start_pressed else (38, 178, 96), start_draw, border_radius=12)
    button_text = f"START ({len(connected_players)}/6 connected)"
    label = button_font.render(button_text, True, (236, 255, 241) if start_pressed else (255, 255, 255))
    screen.blit(label, (start_draw.centerx - label.get_width() // 2, start_draw.centery - label.get_height() // 2))

    fs_hint = tiny_font.render("F: Toggle Fullscreen", True, (98, 104, 118))
    screen.blit(fs_hint, (WIDTH - fs_hint.get_width() - 22, HEIGHT - fs_hint.get_height() - 6))

    return start_draw, test_draw, rules_draw, easy_draw, hard_draw, release_buttons
