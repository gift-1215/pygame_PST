import time
import unittest

from agents import Agent
from game_settings import AGENT_RADIUS, CONVERSION_GRACE_SECONDS


class ConversionGraceTest(unittest.TestCase):
    def _colliding_pair(self, left_kind, right_kind):
        ax, ay = 200, 200
        bx, by = 200 + int(AGENT_RADIUS * 1.5), 200
        left = Agent(ax, ay, left_kind)
        right = Agent(bx, by, right_kind)
        return left, right

    def test_recently_converted_agent_cannot_be_converted(self):
        rock, paper = self._colliding_pair("rock", "paper")
        rock.convert_lock_until = time.monotonic() + CONVERSION_GRACE_SECONDS

        rock.collide_and_convert([rock, paper])
        self.assertEqual(rock.kind, "rock")

    def test_recently_converted_agent_cannot_convert_others(self):
        scissors, rock = self._colliding_pair("scissors", "rock")
        rock.convert_lock_until = time.monotonic() + CONVERSION_GRACE_SECONDS

        scissors.collide_and_convert([scissors, rock])
        self.assertEqual(scissors.kind, "scissors")

    def test_conversion_applies_lock(self):
        scissors, rock = self._colliding_pair("scissors", "rock")

        before = time.monotonic()
        scissors.collide_and_convert([scissors, rock])
        after = time.monotonic()

        self.assertEqual(scissors.kind, "rock")
        self.assertGreaterEqual(scissors.convert_lock_until, before)
        self.assertLessEqual(scissors.convert_lock_until, after + CONVERSION_GRACE_SECONDS + 0.05)

    def test_lock_expired_allows_conversion(self):
        rock, paper = self._colliding_pair("rock", "paper")
        rock.convert_lock_until = time.monotonic() - 0.01

        rock.collide_and_convert([rock, paper])
        self.assertEqual(rock.kind, "paper")


if __name__ == "__main__":
    unittest.main()
