import json
import unittest

from meddic import MalformedOutputError
from prescription import parse_prescription_response

AGENDA = ["Acknowledge attribution chaos", "Connect HubSpot live", "Trace multi-touch journey", "Show ROI dashboard"]


def reply(agenda=AGENDA, steps=None, **extra):
    steps = steps if steps is not None else [{"step": a, "points": [f"Show {a}.", "Tie it to the pain."]} for a in agenda]
    data = {"deal_overview": ["Mid-market SaaS, $2.4M paid spend.", "CFO signs."], "demo_agenda": agenda, "demo_prescription": steps,
            "market_context": ["Competitor A", "Competitor B", "Competitor C"]}
    data.update(extra)
    return json.dumps(data)


class ParsePrescriptionTests(unittest.TestCase):
    def test_valid_agenda_matches_steps(self):
        result = parse_prescription_response(reply())
        self.assertEqual(result["demo_agenda"], AGENDA)
        self.assertEqual([s["step"] for s in result["demo_prescription"]], AGENDA)
        self.assertEqual(result["warnings"], [])

    def test_step_labels_relabelled_to_agenda_by_position(self):
        steps = [{"step": a.upper() if i == 1 else "Something else" if i == 2 else a, "points": ["x"]}
                 for i, a in enumerate(AGENDA)]
        result = parse_prescription_response(reply(steps=steps))
        self.assertEqual([s["step"] for s in result["demo_prescription"]], AGENDA)
        # Case-only difference is not a warning; a different label is.
        self.assertEqual(len(result["warnings"]), 1)

    def test_count_mismatch_rebuilds_agenda_from_steps(self):
        steps = [{"step": a, "points": ["x"]} for a in AGENDA]
        result = parse_prescription_response(reply(agenda=AGENDA[:2], steps=steps))
        self.assertEqual(result["demo_agenda"], AGENDA)
        self.assertTrue(any("rebuilt" in w for w in result["warnings"]))

    def test_missing_agenda_is_built_from_steps(self):
        data = json.loads(reply())
        del data["demo_agenda"]
        result = parse_prescription_response(json.dumps(data))
        self.assertEqual(result["demo_agenda"], AGENDA)

    def test_agenda_shape_warnings(self):
        agenda = ["Intro", "Connect HubSpot live", "Trace the full multi touch customer journey end to end"]
        result = parse_prescription_response(reply(agenda=agenda))
        warnings = " ".join(result["warnings"])
        self.assertIn("3 steps", warnings)
        self.assertIn("'Intro' is 1 words", warnings)
        self.assertIn("is 10 words", warnings)

    def test_malformed_prescription_raises(self):
        for steps in ["A paragraph instead of steps", [], [{"detail": "no label"}]]:
            with self.subTest(steps=steps):
                with self.assertRaises(MalformedOutputError):
                    parse_prescription_response(reply(steps=steps))

    def test_bullets_pass_through(self):
        result = parse_prescription_response(reply())
        self.assertEqual(result["deal_overview"], ["Mid-market SaaS, $2.4M paid spend.", "CFO signs."])
        self.assertEqual(result["demo_prescription"][0]["points"], ["Show Acknowledge attribution chaos.", "Tie it to the pain."])

    def test_prose_is_split_into_sentence_bullets(self):
        steps = [{"step": a, "detail": "First point. Second point? Third!"} for a in AGENDA]
        result = parse_prescription_response(reply(steps=steps, deal_overview="Deal one. Deal two."))
        self.assertEqual(result["deal_overview"], ["Deal one.", "Deal two."])
        self.assertEqual(result["demo_prescription"][0]["points"], ["First point.", "Second point?", "Third!"])
        self.assertTrue(any("came back as prose" in w for w in result["warnings"]))

    def test_long_bullet_warns(self):
        result = parse_prescription_response(reply(deal_overview=["word " * 31]))
        self.assertTrue(any("31-word bullet" in w for w in result["warnings"]))


if __name__ == "__main__":
    unittest.main()
