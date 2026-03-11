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
