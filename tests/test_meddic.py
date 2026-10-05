import json
import unittest

from meddic import MEDDIC_ELEMENTS, MalformedOutputError, parse_meddic_response


def element(content="something", status="GREEN", questions=None, flag=""):
    return {"content": content, "flag": flag, "status": status, "follow_up_questions": questions or []}


def reply(overrides=None, wrap=True):
    meddic = {name: element() for name in MEDDIC_ELEMENTS}
    meddic.update(overrides or {})
    return json.dumps({"meddic": meddic} if wrap else meddic)


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


if __name__ == "__main__":
    unittest.main()
