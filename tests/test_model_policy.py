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


if __name__ == "__main__":
    unittest.main()
