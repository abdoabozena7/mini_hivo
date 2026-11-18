import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import mini
from scripts.experiment12_fixtures import CASES
from scripts.experiment12_run import authority, check_pin, materialize, preregister


class GeneralizationHarnessTests(unittest.TestCase):
    def test_all_five_public_tasks_have_valid_frozen_scopes_and_test_protection(self):
        with tempfile.TemporaryDirectory() as temporary:
            for case in CASES:
                workspace = Path(temporary) / case["case_id"]
                materialize(case, workspace)
                result = authority(case, workspace)
                self.assertTrue(result["plan_gate"]["valid"])
                self.assertEqual(result["plan"]["approved_change_nodes"][0]["target_paths"], [case["source"]])
                self.assertEqual(result["plan"]["do_not_touch"], [case["test_target"]] if case.get("test_target") else [])
                self.assertEqual(result["plan"]["task_goal"], case["goal"])
                self.assertTrue(result["task_brain_validation"]["valid"])
                self.assertEqual(authority(case,workspace)["execution_contract_hash"],result["execution_contract_hash"])

    def test_modified_seed_or_absent_current_symbol_cannot_become_authority(self):
        with tempfile.TemporaryDirectory() as temporary:
            case = CASES[0]
            workspace = Path(temporary) / "seed"
            materialize(case,workspace)
            (workspace / case["source"]).write_text("missing owner",encoding="utf-8")
            with self.assertRaises(ValueError): authority(case,workspace)

    def test_preregistered_model_budget_and_source_pin_is_enforced(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary) / "suite"
            preregister(root)
            manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(len(manifest["cases"]),5)
            self.assertEqual(manifest["model"],"gemma4:e4b")
            self.assertEqual(manifest["worker_budget"],28)
            check_pin(manifest)
            with patch.object(mini,"MAX_TOOL_STEPS",29):
                with self.assertRaises(ValueError): check_pin(manifest)
            changed=copy.deepcopy(manifest)
            changed["production_sha256"]["mini.py"]="different"
            with self.assertRaises(ValueError): check_pin(changed)


if __name__ == "__main__": unittest.main()
