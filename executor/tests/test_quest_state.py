"""Smoke tests for quest_state — uses chain reads against bpeon's known state.

These assertions match the state observed in session 70 (2026-04-30):
- Q48 ("Pipe Dream") completed
- Q49 ("Community Service") owned but blocked on objs_not_met
- Q50 ("You Smelt It…") not yet accepted (gated behind Q49)

Run from the executor/ directory:
    .venv/bin/python -m unittest tests.test_quest_state
"""

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import server  # noqa: E402


class TestQuestState(unittest.TestCase):
    ACCOUNT = "bpeon"

    @classmethod
    def setUpClass(cls):
        # Skip the whole class if the snapshot account isn't loaded — these
        # tests are state-snapshots against bpeon's chain state from session 70.
        try:
            server._get_account(cls.ACCOUNT)
        except Exception as e:
            raise unittest.SkipTest(f"{cls.ACCOUNT} not configured: {e}")

    def test_q48_completed(self):
        r = server.quest_state(48, account=self.ACCOUNT)
        self.assertEqual(r["state"], "completed")
        self.assertTrue(r["completed"])
        self.assertTrue(r["owned"])

    def test_q49_active_blocked_objs_not_met(self):
        r = server.quest_state(49, account=self.ACCOUNT)
        self.assertEqual(r["state"], "active_blocked")
        self.assertTrue(r["owned"])
        self.assertFalse(r["completed"])
        self.assertEqual(r["revert_kind"], "objs_not_met")

    def test_q50_not_accepted(self):
        r = server.quest_state(50, account=self.ACCOUNT)
        self.assertEqual(r["state"], "not_accepted")
        self.assertFalse(r["owned"])
        self.assertFalse(r["completed"])
        self.assertEqual(r["revert_kind"], "not_active")


if __name__ == "__main__":
    unittest.main()
