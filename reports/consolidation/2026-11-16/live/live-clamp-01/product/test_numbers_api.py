import unittest

from numbers_api import clamp_number


class ClampContractTests(unittest.TestCase):
    def test_lower_bound(self):
        self.assertEqual(clamp_number(-2, 0, 5), 0)

    def test_upper_bound(self):
        self.assertEqual(clamp_number(9, 0, 5), 5)

    def test_in_range_and_boundaries(self):
        for value in (0, 2, 5):
            with self.subTest(value=value):
                self.assertEqual(clamp_number(value, 0, 5), value)


if __name__ == "__main__":
    unittest.main()
