import json
import unittest

from meddic import MEDDIC_ELEMENTS, MalformedOutputError
from prescription import parse_prescription_response
from refine import build_ready_check, clean_history, parse_refine_response, refine_system_prompt, rule_gaps
from tests.test_prescription import AGENDA, reply as prescription_reply


def current_plan():
    return parse_prescription_response(prescription_reply())


def meddic(red=()):
    return {name: {"content": "" if name in red else "x", "flag": "",
                   "status": "RED" if name in red else "GREEN",
                   "follow_up_questions": ["What is the baseline today?"] if name in red else []}
            for name in MEDDIC_ELEMENTS}


class RefineMergeTests(unittest.TestCase):
    def test_question_only_leaves_plan_unchanged(self):
        result = parse_refine_response(json.dumps({"reply": "Lead with HubSpot.", "changes": None}), current_plan())
        self.assertEqual(result["reply"], "Lead with HubSpot.")
        self.assertEqual(result["changed_steps"], [])
        self.assertEqual(result["prescription"]["demo_prescription"], current_plan()["demo_prescription"])

    def test_changed_step_is_merged_and_others_kept(self):
        raw = json.dumps({"reply": "Done.", "changes": {"changed_steps": [
            {"step": "connect hubspot live", "points": ["Show SOC 2 report first.", "Then connect HubSpot."]}]}})
        result = parse_refine_response(raw, current_plan())
        steps = result["prescription"]["demo_prescription"]
        self.assertEqual([s["step"] for s in steps], AGENDA)
        self.assertEqual(steps[1]["points"], ["Show SOC 2 report first.", "Then connect HubSpot."])
        self.assertEqual(steps[0]["points"], current_plan()["demo_prescription"][0]["points"])
        self.assertEqual(result["changed_steps"], ["Connect HubSpot live"])

    def test_reordered_and_new_agenda(self):
        agenda = ["Show ROI dashboard", "Acknowledge attribution chaos", "Connect HubSpot live",
                  "Trace multi-touch journey", "Security review walkthrough"]
        raw = json.dumps({"reply": "Reordered.", "changes": {"demo_agenda": agenda, "changed_steps": [
            {"step": "Security review walkthrough", "points": ["Walk through SOC 2 controls."]}]}})
        result = parse_refine_response(raw, current_plan())
        plan = result["prescription"]
        self.assertEqual(plan["demo_agenda"], agenda)
        self.assertEqual([s["step"] for s in plan["demo_prescription"]], agenda)
        self.assertEqual(plan["demo_prescription"][0]["points"], current_plan()["demo_prescription"][3]["points"])
        self.assertEqual(result["changed_steps"], ["Security review walkthrough"])

    def test_new_step_without_detail_warns(self):
        agenda = AGENDA + ["Mystery new step"]
        result = parse_refine_response(json.dumps({"reply": "Added.", "changes": {"demo_agenda": agenda}}), current_plan())
        self.assertEqual(result["prescription"]["demo_prescription"][-1]["points"], [])
        self.assertTrue(any("without any detail" in w for w in result["warnings"]))

    def test_changed_step_not_on_agenda_is_ignored(self):
        raw = json.dumps({"reply": "x", "changes": {"changed_steps": [{"step": "Not a step", "points": ["a"]}]}})
        result = parse_refine_response(raw, current_plan())
        self.assertEqual(result["changed_steps"], [])
        self.assertTrue(any("not on the agenda" in w for w in result["warnings"]))

    def test_deal_overview_replacement(self):
        raw = json.dumps({"reply": "x", "changes": {"deal_overview": ["New overview."]}})
        self.assertEqual(parse_refine_response(raw, current_plan())["prescription"]["deal_overview"], ["New overview."])

    def test_malformed_refine_replies_raise(self):
        for bad in ["no json here", json.dumps({"reply": "", "changes": None}), json.dumps({"reply": "x", "changes": "lots"}),
                    json.dumps({"reply": "x", "changes": {"changed_steps": [{"points": ["a"]}]}})]:
            with self.subTest(bad=bad):
                with self.assertRaises(MalformedOutputError):
                    parse_refine_response(bad, current_plan())

    def test_system_prompt_includes_context(self):
        prompt = refine_system_prompt(meddic(), {"pitching_pct": 10}, current_plan())
        self.assertIn("Connect HubSpot live", prompt)
        self.assertIn('"pitching_pct": 10', prompt)
        self.assertNotIn('"warnings"', prompt)


class HistoryTests(unittest.TestCase):
    def test_trims_and_starts_with_user(self):
        msgs = [{"role": "user" if i % 2 == 0 else "assistant", "content": f"m{i}"} for i in range(13)]
        turns = clean_history(msgs)
        self.assertLessEqual(len(turns), 10)
        self.assertEqual(turns[0]["role"], "user")
        self.assertEqual(turns[-1]["content"], "m12")

    def test_rejects_bad_history(self):
        for bad in [None, [], [{"role": "assistant", "content": "hi"}], [{"role": "system", "content": "x"}]]:
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    clean_history(bad)


class ReadyCheckTests(unittest.TestCase):
    def test_red_element_is_a_blocker_from_rules(self):
        gaps = rule_gaps(meddic(red=["Metrics"]), current_plan())
        self.assertEqual(gaps[0]["severity"], "blocker")
        self.assertEqual(gaps[0]["area"], "Metrics")
        self.assertIn("What is the baseline today?", gaps[0]["fix"])

    def test_ready_when_only_risks(self):
        review = json.dumps({"gaps": [{"severity": "risk", "area": "Show ROI dashboard", "issue": "No numbers.", "fix": "Use $2.4M."}]})
        check = build_ready_check(meddic(), current_plan(), review)
        self.assertTrue(check["ready"])
        self.assertEqual(len(check["gaps"]), 1)

    def test_model_blocker_makes_not_ready_and_blockers_sort_first(self):
        review = json.dumps({"gaps": [
            {"severity": "risk", "area": "Agenda", "issue": "Long.", "fix": "Trim."},
            {"severity": "BLOCKER", "area": "Economic Buyer", "issue": "CFO priorities ignored.", "fix": "Add payback."}]})
        check = build_ready_check(meddic(), current_plan(), review)
        self.assertFalse(check["ready"])
        self.assertEqual(check["gaps"][0]["severity"], "blocker")

    def test_model_gap_duplicating_rule_gap_is_dropped(self):
        review = json.dumps({"gaps": [{"severity": "blocker", "area": "Metrics", "issue": "No metrics.", "fix": "Ask."}]})
        check = build_ready_check(meddic(red=["Metrics"]), current_plan(), review)
        self.assertEqual([g["area"] for g in check["gaps"]], ["Metrics"])

    def test_unreadable_review_falls_back_to_rules(self):
        check = build_ready_check(meddic(red=["Champion"]), current_plan(), "")
        self.assertFalse(check["ready"])
        self.assertTrue(check["warnings"])


if __name__ == "__main__":
    unittest.main()
