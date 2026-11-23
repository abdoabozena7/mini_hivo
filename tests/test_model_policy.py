from dataclasses import FrozenInstanceError
import unittest


EXPECTED_ANALYTICAL_ROLES = (
    "coordinator",
    "predictor",
    "challenger",
    "falsifier",
    "quality",
    "visual",
    "specifier",
    "mission_compiler",
    "clarifier",
    "requirement_extractor",
    "recon_agent",
    "task_brain_compiler",
    "impact_planner",
    "impact_challenger",
    "impact_plan_reviser",
)


class SingleModelPolicyTests(unittest.TestCase):
    def test_every_role_is_pinned_to_gemma(self):
        from hivo.model_policy import GEMMA_MODEL, SingleModelPolicy

        roles = SingleModelPolicy().role_models()
        self.assertEqual(len(roles), 17)
        self.assertEqual(set(roles.values()), {GEMMA_MODEL})

    def test_any_other_requested_model_is_rejected(self):
        from hivo.model_policy import SingleModelPolicy

        with self.assertRaises(ValueError):
            SingleModelPolicy().validate("qwen2.5-coder:7b")

    def test_staged_builder_uses_twelve_k_context_not_the_model_maximum(self):
        from hivo.model_policy import SingleModelPolicy

        self.assertEqual(SingleModelPolicy().context_window("Builder"), 12_288)
        # SingleModelPolicy preserves 12,288 even when instantiated with a compact model.
        self.assertEqual(
            SingleModelPolicy("qwen2.5-coder:1.5b").context_window("Builder"),
            12_288,
        )

    def test_weak_model_sampling_is_low_variance_and_role_specific(self):
        from hivo.model_policy import SingleModelPolicy

        policy = SingleModelPolicy()

        self.assertEqual(policy.temperature("Builder"), 0.1)
        self.assertEqual(policy.temperature("Repairer"), 0.1)
        self.assertEqual(policy.temperature("Visual"), 0.2)
        self.assertEqual(policy.temperature("Coordinator"), 0.0)

    def test_model_for_role_and_symmetry_helpers_preserve_single_model_contract(self):
        from hivo.model_policy import SingleModelPolicy

        policy = SingleModelPolicy("qwen2.5-coder:3b")

        self.assertFalse(policy.is_asymmetric)
        self.assertEqual(policy.distinct_models(), ("qwen2.5-coder:3b",))
        for role in ("Builder", "Repairer", "Coordinator", "ImpactPlanner", *EXPECTED_ANALYTICAL_ROLES):
            with self.subTest(role=role):
                self.assertEqual(policy.model_for_role(role), "qwen2.5-coder:3b")


class AsymmetricModelPolicyTests(unittest.TestCase):
    def test_worker_role_classification_is_strict_and_case_insensitive(self):
        from hivo.model_policy import WORKER_ROLES, is_worker_role

        self.assertEqual(WORKER_ROLES, frozenset({"builder", "repairer"}))
        for worker in ("builder", "Builder", "  BUILDER\t", "repairer", "Repairer", " repairer\n"):
            with self.subTest(worker=worker):
                self.assertTrue(is_worker_role(worker))

        non_workers = (
            *EXPECTED_ANALYTICAL_ROLES,
            "Coordinator",
            "MissionCompiler",
            "RequirementExtractor",
            "ReconAgent",
            "TaskBrainCompiler",
            "ImpactPlanner",
            "ImpactChallenger",
            "ImpactPlanReviser",
            "Quality Review",
            "System",
            "worker",
            "",
        )
        for role in non_workers:
            with self.subTest(role=role):
                self.assertFalse(is_worker_role(role))
        self.assertFalse(is_worker_role(None))  # type: ignore[arg-type]

    def test_asymmetric_role_routing_enforces_zero_orchestrator_code_writing_invariant(self):
        from hivo.model_policy import AsymmetricModelPolicy, SingleModelPolicy

        policy = AsymmetricModelPolicy(
            orchestrator_model="gemma4:e4b",
            worker_model="qwen2.5-coder:1.5b",
        )

        self.assertTrue(policy.is_asymmetric)
        self.assertEqual(policy.model_name, "qwen2.5-coder:1.5b")
        self.assertEqual(policy.distinct_models(), ("gemma4:e4b", "qwen2.5-coder:1.5b"))

        role_map = policy.role_models()
        self.assertEqual(list(role_map.keys()), list(SingleModelPolicy().role_models().keys()))
        self.assertEqual(len(role_map), 17)
        self.assertEqual(len(EXPECTED_ANALYTICAL_ROLES), 15)

        for role in EXPECTED_ANALYTICAL_ROLES:
            with self.subTest(role=role):
                self.assertEqual(role_map[role], "gemma4:e4b")
                self.assertEqual(policy.model_for_role(role), "gemma4:e4b")

        for camel_role in (
            "Coordinator",
            "Predictor",
            "Challenger",
            "Falsifier",
            "Quality",
            "Quality Review",
            "Visual",
            "Specifier",
            "MissionCompiler",
            "Clarifier",
            "RequirementExtractor",
            "ReconAgent",
            "TaskBrainCompiler",
            "ImpactPlanner",
            "ImpactChallenger",
            "ImpactPlanReviser",
        ):
            with self.subTest(camel_role=camel_role):
                self.assertEqual(policy.model_for_role(camel_role), "gemma4:e4b")

        for worker_role in ("builder", "Builder", "  builder ", "repairer", "Repairer"):
            with self.subTest(worker_role=worker_role):
                self.assertEqual(policy.model_for_role(worker_role), "qwen2.5-coder:1.5b")
        self.assertEqual(role_map["builder"], "qwen2.5-coder:1.5b")
        self.assertEqual(role_map["repairer"], "qwen2.5-coder:1.5b")

    def test_symmetric_pair_in_asymmetric_policy_collapses_distinct_models(self):
        from hivo.model_policy import AsymmetricModelPolicy, GEMMA_MODEL

        policy = AsymmetricModelPolicy()
        self.assertEqual(policy.orchestrator_model, GEMMA_MODEL)
        self.assertEqual(policy.worker_model, GEMMA_MODEL)
        self.assertEqual(policy.model_name, GEMMA_MODEL)
        self.assertFalse(policy.is_asymmetric)
        self.assertEqual(policy.distinct_models(), (GEMMA_MODEL,))

    def test_post_init_normalizes_and_rejects_invalid_model_names(self):
        from hivo.model_policy import AsymmetricModelPolicy

        padded = AsymmetricModelPolicy("  gemma4:e4b  ", "  qwen2.5-coder:1.5b  ")
        self.assertEqual(padded.orchestrator_model, "gemma4:e4b")
        self.assertEqual(padded.worker_model, "qwen2.5-coder:1.5b")

        with self.assertRaises(FrozenInstanceError):
            padded.worker_model = "qwen2.5-coder:3b"  # type: ignore[misc]

        for bad_name in ("gemma4: e4b", "../gemma4:e4b", "http://127.0.0.1/model", "gemma4:", ":latest"):
            with self.subTest(bad_orchestrator=bad_name):
                with self.assertRaises(ValueError):
                    AsymmetricModelPolicy(orchestrator_model=bad_name, worker_model="qwen2.5-coder:1.5b")
            with self.subTest(bad_worker=bad_name):
                with self.assertRaises(ValueError):
                    AsymmetricModelPolicy(orchestrator_model="gemma4:e4b", worker_model=bad_name)

    def test_validate_allows_only_pinned_orchestrator_or_worker_and_defaults_to_worker(self):
        from hivo.model_policy import AsymmetricModelPolicy

        policy = AsymmetricModelPolicy("gemma4:e4b", "qwen2.5-coder:1.5b")
        self.assertEqual(policy.validate(), "qwen2.5-coder:1.5b")
        self.assertEqual(policy.validate(None), "qwen2.5-coder:1.5b")
        self.assertEqual(policy.validate(""), "qwen2.5-coder:1.5b")
        self.assertEqual(policy.validate("gemma4:e4b"), "gemma4:e4b")
        self.assertEqual(policy.validate("qwen2.5-coder:1.5b"), "qwen2.5-coder:1.5b")

        with self.assertRaises(ValueError) as ctx:
            policy.validate("qwen2.5-coder:7b")
        self.assertEqual(
            str(ctx.exception),
            "this experiment pins orchestrator=gemma4:e4b and worker=qwen2.5-coder:1.5b; "
            "requested model 'qwen2.5-coder:7b' is not allowed",
        )

    def test_context_window_uses_8192_for_ultra_compact_builders_and_12288_for_larger_builders(self):
        from hivo.model_policy import AsymmetricModelPolicy, SingleModelPolicy

        compact_workers = (
            "qwen2.5-coder:0.5b",
            "llama3.2:1b",
            "qwen2.5-coder:1.5b",
            "qwen2.5-coder:1.5b-instruct-q4_K_M",
            "gemma2:2b",
            "qwen2.5-coder:3b",
            "qwen2.5-coder:3B",
            "phi3:3.5b",
        )
        for worker in compact_workers:
            with self.subTest(compact_worker=worker):
                policy = AsymmetricModelPolicy("gemma4:e4b", worker)
                self.assertEqual(policy.context_window("Builder"), 8_192)
                self.assertEqual(policy.context_window("builder"), 8_192)
                self.assertEqual(policy.context_window("Repairer"), 8_192)
                self.assertEqual(policy.context_window("Falsifier"), 8_192)
                self.assertEqual(policy.context_window("Coordinator"), 4_096)
                self.assertEqual(policy.context_window("ImpactPlanner"), 4_096)

        larger_workers = (
            "gemma4:e4b",
            "phi3.5:3.8b",
            "qwen3:4b",
            "qwen2.5-coder:7b",
            "qwen2.5-coder:14b",
            "qwen2.5-coder:32b",
            "gpt-oss:20b-cloud",
        )
        for worker in larger_workers:
            with self.subTest(larger_worker=worker):
                policy = AsymmetricModelPolicy("gemma4:e4b", worker)
                self.assertEqual(policy.context_window("Builder"), 12_288)

        single = SingleModelPolicy()
        asymmetric = AsymmetricModelPolicy("gemma4:e4b", "qwen2.5-coder:1.5b")
        for role in ("Coordinator", "ImpactPlanner", "Falsifier", "Repairer", "Visual", "Builder", "Unknown"):
            with self.subTest(temp_role=role):
                self.assertEqual(asymmetric.temperature(role), single.temperature(role))


if __name__ == "__main__":
    unittest.main()
