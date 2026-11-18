import tempfile
import unittest
from pathlib import Path

import mini


class DependencyAwareSchedulerTests(unittest.TestCase):
    """Deterministic V19.5 child-DAG scheduling tests; never contacts Gemma."""

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.previous_workspace = mini.WORKSPACE
        mini.WORKSPACE = Path(self.temp.name)
        mini.reset_run("recursive")
        self.contract = {
            "status": "ready",
            "goal": "execute bounded child responsibilities",
            "requirements": ["all required child responsibilities are evaluated"],
            "success_criteria": ["the parent reports the strict aggregate result"],
        }

    def tearDown(self):
        mini.rollback_transaction()
        mini.ACTIVE_TOOL_CONTRACT = None
        mini.WORKSPACE = self.previous_workspace
        self.temp.cleanup()

    def run_children(self, specs, failures=(), failure_type="VERIFICATION_TARGET_UNRESOLVED",
                     inherited_dependencies=()):
        parent = mini.make_task(
            "P", self.contract["goal"], 0, "ROOT", ["all children evaluated"], [],
        )
        children = []
        for child_id, dependencies in specs:
            child = mini.make_task(
                child_id, f"run {child_id}", 1, "P", [f"{child_id} verified"], [],
            )
            # This is the explicit child-DAG boundary.  It is deliberately
            # independent from the list order passed to _execute_children.
            child["dependencies"] = list(dependencies)
            children.append(child)
            mini.TASKS[child_id] = child
            parent["children"].append(child_id)
        mini.TASKS["P"] = parent
        mini.RUN["tasks_created"] = 1 + len(children)

        fit_calls = []
        leaf_calls = []
        dependency_inputs = {}
        dependency_summaries = {}
        aggregate_calls = []

        def fit(task, *_args):
            fit_calls.append(task["id"])
            return {"decision": "execute"}

        def leaf(task, _contract, memory, _repo, _parent, dependencies):
            task_id = task["id"]
            leaf_calls.append(task_id)
            dependency_inputs[task_id] = [item.get("task_id") for item in dependencies]
            dependency_summaries[task_id] = {
                item.get("task_id"): item.get("summary") for item in dependencies
            }
            if task_id in set(failures):
                return {
                    "status": "failed",
                    "failure_type": failure_type,
                    "summary": f"{task_id} failed deterministically",
                    "memory": memory,
                }
            return {
                "status": "done",
                "summary": f"{task_id} completed",
                "memory": memory,
                "changed_files": [],
            }

        def aggregate(_task, _contract, completed, memory, _repo, root=False):
            aggregate_calls.append([item["task"]["id"] for item in completed])
            return {"status": "done", "summary": "all children completed", "memory": memory}

        result = mini._execute_children(
            parent, children, 0, self.contract, {}, {"files": []}, "", inherited_dependencies,
            fit_decider=fit, leaf_executor=leaf, aggregator=aggregate,
        )
        return {
            "parent": parent,
            "children": children,
            "result": result,
            "fit_calls": fit_calls,
            "leaf_calls": leaf_calls,
            "dependency_inputs": dependency_inputs,
            "dependency_summaries": dependency_summaries,
            "aggregate_calls": aggregate_calls,
        }

    @staticmethod
    def statuses(children):
        return {child["id"]: child["status"] for child in children}

    def test_failed_independent_child_does_not_stop_exact_abc_siblings(self):
        observed = self.run_children([("A", []), ("B", []), ("C", [])], failures={"A"})

        self.assertEqual(observed["leaf_calls"], ["A", "B", "C"])
        self.assertEqual(observed["fit_calls"], ["A", "B", "C"])
        self.assertEqual(self.statuses(observed["children"]), {
            "A": "failed", "B": "done", "C": "done",
        })
        self.assertEqual(observed["result"]["status"], "failed")
        self.assertEqual(observed["aggregate_calls"], [])
        self.assertEqual(mini.RUN["child_scheduler_terminal_failures"], 1)
        self.assertEqual(mini.RUN["child_scheduler_independent_after_failure"], 2)
        self.assertEqual(mini.RUN["child_scheduler_continued_after_failure"], 2)
        for child in observed["children"][1:]:
            self.assertTrue(child["child_scheduler"]["eligible"])
            self.assertTrue(child["child_scheduler"]["started"])
            self.assertEqual(child["child_scheduler"]["blocked_by"], [])
            self.assertTrue(child["child_scheduler"]["continued_after_prior_failure"])

    def test_verification_target_unresolved_is_an_ordinary_child_failure(self):
        observed = self.run_children(
            [("EXEC-001.1", []), ("EXEC-001.2", []), ("EXEC-001.3", [])],
            failures={"EXEC-001.1"},
        )

        self.assertEqual(observed["leaf_calls"], ["EXEC-001.1", "EXEC-001.2", "EXEC-001.3"])
        self.assertEqual(observed["result"]["status"], "failed")
        self.assertEqual(
            observed["parent"]["child_scheduler"]["execution_order"],
            ["EXEC-001.1", "EXEC-001.2", "EXEC-001.3"],
        )
        self.assertEqual(observed["parent"]["child_scheduler"]["dependency_edges"], [])

    def test_explicit_dependency_failure_blocks_only_required_child(self):
        observed = self.run_children(
            [("A", []), ("B", []), ("C", ["A"])], failures={"A"},
        )

        self.assertEqual(observed["leaf_calls"], ["A", "B"])
        self.assertEqual(observed["fit_calls"], ["A", "B"])
        self.assertEqual(self.statuses(observed["children"]), {
            "A": "failed", "B": "done", "C": "blocked",
        })
        blocked = observed["children"][2]
        self.assertEqual(blocked["last_failure_type"], mini.EXECUTION_DEPENDENCY_BLOCKED)
        self.assertEqual(blocked["child_scheduler"]["blocked_by"], ["A"])
        self.assertFalse(blocked["child_scheduler"]["eligible"])
        self.assertFalse(blocked["child_scheduler"]["started"])
        self.assertEqual(mini.RUN["child_scheduler_dependency_blocks"], 1)
        self.assertEqual(observed["result"]["status"], "failed")

    def test_transitive_dependency_failure_blocks_chain_but_runs_independent_d(self):
        observed = self.run_children(
            [("A", []), ("B", ["A"]), ("C", ["B"]), ("D", [])],
            failures={"A"},
        )

        self.assertEqual(observed["leaf_calls"], ["A", "D"])
        self.assertEqual(self.statuses(observed["children"]), {
            "A": "failed", "B": "blocked", "C": "blocked", "D": "done",
        })
        self.assertEqual(observed["children"][1]["child_scheduler"]["blocked_by"], ["A"])
        self.assertEqual(observed["children"][2]["child_scheduler"]["blocked_by"], ["B"])
        self.assertEqual(mini.RUN["child_scheduler_dependency_blocks"], 2)
        self.assertEqual(mini.RUN["child_scheduler_independent_after_failure"], 1)

    def test_multiple_dependencies_block_when_one_required_dependency_fails(self):
        observed = self.run_children(
            [("A", []), ("B", []), ("C", ["A", "B"])], failures={"B"},
        )

        self.assertEqual(observed["leaf_calls"], ["A", "B"])
        self.assertEqual(self.statuses(observed["children"]), {
            "A": "done", "B": "failed", "C": "blocked",
        })
        self.assertEqual(observed["children"][2]["child_scheduler"]["blocked_by"], ["B"])
        self.assertEqual(
            [item["normalized_status"] for item in observed["children"][2]["child_scheduler"]["dependency_statuses"]],
            ["COMPLETED", "FAILED"],
        )

    def test_successful_dependencies_execute_and_receive_compact_summaries(self):
        observed = self.run_children(
            [("A", []), ("B", []), ("C", ["A", "B"])],
        )

        self.assertEqual(observed["leaf_calls"], ["A", "B", "C"])
        self.assertEqual(self.statuses(observed["children"]), {
            "A": "done", "B": "done", "C": "done",
        })
        self.assertEqual(observed["dependency_inputs"]["A"], [])
        self.assertEqual(observed["dependency_inputs"]["B"], [])
        self.assertEqual(observed["dependency_inputs"]["C"], ["A", "B"])
        self.assertEqual(observed["aggregate_calls"], [["A", "B", "C"]])

    def test_out_of_order_prerequisites_run_before_consumers_with_stable_ready_order(self):
        observed = self.run_children([
            ("C", ["B"]), ("X", []), ("B", ["A"]), ("A", []), ("Y", []),
        ])

        order = ["X", "A", "B", "C", "Y"]
        self.assertEqual(observed["leaf_calls"], order)
        self.assertEqual(observed["fit_calls"], order)
        self.assertEqual(observed["parent"]["child_scheduler"]["execution_order"], order)
        self.assertEqual(observed["dependency_inputs"]["B"], ["A"])
        self.assertEqual(observed["dependency_inputs"]["C"], ["B"])
        self.assertEqual(observed["aggregate_calls"], [order])
        self.assertEqual(observed["result"]["status"], "done")

    def test_out_of_order_failure_blocks_only_the_dependent_sibling(self):
        observed = self.run_children(
            [("B", ["A"]), ("A", []), ("C", [])], failures={"A"},
        )

        self.assertEqual(observed["leaf_calls"], ["A", "C"])
        self.assertEqual(observed["fit_calls"], ["A", "C"])
        blocked = observed["children"][0]["child_scheduler"]
        self.assertEqual(blocked["blocked_by"], ["A"])
        self.assertEqual(blocked["dependency_statuses"][0]["normalized_status"], "FAILED")
        self.assertTrue(blocked["continued_after_prior_failure"])
        self.assertEqual(observed["result"]["failure_type"], "VERIFICATION_TARGET_UNRESOLVED")

    def test_local_prerequisite_uses_current_summary_but_external_dependency_keeps_inherited(self):
        observed = self.run_children(
            [("A", []), ("B", ["A", "External"])],
            inherited_dependencies=[
                {"task_id": "A", "status": "done", "summary": "older A"},
                {"task_id": "External", "status": "done", "summary": "verified outside parent"},
            ],
        )

        self.assertEqual(observed["result"]["status"], "done")
        self.assertEqual(observed["dependency_summaries"]["B"], {
            "A": "A completed", "External": "verified outside parent",
        })

    def test_unknown_and_cyclic_dependencies_block_even_with_an_inherited_cycle_match(self):
        observed = self.run_children(
            [
                ("Tail", ["A"]), ("Missing", ["absent"]), ("A", ["B"]),
                ("Independent", []), ("B", ["A"]), ("Self", ["Self"]),
            ],
            inherited_dependencies=[
                {"task_id": "B", "status": "done", "summary": "a different run's B"},
                {"task_id": "Self", "status": "done", "summary": "a different run's Self"},
            ],
        )

        self.assertEqual(observed["leaf_calls"], ["Independent"])
        self.assertEqual(observed["fit_calls"], ["Independent"])
        expected_blocks = {"Tail": "A", "Missing": "absent", "A": "B", "B": "A", "Self": "Self"}
        nodes = observed["parent"]["child_scheduler"]["nodes"]
        self.assertEqual(len(nodes), len(observed["children"]))
        self.assertEqual({
            node["child_id"]: node["blocked_by"][0]
            for node in nodes if node["terminal_status"] == "DEPENDENCY_BLOCKED"
        }, expected_blocks)
        self.assertEqual(observed["result"]["status"], "failed")
        self.assertEqual(observed["result"]["failure_type"], mini.EXECUTION_DEPENDENCY_BLOCKED)
        self.assertFalse(observed["aggregate_calls"])

    def test_duplicate_identity_is_ambiguous_and_runs_no_provider_or_consumer(self):
        observed = self.run_children(
            [("Provider", []), ("Consumer", ["Provider"]), ("Provider", []), ("Other", [])],
            inherited_dependencies=[
                {"task_id": "Provider", "status": "done", "summary": "different provider"},
            ],
        )

        self.assertEqual(observed["leaf_calls"], ["Other"])
        self.assertEqual(observed["fit_calls"], ["Other"])
        self.assertEqual([child["status"] for child in observed["children"]], [
            "blocked", "blocked", "blocked", "done",
        ])
        self.assertEqual(observed["children"][1]["child_scheduler"]["blocked_by"], ["Provider"])
        self.assertEqual(observed["result"]["failure_type"], mini.EXECUTION_DEPENDENCY_BLOCKED)
        self.assertFalse(observed["aggregate_calls"])

    def test_order_does_not_create_implicit_dependency_edges(self):
        observed = self.run_children(
            [("A", []), ("B", []), ("C", [])], failures={"A"},
        )

        scheduler = observed["parent"]["child_scheduler"]
        self.assertEqual(scheduler["execution_order"], ["A", "B", "C"])
        self.assertEqual(scheduler["dependency_edges"], [])
        self.assertEqual(
            [node["explicit_dependencies"] for node in scheduler["nodes"]],
            [[], [], []],
        )
        self.assertNotEqual(observed["children"][1]["status"], "blocked")
        self.assertNotEqual(observed["children"][2]["status"], "blocked")

    def test_failed_child_is_not_retried_and_scheduler_remains_sequential(self):
        observed = self.run_children(
            [("A", []), ("B", []), ("C", [])], failures={"A"},
        )

        self.assertEqual(observed["leaf_calls"].count("A"), 1)
        self.assertEqual(observed["leaf_calls"], ["A", "B", "C"])
        self.assertEqual(
            [node["order_position"] for node in observed["parent"]["child_scheduler"]["nodes"]],
            [1, 2, 3],
        )

    def test_dependency_blocked_child_gets_no_fit_or_leaf_call(self):
        observed = self.run_children(
            [("A", []), ("B", ["A"]), ("C", [])], failures={"A"},
        )

        self.assertNotIn("B", observed["fit_calls"])
        self.assertNotIn("B", observed["leaf_calls"])
        self.assertEqual(observed["children"][1]["status"], "blocked")
        self.assertEqual(observed["children"][1]["child_scheduler"]["started"], False)


if __name__ == "__main__":
    unittest.main()
