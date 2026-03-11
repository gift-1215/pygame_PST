import time
import unittest

from game_settings import CONNECTION_STALE_SECONDS, INPUT_STALE_SECONDS, MAX_LATENCY_MS, MAX_PLAYERS
from networking import MobileHub


class MobileHubTest(unittest.TestCase):
    def setUp(self):
        self.hub = MobileHub(MAX_PLAYERS)

    def test_stale_input_is_zeroed_before_disconnect(self):
        ok, player_id, token, _reason = self.hub.join(requested_group="paper")
        self.assertTrue(ok)
        self.assertTrue(self.hub.set_input(token, 1.0, -1.0, rtt_ms=32))

        with self.hub.lock:
            self.hub.last_seen[token] = time.monotonic() - (INPUT_STALE_SECONDS + 0.05)

        inputs, connected, _latency = self.hub.snapshot()
        self.assertIn(player_id, connected)
        self.assertEqual(inputs[player_id], (0.0, 0.0))

    def test_existing_token_can_switch_group(self):
        ok, player_id, token, _reason = self.hub.join(requested_group="scissors")
        self.assertTrue(ok)
        self.assertIn(player_id, self.hub.group_slots["scissors"])

        ok2, new_player_id, same_token, reason2 = self.hub.join(existing_token=token, requested_group="rock")
        self.assertTrue(ok2)
        self.assertEqual(reason2, "switched_group")
        self.assertEqual(same_token, token)
        self.assertIn(new_player_id, self.hub.group_slots["rock"])
        self.assertNotIn(player_id, self.hub.player_to_token)
        self.assertEqual(self.hub.token_to_player[token], new_player_id)

    def test_switch_group_full_keeps_original_slot(self):
        self.assertTrue(self.hub.join(requested_group="rock")[0])
        self.assertTrue(self.hub.join(requested_group="rock")[0])
        ok, player_id, token, _reason = self.hub.join(requested_group="paper")
        self.assertTrue(ok)

        ok2, new_player_id, _new_token, reason2 = self.hub.join(existing_token=token, requested_group="rock")
        self.assertFalse(ok2)
        self.assertEqual(reason2, "group_full")
        self.assertIsNone(new_player_id)
        self.assertEqual(self.hub.token_to_player[token], player_id)

    def test_connection_cleanup_removes_stale_player(self):
        ok, player_id, token, _reason = self.hub.join(requested_group="paper")
        self.assertTrue(ok)
        self.assertTrue(self.hub.set_input(token, 0.4, 0.5))

        with self.hub.lock:
            self.hub.last_seen[token] = time.monotonic() - (CONNECTION_STALE_SECONDS + 0.2)

        inputs, connected, _latency = self.hub.snapshot()
        self.assertNotIn(player_id, connected)
        self.assertEqual(inputs[player_id], (0.0, 0.0))

    def test_high_rtt_disconnects_player_immediately(self):
        ok, player_id, token, _reason = self.hub.join(requested_group="rock")
        self.assertTrue(ok)

        accepted = self.hub.set_input(token, 0.2, 0.1, rtt_ms=MAX_LATENCY_MS + 1)
        self.assertFalse(accepted)
        self.assertNotIn(token, self.hub.token_to_player)
        self.assertNotIn(player_id, self.hub.player_to_token)

        _inputs, connected, _latency = self.hub.snapshot()
        self.assertNotIn(player_id, connected)

    def test_snapshot_disconnects_when_total_latency_exceeds_threshold(self):
        ok, player_id, token, _reason = self.hub.join(requested_group="scissors")
        self.assertTrue(ok)
        self.assertTrue(self.hub.set_input(token, 0.1, 0.2, rtt_ms=20))

        with self.hub.lock:
            self.hub.last_seen[token] = time.monotonic() - ((MAX_LATENCY_MS + 50) / 1000.0)

        _inputs, connected, latency = self.hub.snapshot()
        self.assertNotIn(player_id, connected)
        self.assertNotIn(player_id, latency)
        self.assertNotIn(token, self.hub.token_to_player)
        self.assertNotIn(player_id, self.hub.player_to_token)


if __name__ == "__main__":
    unittest.main()
