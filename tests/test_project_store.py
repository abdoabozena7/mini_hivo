import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class ProjectStoreTests(unittest.TestCase):
    def test_legacy_list_contents_become_project_one_and_next_is_incremented(self):
        from hivo.projects import ProjectStore

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as raw:
            root = Path(raw) / "list"
            root.mkdir()
            (root / "index.html").write_text("legacy", encoding="utf-8")
            (root / ".agent_memory.json").write_text("{}", encoding="utf-8")

            store = ProjectStore(root)
            migration = store.migrate_legacy_contents()

            self.assertEqual(migration.project.name, "project-1")
            self.assertTrue((migration.project / "index.html").exists())
            self.assertTrue((migration.project / ".agent_memory.json").exists())
            self.assertEqual(store.create_project().name, "project-2")

    def test_project_numbers_ignore_unrelated_directory_names(self):
        from hivo.projects import ProjectStore

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as raw:
            root = Path(raw) / "list"
            (root / "project-not-a-number").mkdir(parents=True)
            (root / "project-7").mkdir()
            self.assertEqual(ProjectStore(root).create_project().name, "project-8")

    def test_blank_workspace_prompt_creates_the_next_default_project(self):
        import mini

        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as raw:
            root = Path(raw) / "list"
            previous_prompt_state = mini.PROMPT_TOOLKIT_AVAILABLE
            mini.PROMPT_TOOLKIT_AVAILABLE = False
            try:
                with patch("builtins.input", return_value=""):
                    workspace = mini.get_workspace(projects_root=root)
            finally:
                mini.PROMPT_TOOLKIT_AVAILABLE = previous_prompt_state
            self.assertEqual(workspace, root / "project-1")
            self.assertTrue(workspace.is_dir())


if __name__ == "__main__":
    unittest.main()
