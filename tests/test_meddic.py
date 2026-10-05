import json
import unittest

import meddic
from meddic import MEDDIC_ELEMENTS, MalformedOutputError, build_call_balance, parse_meddic_response


def element(content="something", status="GREEN", questions=None, flag=""):
    return {"content": content, "flag": flag, "status": status, "follow_up_questions": questions or []}


BALANCED = {"discovery_count": 16, "pitching_count": 2, "other_count": 1, "pitching_examples": ["PRISM connects natively"]}


def reply(overrides=None, wrap=True, call_balance=BALANCED):
    meddic = {name: element() for name in MEDDIC_ELEMENTS}
    meddic.update(overrides or {})
    data = {"meddic": meddic} if wrap else dict(meddic)
    if call_balance is not None:
        data["call_balance"] = call_balance
    return json.dumps(data)


class ParseMeddicTests(unittest.TestCase):
    def test_all_green_is_ready(self):
        result = parse_meddic_response(reply())
        self.assertTrue(result["gate"]["ready"])
        self.assertEqual(result["gate"]["missing"], [])
        self.assertEqual(result["gate"]["metrics_status"], "GREEN")
        self.assertEqual(result["warnings"], [])

    def test_red_metrics_fires_gate_with_questions(self):
        result = parse_meddic_response(reply({
            "Metrics": element("", "RED", ["What does onboarding cost today?"]),
        }))
        gate = result["gate"]
        self.assertFalse(gate["ready"])
        self.assertEqual(gate["metrics_status"], "RED")
        self.assertEqual(gate["missing"], [{
            "element": "Metrics",
            "follow_up_questions": ["What does onboarding cost today?"],
        }])

    def test_yellow_does_not_fire_gate(self):
        result = parse_meddic_response(reply({"Champion": element("maybe Sam", "YELLOW", ["Is Sam selling internally?"])}))
        self.assertTrue(result["gate"]["ready"])
        self.assertEqual(result["meddic"]["Champion"]["follow_up_questions"], ["Is Sam selling internally?"])

    def test_tolerates_code_fences_and_unwrapped_elements(self):
        result = parse_meddic_response("```json\n" + reply(wrap=False) + "\n```")
        self.assertEqual(set(result["meddic"]), set(MEDDIC_ELEMENTS))

    def test_status_is_case_insensitive(self):
        result = parse_meddic_response(reply({"Metrics": element("30 to 20 days", "green")}))
        self.assertEqual(result["meddic"]["Metrics"]["status"], "GREEN")

    def test_invalid_status_falls_back_on_content(self):
        result = parse_meddic_response(reply({
            "Metrics": element("some numbers", "AMBER"),
            "Champion": element("", "maybe"),
        }))
        self.assertEqual(result["meddic"]["Metrics"]["status"], "YELLOW")
        self.assertEqual(result["meddic"]["Champion"]["status"], "RED")
        self.assertEqual(len(result["warnings"]), 2)

    def test_empty_content_cannot_be_green(self):
        result = parse_meddic_response(reply({"Economic Buyer": element("", "GREEN")}))
        self.assertEqual(result["meddic"]["Economic Buyer"]["status"], "RED")
        self.assertFalse(result["gate"]["ready"])

    def test_missing_element_is_red(self):
        data = json.loads(reply())
        del data["meddic"]["Decision Process"]
        result = parse_meddic_response(json.dumps(data))
        self.assertEqual(result["meddic"]["Decision Process"]["status"], "RED")
        self.assertIn("Decision Process", [m["element"] for m in result["gate"]["missing"]])

    def test_green_elements_drop_questions_and_questions_are_capped(self):
        result = parse_meddic_response(reply({
            "Metrics": element("x", "GREEN", ["q"]),
            "Champion": element("y", "YELLOW", ["1", "2", "3", "4"]),
        }))
        self.assertEqual(result["meddic"]["Metrics"]["follow_up_questions"], [])
        self.assertEqual(len(result["meddic"]["Champion"]["follow_up_questions"]), 3)

    def test_malformed_outputs_raise(self):
        for bad in ["", "Sorry, I can't help with that.", "{not json}", "[1, 2]", '{"foo": 1}', None]:
            with self.subTest(bad=bad):
                with self.assertRaises(MalformedOutputError):
                    parse_meddic_response(bad)


class CallBalanceTests(unittest.TestCase):
    def test_balanced_call_is_not_flagged(self):
        balance = parse_meddic_response(reply())["call_balance"]
        self.assertTrue(balance["measured"])
        self.assertEqual((balance["discovery_pct"], balance["pitching_pct"]), (89, 11))
        self.assertFalse(balance["flagged"])
        self.assertEqual(balance["flag"], "")

    def test_pitch_heavy_call_is_flagged(self):
        balance = parse_meddic_response(reply(call_balance={"discovery_count": 3, "pitching_count": 5}))["call_balance"]
        self.assertTrue(balance["flagged"])
        self.assertEqual(balance["flag"], "Discovery looks thin: 62% of the call was pitching.")

    def test_threshold_is_exclusive_and_configurable(self):
        warnings = []
        at_threshold = build_call_balance({"discovery_count": 7, "pitching_count": 3}, warnings)
        self.assertEqual(at_threshold["pitching_pct"], 30)
        self.assertFalse(at_threshold["flagged"])
        self.assertTrue(build_call_balance({"discovery_count": 7, "pitching_count": 3}, warnings, threshold=20)["flagged"])
        self.assertEqual(meddic.PITCH_THRESHOLD_PCT, at_threshold["threshold_pct"])

    def test_no_classified_content_is_not_measured(self):
        balance = parse_meddic_response(reply(call_balance={"discovery_count": 0, "pitching_count": 0}))["call_balance"]
        self.assertFalse(balance["measured"])
        self.assertFalse(balance["flagged"])
        self.assertIn("Not enough", balance["flag"])

    def test_missing_or_bad_balance_does_not_break_meddic(self):
        for bad in [None, "lots", {"discovery_count": "many", "pitching_count": 2}, {"discovery_count": -1, "pitching_count": 2}]:
            with self.subTest(bad=bad):
                result = parse_meddic_response(reply(call_balance=bad))
                self.assertFalse(result["call_balance"]["measured"])
                self.assertTrue(result["warnings"])
                self.assertTrue(result["gate"]["ready"])

    def test_string_counts_and_example_cap(self):
        balance = parse_meddic_response(reply(call_balance={
            "discovery_count": "4", "pitching_count": "4", "pitching_examples": ["a", "b", "c"]}))["call_balance"]
        self.assertEqual(balance["pitching_pct"], 50)
        self.assertEqual(balance["pitching_examples"], ["a", "b"])


if __name__ == "__main__":
    unittest.main()
