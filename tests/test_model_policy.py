import unittest


class SingleModelPolicyTests(unittest.TestCase):
    def test_every_role_is_pinned_to_gemma(self):
        from hivo.model_policy import GEMMA_MODEL, SingleModelPolicy

        roles = SingleModelPolicy().role_models()
        self.assertEqual(set(roles.values()), {GEMMA_MODEL})

    def test_any_other_requested_model_is_rejected(self):
        from hivo.model_policy import SingleModelPolicy

        with self.assertRaises(ValueError):
            SingleModelPolicy().validate("qwen2.5-coder:7b")

    def test_staged_builder_uses_twelve_k_context_not_the_model_maximum(self):
        from hivo.model_policy import SingleModelPolicy

        self.assertEqual(SingleModelPolicy().context_window("Builder"), 12_288)

    def test_weak_model_sampling_is_low_variance_and_role_specific(self):
        from hivo.model_policy import SingleModelPolicy

        policy = SingleModelPolicy()

        self.assertEqual(policy.temperature("Builder"), 0.1)
        self.assertEqual(policy.temperature("Repairer"), 0.1)
        self.assertEqual(policy.temperature("Coordinator"), 0.0)


if __name__ == "__main__":
    unittest.main()
