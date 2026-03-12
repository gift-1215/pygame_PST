import pygame

from game_settings import WIDTH, HEIGHT


def draw_rules_page(screen, bg_surface, title_font, font, small_font, button_font, pressed_buttons=None):
    pressed_buttons = pressed_buttons or set()
    screen.blit(bg_surface, (0, 0))

    title = title_font.render("GAME RULES", True, (31, 36, 46))
    screen.blit(title, (WIDTH // 2 - title.get_width() // 2, 44))

    panel = pygame.Rect(WIDTH // 2 - 500, 128, 1000, 490)
    pygame.draw.rect(screen, (255, 255, 255), panel, border_radius=16)
    pygame.draw.rect(screen, (210, 218, 232), panel, 1, border_radius=16)

    sub = font.render("How to play", True, (53, 62, 78))
    screen.blit(sub, (panel.x + 24, panel.y + 22))

    lines = [
        "1. Three factions: Scissors, Rock, Paper.",
        "2. Scissors beats Paper, Paper beats Rock, Rock beats Scissors.",
        "3. Each team has 2 player slots. Empty slots are AI-controlled.",
        "4. Scan team QR in menu, then control movement on your phone.",
        "5. In match setup, NPCs pause so players can find their character.",
        "6. Press S to begin 3-second countdown and start the battle.",
        "7. Match timer appears at top-right during battle.",
        "8. After 30s, base speed ramps up every 5s.",
        "9. Match ends when all agents become the same type.",
    ]

    y = panel.y + 72
    for text in lines:
        item = small_font.render(text, True, (58, 67, 82))
        screen.blit(item, (panel.x + 24, y))
        y += 38

    tips = small_font.render("Game over controls: R replay, ESC back to menu.", True, (93, 102, 118))
    screen.blit(tips, (panel.x + 24, panel.bottom - 36))

    go_menu_btn = pygame.Rect(WIDTH // 2 - 200, HEIGHT - 120, 400, 66)
    go_menu_pressed = "rules_go_menu" in pressed_buttons
    go_menu_draw = go_menu_btn.move(0, 2 if go_menu_pressed else 0)
    pygame.draw.rect(screen, (26, 157, 86) if go_menu_pressed else (38, 178, 96), go_menu_draw, border_radius=12)
    label = button_font.render("GO TO MENU", True, (236, 255, 241) if go_menu_pressed else (255, 255, 255))
    screen.blit(label, (go_menu_draw.centerx - label.get_width() // 2, go_menu_draw.centery - label.get_height() // 2))

    fs_hint = small_font.render("F: Toggle Fullscreen", True, (98, 104, 118))
    screen.blit(fs_hint, (WIDTH - fs_hint.get_width() - 22, HEIGHT - 72))

    return go_menu_draw
