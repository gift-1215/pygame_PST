import math
import random
import time

import pygame

from agents import create_positioning_agents, create_test_agents
from game_settings import (
    COUNTDOWN_SECONDS,
    EASY_NPC_PER_TYPE,
    FPS,
    MAX_PLAYERS,
    NPC_PER_TYPE,
    QR_MISSING_MSG,
    SERVER_HOST,
    SERVER_PORT,
    SPEED_RAMP_START_SECONDS,
    SPEED_RAMP_END_SECONDS,
    SPEED_RAMP_STEP_MULT,
    SPEED_RAMP_STEP_SECONDS,
    START_FULLSCREEN,
    TEAM_COLORS,
    TEAM_TYPES,
    WIDTH,
    HEIGHT,
)
from networking import MobileHub, get_local_ip, load_controller_html, start_server
from rules_page import draw_rules_page
from visuals import (
    build_background_surface,
    build_qr_surface,
    build_sprites,
    build_team_preview_surfaces,
    draw_menu,
    draw_hotkey_bar,
    draw_network_hud,
    draw_match_timer_hud,
    draw_pause_button,
    draw_player_controlled_hud,
    format_elapsed_mmss,
    draw_soft_text_block,
    draw_soft_text_panel,
    render_arena,
)


def create_screen(fullscreen):
    flags = pygame.SCALED
    if fullscreen:
        flags |= pygame.FULLSCREEN
    return pygame.display.set_mode((WIDTH, HEIGHT), flags)


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
    state = "rules"
    countdown_start = 0.0
    test_start = 0.0
    pause_return_state = "playing"
    display_latency_ms = {}
    next_latency_update = 0.0
    selected_difficulty = "easy"
    match_elapsed_seconds = 0.0
    match_running_since = None
    victory_time_seconds = None
    game_over_started_at = None
    victory_confetti = []
    rules_return_state = "menu"
    input_lock_until = 0.0
    transition_until = 0.0
    transition_duration = 0.16
    key_anim_until = {}
    button_anim_until = {}
    pending_action = None

    def npc_per_type_for(difficulty):
        return EASY_NPC_PER_TYPE if difficulty == "easy" else NPC_PER_TYPE

    def hud_top_y():
        return 48 if is_fullscreen else 12

    def can_accept_input(now):
        return now >= input_lock_until

    def mark_key(label, now):
        key_anim_until[label] = now + 0.14

    def active_key_labels(now):
        return {label for label, until in key_anim_until.items() if until > now}

    def mark_button(button_id, now):
        button_anim_until[button_id] = now + 0.14

    def active_pressed_buttons(now):
        return {button_id for button_id, until in button_anim_until.items() if until > now}

    def set_transition(now):
        nonlocal transition_until
        transition_until = now + transition_duration

    def go_to(next_state, now):
        nonlocal state, input_lock_until
        if next_state == state:
            return
        if state == "playing" and next_state != "playing":
            pause_match_clock(now)
        if state != "playing" and next_state == "playing":
            start_match_clock(now)
        state = next_state
        input_lock_until = now + 0.20
        set_transition(now)

    def go_pause(return_state, now):
        nonlocal pause_return_state
        if return_state == "playing":
            pause_match_clock(now)
        pause_return_state = return_state
        go_to("paused", now)

    def schedule_action(action_name, now, payload=None, delay=0.09):
        nonlocal pending_action, input_lock_until
        pending_action = {"run_at": now + delay, "name": action_name, "payload": payload}
        input_lock_until = max(input_lock_until, now + delay)

    def execute_action(action_name, now, connected_players, payload=None):
        nonlocal agents, test_start, rules_return_state, display_latency_ms
        if action_name == "start_positioning":
            agents = create_positioning_agents(
                connected_players,
                npc_per_type=npc_per_type_for(selected_difficulty),
            )
            reset_match_clock()
            trail_surface.fill((0, 0, 0, 0))
            go_to("positioning", now)
            return
        if action_name == "start_test":
            agents = create_test_agents(connected_players)
            trail_surface.fill((0, 0, 0, 0))
            test_start = now
            go_to("test", now)
            return
        if action_name == "open_rules":
            rules_return_state = "menu"
            go_to("rules", now)
            return
        if action_name == "rules_to_menu":
            go_to("menu", now)
            return
        if action_name == "release_slot":
            if hub.release_player(payload):
                display_latency_ms.pop(payload, None)

    def run_pending_action(now, connected_players):
        nonlocal pending_action
        if pending_action is None:
            return
        if now < pending_action["run_at"]:
            return
        action = pending_action
        pending_action = None
        execute_action(action["name"], now, connected_players, payload=action.get("payload"))

    def sync_agent_control(connected_players):
        connected_set = set(connected_players)
        for agent in agents:
            if agent.slot_id is None:
                continue
            agent.mobile_id = agent.slot_id if agent.slot_id in connected_set else None

    def shortcut_items_for_state(current_state):
        if current_state == "rules":
            return [("ENTER", "Menu"), ("SPACE", "Menu"), ("ESC", "Back"), ("F1", "Rules"), ("M", "Menu"), ("F", "Fullscreen")]
        if current_state == "menu":
            return [("ENTER", "Start"), ("SPACE", "Start"), ("A/[", "Easy"), ("D/]", "Hard"), ("T", "Test"), ("F1", "Rules"), ("M", "Menu"), ("F", "Fullscreen")]
        if current_state == "test":
            return [("ENTER", "Setup"), ("SPACE", "Setup"), ("P", "Pause"), ("ESC", "Menu"), ("F1", "Rules"), ("M", "Menu")]
        if current_state == "positioning":
            return [("S", "Countdown"), ("ENTER", "Countdown"), ("SPACE", "Countdown"), ("ESC", "Menu"), ("F1", "Rules"), ("M", "Menu")]
        if current_state == "countdown":
            return [("ESC", "Menu"), ("F1", "Rules"), ("M", "Menu")]
        if current_state == "playing":
            return [("P", "Pause"), ("ESC", "Menu"), ("F1", "Rules"), ("M", "Menu")]
        if current_state == "paused":
            return [("P", "Resume"), ("ESC", "Menu"), ("F1", "Rules"), ("M", "Menu")]
        if current_state == "game_over":
            return [("R", "Replay"), ("ESC", "Menu"), ("F1", "Rules"), ("M", "Menu")]
        return [("F1", "Rules"), ("M", "Menu"), ("F", "Fullscreen")]

    def reset_match_clock():
        nonlocal match_elapsed_seconds, match_running_since, victory_time_seconds
        nonlocal game_over_started_at, victory_confetti
        match_elapsed_seconds = 0.0
        match_running_since = None
        victory_time_seconds = None
        game_over_started_at = None
        victory_confetti = []

    def start_match_clock(now):
        nonlocal match_running_since
        if match_running_since is None:
            match_running_since = now

    def pause_match_clock(now):
        nonlocal match_elapsed_seconds, match_running_since
        if match_running_since is not None:
            match_elapsed_seconds += max(0.0, now - match_running_since)
            match_running_since = None

    def current_match_elapsed(now):
        if match_running_since is None:
            return match_elapsed_seconds
        return match_elapsed_seconds + max(0.0, now - match_running_since)

    def speed_scale_for_elapsed(elapsed_seconds):
        if elapsed_seconds < SPEED_RAMP_START_SECONDS:
            return 1.0
        effective_elapsed = min(elapsed_seconds, SPEED_RAMP_END_SECONDS)
        steps = int((effective_elapsed - SPEED_RAMP_START_SECONDS) // SPEED_RAMP_STEP_SECONDS) + 1
        return 1.0 + steps * SPEED_RAMP_STEP_MULT

    def spawn_confetti_once(winner_color):
        particles = []
        palette = [
            winner_color,
            (255, 255, 255),
            (255, 214, 78),
            (130, 196, 255),
            (255, 126, 126),
        ]
        burst_x = WIDTH // 2
        burst_y = HEIGHT // 2 - 210
        for _ in range(170):
            angle = random.uniform(-2.9, -0.25)
            speed = random.uniform(180, 430)
            particles.append(
                {
                    "x": burst_x + random.uniform(-110, 110),
                    "y": burst_y + random.uniform(-24, 24),
                    "vx": math.cos(angle) * speed,
                    "vy": math.sin(angle) * speed,
                    "rot": random.uniform(0, 360),
                    "spin": random.uniform(-260, 260),
                    "size": random.randint(7, 15),
                    "life": random.uniform(2.2, 3.2),
                    "color": random.choice(palette),
                }
            )
        return particles

    try:
        running = True
        while running:
            mobile_inputs, connected_players, latency_ms = hub.snapshot()
            now = time.monotonic()
            run_pending_action(now, connected_players)
            sync_agent_control(connected_players)
            top_y = hud_top_y()
            if now >= next_latency_update:
                display_latency_ms = dict(latency_ms)
                next_latency_update = now + 0.45
            raw_events = pygame.event.get()
            mouse_pos = pygame.mouse.get_pos()
            events = []

            for event in raw_events:
                if event.type == pygame.QUIT:
                    running = False
                    continue

                if event.type == pygame.KEYDOWN:
                    if event.key == pygame.K_RETURN:
                        mark_key("ENTER", now)
                    elif event.key == pygame.K_SPACE:
                        mark_key("SPACE", now)
                    elif event.key == pygame.K_p:
                        mark_key("P", now)
                    elif event.key == pygame.K_s:
                        mark_key("S", now)
                    elif event.key == pygame.K_r:
                        mark_key("R", now)
                    elif event.key == pygame.K_t:
                        mark_key("T", now)
                    elif event.key == pygame.K_F1:
                        mark_key("F1", now)
                    elif event.key == pygame.K_m:
                        mark_key("M", now)
                    elif event.key == pygame.K_ESCAPE:
                        mark_key("ESC", now)
                    elif event.key in (pygame.K_a, pygame.K_LEFTBRACKET):
                        mark_key("A/[", now)
                    elif event.key in (pygame.K_d, pygame.K_RIGHTBRACKET):
                        mark_key("D/]", now)
                    elif event.key == pygame.K_f:
                        mark_key("F", now)

                    if event.key == pygame.K_f:
                        is_fullscreen = not is_fullscreen
                        screen = create_screen(is_fullscreen)
                        continue

                    if not can_accept_input(now):
                        continue

                    if event.key == pygame.K_F1:
                        if state != "rules":
                            rules_return_state = state
                        go_to("rules", now)
                        continue

                    if event.key == pygame.K_m:
                        if state != "menu":
                            reset_match_clock()
                        go_to("menu", now)
                        continue

                    if event.key == pygame.K_ESCAPE:
                        if state == "rules":
                            go_to(rules_return_state, now)
                        elif state == "menu":
                            rules_return_state = "menu"
                            go_to("rules", now)
                        else:
                            reset_match_clock()
                            go_to("menu", now)
                        continue

                events.append(event)

            if state == "rules":
                go_menu_btn = draw_rules_page(
                    screen,
                    bg_surface,
                    title_font,
                    font,
                    small_font,
                    button_font,
                    pressed_buttons=active_pressed_buttons(now),
                )
                for event in events:
                    if not can_accept_input(now):
                        continue
                    if event.type == pygame.MOUSEBUTTONDOWN and go_menu_btn.collidepoint(mouse_pos):
                        mark_button("rules_go_menu", now)
                        schedule_action("rules_to_menu", now)
                    elif event.type == pygame.KEYDOWN and event.key in (pygame.K_RETURN, pygame.K_SPACE):
                        go_to("menu", now)

            elif state == "menu":
                start_btn, test_btn, rules_btn, easy_btn, hard_btn, release_buttons = draw_menu(
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
                    display_latency_ms,
                    selected_difficulty,
                    active_pressed_buttons(now),
                )
                for event in events:
                    if not can_accept_input(now):
                        continue

                    if event.type == pygame.MOUSEBUTTONDOWN:
                        released_any = False
                        for player_id, release_btn in release_buttons.items():
                            if release_btn.collidepoint(mouse_pos):
                                button_id = f"release_{player_id}"
                                mark_button(button_id, now)
                                execute_action("release_slot", now, connected_players, payload=player_id)
                                released_any = True
                                break
                        if released_any:
                            continue

                    if event.type == pygame.MOUSEBUTTONDOWN and start_btn.collidepoint(mouse_pos):
                        mark_button("menu_start", now)
                        schedule_action("start_positioning", now)
                    elif event.type == pygame.MOUSEBUTTONDOWN and test_btn.collidepoint(mouse_pos):
                        mark_button("menu_test", now)
                        schedule_action("start_test", now)
                    elif event.type == pygame.KEYDOWN and event.key in (pygame.K_RETURN, pygame.K_SPACE):
                        execute_action("start_positioning", now, connected_players)
                    elif event.type == pygame.KEYDOWN and event.key == pygame.K_t:
                        execute_action("start_test", now, connected_players)
                    elif event.type == pygame.MOUSEBUTTONDOWN and rules_btn.collidepoint(mouse_pos):
                        mark_button("menu_rules", now)
                        schedule_action("open_rules", now)
                    elif event.type == pygame.MOUSEBUTTONDOWN and easy_btn.collidepoint(mouse_pos):
                        mark_button("menu_easy", now)
                        selected_difficulty = "easy"
                    elif event.type == pygame.MOUSEBUTTONDOWN and hard_btn.collidepoint(mouse_pos):
                        mark_button("menu_hard", now)
                        selected_difficulty = "hard"
                    elif event.type == pygame.KEYDOWN and event.key in (pygame.K_a, pygame.K_LEFTBRACKET):
                        selected_difficulty = "easy"
                    elif event.type == pygame.KEYDOWN and event.key in (pygame.K_d, pygame.K_RIGHTBRACKET):
                        selected_difficulty = "hard"

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
                    animate_trail=True,
                )
                draw_network_hud(screen, small_font, connected_players, display_latency_ms, start_y=top_y)
                pause_btn = draw_pause_button(screen, small_font, paused=False, top_y=top_y)

                draw_soft_text_panel(
                    screen,
                    [
                        (font, "Control Test", (45, 45, 45)),
                        (small_font, "Press ENTER for match setup, ESC to menu", (45, 45, 45)),
                    ],
                    WIDTH // 2,
                    top_y,
                )

                for event in events:
                    if not can_accept_input(now):
                        continue
                    if event.type == pygame.MOUSEBUTTONDOWN and pause_btn.collidepoint(mouse_pos):
                        go_pause("test", now)
                    elif event.type == pygame.KEYDOWN and event.key == pygame.K_p:
                        go_pause("test", now)
                    elif event.type == pygame.KEYDOWN and event.key in (pygame.K_RETURN, pygame.K_SPACE):
                        agents = create_positioning_agents(
                            connected_players,
                            npc_per_type=npc_per_type_for(selected_difficulty),
                        )
                        reset_match_clock()
                        trail_surface.fill((0, 0, 0, 0))
                        go_to("positioning", now)

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
                    animate_trail=False,
                )
                hud_next_y = draw_player_controlled_hud(screen, small_font, agents, y=top_y)
                draw_network_hud(screen, small_font, connected_players, display_latency_ms, start_y=hud_next_y)

                draw_soft_text_panel(
                    screen,
                    [
                        (font, "Match Setup: Find your character", (45, 45, 45)),
                        (small_font, "NPC are paused. Move slightly to confirm your position.", (48, 48, 48)),
                        (small_font, "Press S when everyone is ready (ESC to menu)", (40, 108, 63)),
                    ],
                    WIDTH // 2,
                    top_y,
                )

                for event in events:
                    if not can_accept_input(now):
                        continue
                    if event.type == pygame.KEYDOWN and event.key in (pygame.K_s, pygame.K_RETURN, pygame.K_SPACE):
                        countdown_start = time.monotonic()
                        go_to("countdown", now)

            elif state == "countdown":
                render_arena(
                    screen,
                    bg_surface,
                    trail_surface,
                    agents,
                    sprites,
                    tag_font,
                    connected_players,
                    animate_trail=True,
                )
                hud_next_y = draw_player_controlled_hud(screen, small_font, agents, y=top_y)
                draw_network_hud(screen, small_font, connected_players, display_latency_ms, start_y=hud_next_y)

                elapsed = time.monotonic() - countdown_start
                remain = max(1, COUNTDOWN_SECONDS - int(elapsed))
                num = title_font.render(str(remain), True, (35, 35, 35))
                screen.blit(num, (WIDTH // 2 - num.get_width() // 2, HEIGHT // 2 - num.get_height() // 2))

                draw_soft_text_block(
                    screen,
                    font,
                    "Get ready! Check your position.",
                    WIDTH // 2,
                    HEIGHT // 2 + 70,
                    text_color=(55, 55, 55),
                    align="center",
                )

                if elapsed >= COUNTDOWN_SECONDS:
                    start_match_clock(time.monotonic())
                    go_to("playing", now)

            elif state == "playing":
                match_elapsed = current_match_elapsed(now)
                speed_scale = speed_scale_for_elapsed(match_elapsed)
                for agent in agents:
                    agent.speed_scale = speed_scale
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
                    animate_trail=True,
                )
                pause_btn = draw_pause_button(screen, small_font, paused=False, top_y=top_y)
                hud_next_y = draw_player_controlled_hud(screen, small_font, agents, y=top_y)
                draw_network_hud(screen, small_font, connected_players, display_latency_ms, start_y=hud_next_y)
                draw_match_timer_hud(screen, small_font, match_elapsed, top_y=top_y)

                for event in events:
                    if not can_accept_input(now):
                        continue
                    if event.type == pygame.MOUSEBUTTONDOWN and pause_btn.collidepoint(mouse_pos):
                        go_pause("playing", now)
                    elif event.type == pygame.KEYDOWN and event.key == pygame.K_p:
                        go_pause("playing", now)

                if len({agent.kind for agent in agents}) == 1:
                    pause_match_clock(time.monotonic())
                    victory_time_seconds = match_elapsed_seconds
                    go_to("game_over", now)

            elif state == "paused":
                render_arena(
                    screen,
                    bg_surface,
                    trail_surface,
                    agents,
                    sprites,
                    tag_font,
                    connected_players,
                    animate_trail=False,
                )
                resume_btn = draw_pause_button(screen, small_font, paused=True, top_y=top_y)
                draw_match_timer_hud(screen, small_font, current_match_elapsed(now), top_y=top_y)

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
                    if not can_accept_input(now):
                        continue
                    if event.type == pygame.MOUSEBUTTONDOWN and resume_btn.collidepoint(mouse_pos):
                        if pause_return_state == "playing":
                            start_match_clock(now)
                        go_to(pause_return_state, now)
                    elif event.type == pygame.KEYDOWN and event.key == pygame.K_p:
                        if pause_return_state == "playing":
                            start_match_clock(now)
                        go_to(pause_return_state, now)

            elif state == "game_over":
                render_arena(
                    screen,
                    bg_surface,
                    trail_surface,
                    agents,
                    sprites,
                    tag_font,
                    connected_players,
                    animate_trail=False,
                )

                overlay = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
                overlay.fill((0, 0, 0, 120))
                screen.blit(overlay, (0, 0))

                winner_kind = agents[0].kind
                winner_color = TEAM_COLORS.get(winner_kind, (255, 255, 255))
                if game_over_started_at is None:
                    game_over_started_at = now
                    victory_confetti = spawn_confetti_once(winner_color)
                anim_t = now - game_over_started_at
                dt = 1.0 / FPS

                glow = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
                pulse = 210 + int(24 * (0.5 + 0.5 * math.sin(anim_t * 3.2)))
                pygame.draw.circle(glow, (*winner_color, 95), (WIDTH // 2, HEIGHT // 2), pulse)
                screen.blit(glow, (0, 0))

                active_confetti = []
                for piece in victory_confetti:
                    life = piece["life"] - dt
                    if life <= 0:
                        continue
                    piece["life"] = life
                    piece["vy"] += 430 * dt
                    piece["x"] += piece["vx"] * dt
                    piece["y"] += piece["vy"] * dt
                    piece["rot"] += piece["spin"] * dt
                    if piece["y"] > HEIGHT + 50:
                        continue
                    active_confetti.append(piece)
                victory_confetti = active_confetti

                panel = pygame.Rect(WIDTH // 2 - 300, HEIGHT // 2 - 155, 600, 310)
                pygame.draw.rect(screen, (255, 255, 255), panel, border_radius=18)
                pygame.draw.rect(screen, winner_color, panel, 4, border_radius=18)

                winner_icon = sprites[winner_kind]
                icon_scale = 0.48 + 0.03 * math.sin(anim_t * 4.0)
                icon = pygame.transform.rotozoom(winner_icon, anim_t * 64.0, icon_scale)
                icon_rect = icon.get_rect(center=(panel.centerx, panel.y + 62))
                screen.blit(icon, icon_rect)

                crown = font.render("VICTORY", True, winner_color)
                screen.blit(crown, (panel.centerx - crown.get_width() // 2, panel.y + 96))

                win_text = title_font.render(f"{winner_kind.upper()} WINS!", True, (32, 38, 50))
                screen.blit(win_text, (panel.centerx - win_text.get_width() // 2, panel.y + 136))

                final_time = victory_time_seconds if victory_time_seconds is not None else 0.0
                time_text = font.render(f"Clear Time: {format_elapsed_mmss(final_time)}", True, (56, 66, 86))
                screen.blit(time_text, (panel.centerx - time_text.get_width() // 2, panel.y + 222))

                info = small_font.render("Press R to replay, ESC to menu", True, (74, 84, 106))
                screen.blit(info, (panel.centerx - info.get_width() // 2, panel.y + 262))

                for piece in victory_confetti:
                    alpha = max(0, min(255, int(255 * min(1.0, piece["life"] / 1.4))))
                    confetti = pygame.Surface((piece["size"], int(piece["size"] * 1.7)), pygame.SRCALPHA)
                    confetti.fill((*piece["color"], alpha))
                    rotated = pygame.transform.rotate(confetti, piece["rot"])
                    rect = rotated.get_rect(center=(int(piece["x"]), int(piece["y"])))
                    screen.blit(rotated, rect)

                for event in events:
                    if not can_accept_input(now):
                        continue
                    if event.type == pygame.KEYDOWN and event.key == pygame.K_r:
                        agents = create_positioning_agents(
                            connected_players,
                            npc_per_type=npc_per_type_for(selected_difficulty),
                        )
                        reset_match_clock()
                        trail_surface.fill((0, 0, 0, 0))
                        go_to("positioning", now)

            if state in {"menu", "rules", "paused", "game_over"}:
                draw_hotkey_bar(screen, tiny_font, shortcut_items_for_state(state), active_key_labels(now))
            if transition_until > now:
                fade_ratio = (transition_until - now) / transition_duration
                fade = pygame.Surface((WIDTH, HEIGHT), pygame.SRCALPHA)
                fade.fill((18, 22, 30, int(170 * max(0.0, min(1.0, fade_ratio)))))
                screen.blit(fade, (0, 0))

            pygame.display.flip()
            clock.tick(FPS)
    finally:
        server.shutdown()
        server.server_close()
        pygame.quit()


if __name__ == "__main__":
    main()
