import unittest

from dcp import broll, captions, hook, slate

PARAS = [
    ("Title", "Josh Hokit episode: gated slate of 14 clips"),
    ("", "Source: Double Coverage x Josh Hokit, episode Je8zVbMAd00. Fight is November 14."),
    ("Heading 2", "5. If size won, the elephant would be king"),
    ("", 'HOOK to PAYOFF: He is a middleweight, to "the elephant would be king of the jungle."'),
    ("", 'Source: 4:44-4:56 + 5:21-5:32 (23 s). Start "It\'s like these guys are lazy".'),
    ("", "Hook box: Josh Hokit says size doesn't win fights. Then he said this \U0001F418"),
    ("", "B-roll (Triple Hook): Elephant (snapback), then Hokit vs larger men (Blades, Lewis)."),
    ("", "Weak spot: Two-part cut."),
    ("Heading 2", "Left out on purpose"),
    ("", "Source: 9:99-9:99 should be ignored"),
]


class SlateTest(unittest.TestCase):
    def test_clip(self):
        s = slate.parse_paragraphs(PARAS)
        self.assertEqual(s["episode"], "Je8zVbMAd00")
        self.assertEqual(slate.guest_name(s["title"]), "Hokit")
        self.assertEqual(len(s["clips"]), 1)
        c = s["clips"][0]
        self.assertEqual(c["segments"], [[284, 296], [321, 332]])
        self.assertEqual(c["start_phrase"], "It's like these guys are lazy")
        self.assertEqual(c["payoff"], "the elephant would be king of the jungle")
        self.assertEqual(c["emoji"], "\U0001F418")
        self.assertTrue(c["hook_text"].endswith("said this"))
        self.assertEqual([b["match"] for b in c["broll"]], ["Elephant", "Hokit vs larger men"])

    def test_broll_forms(self):
        items, notes = slate.parse_broll(
            "Official Hokit vs Blades footage: bloody exchanges, final bell. No text shots.")
        self.assertEqual([i["search"] for i in items],
                         ["Hokit vs Blades bloody exchanges", "Hokit vs Blades final bell"])
        self.assertEqual(notes, "No text shots")
        items, _ = slate.parse_broll("Pereira KO highlights (snapback: the feared striker), Hokit takedowns.")
        self.assertEqual(items[0]["match"], "Pereira KO highlights")
        items, _ = slate.parse_broll("Floyd belts Ck_l3DOg9iQ 0:56-1:05; Lamborghini")
        self.assertEqual(items[0]["fixed"], {"vid": "Ck_l3DOg9iQ", "t": 56, "t_end": 65})
        self.assertIsNone(items[1]["fixed"])


class TimelineTest(unittest.TestCase):
    def test_shots_land_on_words(self):
        items = [{"match": "Hokit walkout", "hint": ""}, {"match": "MSG exterior", "hint": ""},
                 {"match": "belt close-up", "hint": ""}]
        toks = [["the", 0.1, 0.3], ["belt", 3.0, 3.4], ["imagine", 4.0, 4.4], ["reading", 9.0, 9.4],
                ["at", 11.5, 11.7], ["MSG", 12.0, 12.5]]
        slots = broll.build_timeline(items, toks, 14.0)
        self.assertEqual(slots[0]["start"], 0.0)
        self.assertEqual(slots[-1]["end"], 14.0)
        for a, b in zip(slots[:-1], slots[1:]):
            self.assertAlmostEqual(a["end"], b["start"])
        belt = next(s for s in slots if s["word"] == "belt")
        self.assertEqual(belt["item"], 2)
        self.assertAlmostEqual(belt["start"], 2.85)
        self.assertEqual(next(s for s in slots if s["word"] == "msg")["item"], 1)

    def test_word_matching(self):
        self.assertTrue(broll.same_word("lambo", "lamborghini"))
        self.assertTrue(broll.same_word("belts", "belt"))
        self.assertFalse(broll.same_word("gane", "game"))


class CaptionTest(unittest.TestCase):
    def test_fixes_and_mask(self):
        toks = [["Sir", 0, 0.2], ["Gone", 0.2, 0.5], ["is", 0.5, 0.6], ["fucking", 0.6, 1.0]]
        out = captions.apply_fixes(toks, captions.parse_fixes("sir gone = Gane"))
        self.assertEqual(out[0], ["Gane", 0, 0.5])
        self.assertEqual(captions.display("fucking", ["fuck"]), "f**king")
        self.assertEqual(captions.display("Gane,", ["fuck"]), "gane")
        self.assertEqual(len(captions.bleeps(out, ["fuck"])), 1)

    def test_hook_wrap(self):
        self.assertEqual(hook.wrap("Josh Hokit's plan if he wins the belt at MSG"),
                         ["Josh Hokit's plan if", "he wins the belt at MSG"])


if __name__ == "__main__":
    unittest.main()
