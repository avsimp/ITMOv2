"""Offline regression checks for the blind evaluation harness."""

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from assistant_check import digest_files, prepare_snapshot, summarize


class HarnessTest(unittest.TestCase):
    def test_reasoning_is_not_a_visible_answer(self):
        result = summarize([
            {"type": "reasoning", "part": {"text": "Correct but hidden"}},
            {"type": "step_finish", "sessionID": "s1", "part": {"reason": "stop"}},
        ])
        self.assertEqual(result["text"], "")
        self.assertEqual(result["session_ids"], ["s1"])

    def test_forbidden_tool_and_error_are_preserved(self):
        result = summarize([
            {"type": "tool_use", "part": {"tool": "bash", "state": {"status": "error"}}},
            {"type": "error", "error": "denied"},
        ])
        self.assertFalse(result["allowed_tools_only"])
        self.assertEqual(len(result["tool_errors"]), 1)
        self.assertEqual(len(result["errors"]), 1)

    def test_snapshot_does_not_include_answer_key(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            prepare_snapshot(root, "homework")
            self.assertEqual(set(digest_files(root)),
                             {"assistant_check.py", "test_assistant_check.py", "opencode.json"})
            config = json.loads((root / "opencode.json").read_text())
            permissions = config["agent"]["local-guide"]["permission"]
            self.assertEqual(permissions, {"*": "deny", "read": "allow", "glob": "allow", "grep": "allow"})
            self.assertEqual(config["enabled_providers"], ["ollama"])
            before = digest_files(root)
            (root / "assistant_check.py").write_text("changed")
            self.assertNotEqual(before, digest_files(root))

    def test_existing_results_are_never_overwritten(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory)
            marker = output / "q1.jsonl"
            marker.write_text("original")
            result = subprocess.run(
                [sys.executable, str(Path(__file__).with_name("assistant_check.py")),
                 "--output", directory, "--question", "test"], capture_output=True, text=True
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("FileExistsError", result.stderr)
            self.assertEqual(marker.read_text(), "original")


if __name__ == "__main__":
    unittest.main()
