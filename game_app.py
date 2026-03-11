import time

import pygame

from agents import create_positioning_agents, create_test_agents
from game_settings import (
    COUNTDOWN_SECONDS,
    FPS,
    MAX_PLAYERS,
    QR_MISSING_MSG,
    SERVER_HOST,
    SERVER_PORT,
    START_FULLSCREEN,
    TEAM_TYPES,
    TEST_SECONDS,
    WIDTH,
    HEIGHT,
)
from networking import MobileHub, get_local_ip, load_controller_html, start_server
from visuals import (
    build_background_surface,
    build_qr_surface,
    build_sprites,
    build_team_preview_surfaces,
    draw_menu,
    draw_network_hud,
    draw_pause_button,
    draw_player_controlled_hud,
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
