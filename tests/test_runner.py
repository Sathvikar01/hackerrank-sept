import unittest

from orchestrator.protocol import parse_json_response, validate_plan
from orchestrator.runner import _system_instruction, dispatch_groups, validate_final


class RunnerTests(unittest.TestCase):
    def test_validator_rejects_unverified_model_reference(self):
        with self.assertRaises(ValueError):
            validate_plan({"subtasks": [{
                "id": "one", "model": "missing", "role": "review",
                "instruction": "inspect the supplied input", "independent_group": "a",
                "depends_on": [],
            }]}, [{"exact_id": "verified", "verified": True}])

    def test_independent_group_dispatches_concurrently_and_collects_results(self):
        calls = []

        def specialist(subtask):
            calls.append(subtask["id"])
            return {"id": subtask["id"], "status": "ok"}

        result = dispatch_groups([
            {"id": "a", "independent_group": "parallel", "depends_on": []},
            {"id": "b", "independent_group": "parallel", "depends_on": []},
        ], specialist)
        self.assertEqual({item["id"] for item in result}, {"a", "b"})
        self.assertEqual(set(calls), {"a", "b"})

    def test_parser_accepts_fenced_json_without_executing_embedded_text(self):
        self.assertEqual(
            parse_json_response("```json\n{\"needs_iteration\": false}\n```"),
            {"needs_iteration": False},
        )

    def test_system_instruction_exposes_only_verified_exact_ids(self):
        instruction = _system_instruction([
            {"model": "Gemini 3.8 Flash", "exact_id": "free/gemini-3.8-flash", "verified": True, "role": "orchestration"},
            {"model": "GPT-5.6 Luna", "exact_id": "free/gpt-5.6-luna", "verified": True, "role": "independent evaluation"},
            {"model": "DeepSeek V4.1 Flash", "exact_id": "opencode-go/deepseek-v4.1-flash", "verified": False, "role": "implementation, debugging, tests"},
        ])
        self.assertIn("free/gpt-5.6-luna", instruction)
        self.assertNotIn("free/gemini-3.8-flash", instruction)
        self.assertNotIn("opencode-go/deepseek-v4.1-flash", instruction)

    def test_validator_rejects_orchestrator_model_as_specialist(self):
        with self.assertRaises(ValueError):
            validate_plan({"subtasks": [{
                "id": "one", "model": "free/gemini", "role": "orchestration",
                "instruction": "inspect the supplied input", "independent_group": "a",
                "depends_on": [],
            }]}, [{"exact_id": "free/gemini", "verified": True, "role": "orchestration", "model": "Gemini 3.8 Flash"}])

    def test_final_result_requires_a_real_keep_modify_or_rollback_decision(self):
        with self.assertRaises(ValueError):
            validate_final({"status": "complete", "summary": "done"})


if __name__ == "__main__":
    unittest.main()
