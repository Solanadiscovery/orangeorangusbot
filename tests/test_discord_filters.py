"""Test offline delle regole di moderazione del bot Discord."""
import json, sys, unittest
from pathlib import Path

DIR = Path(__file__).resolve().parent.parent / "discord_bot"
sys.path.insert(0, str(DIR))
import filters

CFG = json.loads((DIR / "config.json").read_text(encoding="utf-8"))


class FiltersTest(unittest.TestCase):
    def test_scam_patterns(self):
        self.assertTrue(filters.check("Claim your AIRDROP now", 0, False, CFG)[0].startswith("possibile truffa"))
        self.assertIsNotNone(filters.scam_match("join discord.gg/abc", CFG["scam_patterns"]))
        self.assertIsNone(filters.check("adoro le arance", 0, False, CFG))

    def test_mentions_timeout(self):
        self.assertEqual(filters.check("ciao", 5, False, CFG), ("spam di menzioni (5)", True))

    def test_links_only_in_community(self):
        self.assertIsNone(filters.check("guarda https://example.com", 0, False, CFG))
        self.assertEqual(filters.check("guarda https://example.com", 0, True, CFG)[1], False)
        self.assertIsNone(filters.bad_link("https://sub.ok.io/x", ["ok.io"]))

    def test_caps(self):
        self.assertTrue(filters.too_many_caps("QUESTO È TUTTO MAIUSCOLO", 0.7, 10))
        self.assertFalse(filters.too_many_caps("CIAO", 0.7, 10))

    def test_tracker(self):
        now = [0.0]
        t = filters.Tracker(5, 5, 3, clock=lambda: now[0])
        self.assertEqual([t.add(1, f"m{i}") for i in range(5)][-1], "flood")
        now[0] = 100
        self.assertEqual([t.add(2, "uguale") for _ in range(3)][-1], "duplicati")
        self.assertIsNone(t.add(3, "uno"))


if __name__ == "__main__":
    unittest.main()
