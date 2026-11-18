import unittest


class ContextPolicyTests(unittest.TestCase):
    def test_old_tool_outputs_are_compacted_without_mutating_history(self):
        from hivo.context import compact_messages

        original = [{"role": "system", "content": "system"}]
        original.extend({"role": "tool", "content": "x" * 10_000} for _ in range(12))
        projected = compact_messages(original, max_chars=20_000, keep_recent=3)
        self.assertLessEqual(sum(len(item["content"]) for item in projected), 20_000)
        self.assertEqual(len(original[1]["content"]), 10_000)
        self.assertIn("HIVO HISTORY OMITTED", projected[1]["content"])
        self.assertIn("never copy this marker into code", projected[1]["content"])

    def test_large_historical_tool_arguments_are_compacted_too(self):
        from hivo.context import compact_messages, projected_size

        original = [
            {"role": "system", "content": "system"},
            {"role": "assistant", "content": "", "tool_calls": [{
                "id": "call-1",
                "function": {
                    "name": "edit_file",
                    "arguments": {
                        "path": "index.html",
                        "old": "a" * 12_000,
                        "new": "b" * 12_000,
                    },
                },
            }]},
            {"role": "tool", "tool_name": "edit_file", "content": "error: retry with a smaller edit"},
        ]

        projected = compact_messages(original, max_chars=3_000, keep_recent=2)

        self.assertLessEqual(projected_size(projected), 3_000)
        self.assertEqual(original[1]["tool_calls"][0]["function"]["arguments"]["old"], "a" * 12_000)
        arguments = projected[1]["tool_calls"][0]["function"]["arguments"]
        self.assertEqual(arguments["path"], "index.html")
        self.assertEqual(arguments["old"], "")
        self.assertEqual(arguments["new"], "")

    def test_recent_tool_payload_is_untouched_when_context_has_room(self):
        from hivo.context import compact_messages

        source = "function timer() { return 1500; }\n" * 240
        messages = [
            {"role": "system", "content": "system"},
            {"role": "user", "content": "build timer"},
            {"role": "assistant", "content": "", "tool_calls": [{
                "function": {
                    "name": "write_file",
                    "arguments": {"path": "script.js", "content": source},
                },
            }]},
            {"role": "tool", "tool_name": "write_file", "content": "wrote file"},
        ]

        projected = compact_messages(messages, max_chars=18_432, keep_recent=4)

        content = projected[2]["tool_calls"][0]["function"]["arguments"]["content"]
        self.assertEqual(content, source)


if __name__ == "__main__":
    unittest.main()
