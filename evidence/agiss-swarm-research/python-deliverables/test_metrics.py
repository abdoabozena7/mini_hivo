import unittest
from metrics import summarize_latencies

class TestMetrics(unittest.TestCase):
    def test_summarize_latencies_success(self):
        """Test successful summarization for a standard list."""
        values = [10.0, 20.0, 30.0]
        expected = {"count": 3, "min": 10.0, "max": 30.0, "mean": 20.0}
        result = summarize_latencies(values)
        self.assertEqual(result['count'], expected['count'])
        self.assertAlmostEqual(result['min'], expected['min'])
        self.assertAlmostEqual(result['max'], expected['max'])
        self.assertAlmostEqual(result['mean'], expected['mean'])

    def test_summarize_latencies_single_element(self):
        """Test summarization with only one element."""
        values = [42.5]
        expected = {"count": 1, "min": 42.5, "max": 42.5, "mean": 42.5}
        result = summarize_latencies(values)
        self.assertEqual(result['count'], expected['count'])
        self.assertAlmostEqual(result['min'], expected['min'])
        self.assertAlmostEqual(result['max'], expected['max'])
        self.assertAlmostEqual(result['mean'], expected['mean'])

    def test_summarize_latencies_empty_list(self):
        """Test summarization with an empty list, expecting default/error handling."""
        values = []
        expected = {"count": 0, "min": None, "max": None, "mean": None}
        with self.assertRaisesRegex(ValueError, "values must not be empty"):
            summarize_latencies(values)

if __name__ == '__main__':
    unittest.main()
