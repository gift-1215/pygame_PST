# pygames - RPS Mobile Local

Local multiplayer Rock-Paper-Scissors battle using `pygame` + phone joystick over local network.

## Run

```bash
pip3 install -r requirements.txt
python3 main.py
```

## Play

1. Open the game on your computer. The game starts on the rules page.
2. Press `GO TO MENU` to enter lobby.
3. Scan the QR code (or open the displayed URL) from phones on the same Wi-Fi.
4. Press `START` in game window.

## Controls

- `ENTER`: open match setup from menu / test
- `SPACE` / `ENTER`: go from rules page to menu
- `S`: start 3-second countdown from match setup
- `T`: open control test area
- `P`: pause / resume during test or game
- `R`: replay from game-over
- `ESC`: back to menu
- `F1`: open rules page from menu

## Files

- `main.py`: primary entrypoint
- `game_app.py`: game state machine and main loop
- `game_settings.py`: configuration and shared constants
- `agents.py`: agent behavior and spawning
- `visuals.py`: rendering and menu/HUD drawing
- `networking.py`: mobile control server and connection hub
- `rules_page.py`: rules page UI
- `controller.html`: mobile joystick page
- `requirements.txt`: dependencies
