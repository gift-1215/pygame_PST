# pygames - RPS Mobile Local

Local multiplayer Rock-Paper-Scissors battle using `pygame` + phone joystick over local network.

## Run

```bash
pip3 install -r requirements.txt
python3 simulation.py
```

## Play

1. Open the game on your computer.
2. Scan the QR code (or open the displayed URL) from phones on the same Wi-Fi.
3. Press `START` in game window.

## Controls

- `ENTER`: open match setup from menu / test
- `S`: start 3-second countdown from match setup
- `T`: open 10-second control test area
- `P`: pause / resume during test or game
- `R`: replay from game-over
- `ESC`: back to menu

## Files

- `simulation.py`: game loop + local HTTP controller server
- `controller.html`: mobile joystick page
- `requirements.txt`: dependencies
