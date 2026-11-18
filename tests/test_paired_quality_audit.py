import copy
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import unittest
from uuid import uuid4


ROOT = Path(__file__).resolve().parents[1]
CLI = ROOT / "scripts" / "paired_quality_audit.py"
READY = b"READY\n"


class PairedQualityAuditTests(unittest.TestCase):
    def setUp(self):
        self.directory = ROOT / ".runtime-proof" / f"paired-audit-test-{uuid4().hex}"
        self.directory.mkdir(parents=True)
        self.addCleanup(shutil.rmtree, self.directory)
        limits = {"max_model_calls": 5, "max_tool_calls": 12, "max_elapsed_seconds": 18}
        self.protocol = {
            "schema": 1,
            "evidence_mode": "fixture",
            "tool_authority": "same-readonly-oracle-v1",
            "arms": [{"id": arm, "limits": dict(limits)} for arm in ("reference", "candidate")],
            "cases": [
                {"id": case, "oracle_id": "exact-ready-bytes-v1"}
                for case in ("ordinary", "incorrect", "gain", "approval", "deadline",
                             "unrecorded", "never-started")
            ],
        }

    def _files(self, records, protocol=None):
        protocol_path = self.directory / "protocol.json"
        result_path = self.directory / "results.json"
        raw = json.dumps(self.protocol if protocol is None else protocol, indent=2).encode("utf-8")
        protocol_path.write_bytes(raw)
        result_path.write_text(json.dumps({
            "schema": 1,
            "protocol_sha256": hashlib.sha256(raw).hexdigest(),
            "records": records,
        }), encoding="utf-8")
        return protocol_path, result_path

    def _run(self, paths):
        return subprocess.run(
            [sys.executable, "-B", str(CLI), *map(str, paths)],
            cwd=ROOT, capture_output=True, encoding="utf-8", timeout=10,
        )

    def _report(self, records, protocol=None):
        paths = self._files(records, protocol)
        inputs = [path.read_bytes() for path in paths]
        run = self._run(paths)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertEqual(run.stderr, "")
        self.assertEqual([path.read_bytes() for path in paths], inputs)
        report = json.loads(run.stdout)
        self.assertEqual(report["protocol_sha256"], hashlib.sha256(inputs[0]).hexdigest())
        self.assertEqual(report["results_sha256"], hashlib.sha256(inputs[1]).hexdigest())
        return report

    def _rejected(self, reason, *, records=(), protocol=None, paths=None):
        run = self._run(paths or self._files(list(records), protocol))
        self.assertEqual(run.returncode, 2, run.stderr)
        self.assertEqual(run.stdout, "")
        self.assertIn(reason, run.stderr)

    def _external_verdict(self, arm, case, artifact_bytes):
        artifact = self.directory / f"{arm}-{case}.txt"
        artifact.write_bytes(artifact_bytes)
        return {
            "arm_id": arm,
            "case_id": case,
            "outcome": "pass" if artifact.read_bytes() == READY else "fail",
            "oracle_id": "exact-ready-bytes-v1",
            "evidence_id": artifact.name,
            "controller_status": "done",
        }

    def test_external_reference_and_flawed_artifacts_keep_full_denominator(self):
        records = [
            self._external_verdict("reference", "ordinary", READY),
            self._external_verdict("reference", "incorrect", READY),
            self._external_verdict("reference", "gain", b"BROKEN\n"),
            self._external_verdict("reference", "approval", READY),
            self._external_verdict("reference", "deadline", READY),
            self._external_verdict("reference", "unrecorded", READY),
            self._external_verdict("candidate", "ordinary", READY),
            self._external_verdict("candidate", "incorrect", b"READY\nextra\n"),
            self._external_verdict("candidate", "gain", READY),
            {"arm_id": "candidate", "case_id": "approval", "outcome": "blocked",
             "evidence_id": "fixture-approval-denial"},
            {"arm_id": "candidate", "case_id": "deadline", "outcome": "timeout",
             "evidence_id": "fixture-deadline"},
        ]
        report = self._report(list(reversed(records)))
        self.assertEqual(report["evidence_mode"], "fixture")
        self.assertEqual(report["planned_cases"], 7)
        self.assertEqual([row["case_id"] for row in report["cases"]],
                         ["ordinary", "incorrect", "gain", "approval", "deadline",
                          "unrecorded", "never-started"])
        self.assertEqual(report["cases"][1]["outcomes"], {
            "reference": {"outcome": "pass", "evidence_id": "reference-incorrect.txt"},
            "candidate": {"outcome": "fail", "evidence_id": "candidate-incorrect.txt"},
        })
        self.assertEqual(report["cases"][-1]["outcomes"], {
            "reference": {"outcome": "missing", "evidence_id": None},
            "candidate": {"outcome": "missing", "evidence_id": None},
        })
        self.assertEqual(report["arms"]["reference"]["counts"],
                         {"pass": 5, "fail": 1, "blocked": 0, "timeout": 0, "missing": 1})
        candidate = report["arms"]["candidate"]
        self.assertEqual(candidate["counts"],
                         {"pass": 2, "fail": 1, "blocked": 1, "timeout": 1, "missing": 2})
        self.assertEqual(candidate["case_ids_by_outcome"], {
            "pass": ["ordinary", "gain"], "fail": ["incorrect"], "blocked": ["approval"],
            "timeout": ["deadline"], "missing": ["unrecorded", "never-started"],
        })
        self.assertEqual(candidate["pass_rate"], 2 / 7)
        self.assertEqual(report["pairs"], [{
            "left_arm": "reference", "right_arm": "candidate", "both_pass": 1,
            "left_only_pass": 4, "right_only_pass": 1, "neither_pass": 1,
            "pass_count_delta": -3, "pass_rate_delta": -3 / 7,
        }])

    def test_all_declared_arms_compared_even_with_no_records(self):
        self.protocol["arms"].append({
            "id": "unmeasured",
            "limits": dict(self.protocol["arms"][0]["limits"]),
        })
        self.protocol["cases"] = self.protocol["cases"][:1]
        report = self._report([self._external_verdict("reference", "ordinary", READY)])
        self.assertEqual(report["arms"]["unmeasured"]["case_ids_by_outcome"]["missing"], ["ordinary"])
        self.assertEqual([
            (row["left_arm"], row["right_arm"], row["pass_count_delta"])
            for row in report["pairs"]
        ], [("reference", "candidate", -1), ("reference", "unmeasured", -1),
            ("candidate", "unmeasured", 0)])

    def test_every_declared_limit_must_match(self):
        for key in ("max_model_calls", "max_tool_calls", "max_elapsed_seconds"):
            with self.subTest(key=key):
                protocol = copy.deepcopy(self.protocol)
                protocol["arms"][1]["limits"][key] += 1
                self._rejected("unequal declared limits", protocol=protocol)

    def test_invalid_budget_or_authority_cannot_count_as_matched(self):
        for key, bad in (("max_model_calls", None), ("max_tool_calls", True),
                         ("max_elapsed_seconds", 0), ("max_elapsed_seconds", float("inf"))):
            with self.subTest(key=key, bad=bad):
                protocol = copy.deepcopy(self.protocol)
                for arm in protocol["arms"]:
                    arm["limits"][key] = bad
                self._rejected(key if bad != float("inf") else "is not a JSON number",
                               protocol=protocol)
        self.protocol["arms"][1]["tool_authority"] = "different-profile"
        self._rejected("does not use the shared tool_authority")

    def test_duplicate_arms_cases_and_results_are_rejected(self):
        for key, reason in (("arms", "duplicate arm id"), ("cases", "duplicate case id")):
            with self.subTest(key=key):
                protocol = copy.deepcopy(self.protocol)
                protocol[key].append(protocol[key][0])
                self._rejected(reason, protocol=protocol)
        record = self._external_verdict("candidate", "ordinary", b"BROKEN\n")
        retry = self._external_verdict("candidate", "ordinary", READY)
        self._rejected("duplicate result", records=[record, retry])

    def test_records_are_bound_to_exact_frozen_protocol_bytes(self):
        paths = self._files([])
        paths[0].write_bytes(paths[0].read_bytes() + b"\n")
        self._rejected("does not match the exact protocol bytes", paths=paths)

    def test_controller_completion_is_not_an_independent_verdict(self):
        record = self._external_verdict("candidate", "ordinary", READY)
        for change, reason in (
            ({"outcome": "done"}, "outcome must be one of"),
            ({"oracle_id": None}, "must name the frozen oracle_id"),
            ({"oracle_id": "different-oracle"}, "must name the frozen oracle_id"),
            ({"evidence_id": ""}, "evidence_id must be a nonempty string"),
        ):
            with self.subTest(change=change):
                self._rejected(reason, records=[{**record, **change}])

    def test_no_unplanned_or_synthetic_results(self):
        record = self._external_verdict("candidate", "ordinary", READY)
        for change in ({"arm_id": "extra-arm"}, {"case_id": "extra-case"}):
            with self.subTest(change=change):
                self._rejected("unplanned arm/case pair", records=[{**record, **change}])
        self._rejected("outcome must be one of", records=[{**record, "outcome": "missing"}])


if __name__ == "__main__":
    unittest.main()
