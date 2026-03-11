import unittest

from agents import create_agents
from game_settings import EASY_NPC_PER_TYPE, EASY_TOTAL_PER_TEAM, NPC_PER_TYPE


class DifficultySpawnTest(unittest.TestCase):
    def test_easy_mode_has_five_agents_per_team(self):
        agents = create_agents([], npc_per_type=EASY_NPC_PER_TYPE)
        counts = {}
        for agent in agents:
            counts[agent.kind] = counts.get(agent.kind, 0) + 1

        self.assertEqual(counts.get("rock"), EASY_TOTAL_PER_TEAM)
        self.assertEqual(counts.get("paper"), EASY_TOTAL_PER_TEAM)
        self.assertEqual(counts.get("scissors"), EASY_TOTAL_PER_TEAM)

    def test_hard_mode_keeps_current_density(self):
        agents = create_agents([], npc_per_type=NPC_PER_TYPE)
        counts = {}
        for agent in agents:
            counts[agent.kind] = counts.get(agent.kind, 0) + 1

        expected_per_team = NPC_PER_TYPE + 2
        self.assertEqual(counts.get("rock"), expected_per_team)
        self.assertEqual(counts.get("paper"), expected_per_team)
        self.assertEqual(counts.get("scissors"), expected_per_team)


if __name__ == "__main__":
    unittest.main()
