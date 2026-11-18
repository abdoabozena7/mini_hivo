"""Provider-free ingestion regressions, including historical withheld-fix counterexamples."""
import unittest
from hivo import requirements as r
from hivo import project_understanding as u

class IngestionIntegrationTests(unittest.TestCase):
    def conflicts(self, *texts):
        return r.detect_explicit_conflicts(r.build_source_requirement_ledger([
            {"text": t, "source_segment": i} for i, t in enumerate(texts, 1)]))

    def test_unchanged_complete_coin_courier_prompt(self):
        from pathlib import Path
        import hashlib
        raw = (Path(__file__).parent / "fixtures/coin_courier_prompt.txt").read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), "848c24c7c5788d077635af5677663ab5d3fe540498252cf3ad3ae3f01b64e256")
        ledger = r.build_source_requirement_ledger(r.deterministic_requirement_candidates(raw.decode(), 1))
        self.assertEqual(r.detect_explicit_conflicts(ledger), [])
        self.assertEqual(u.classify_project_mode(raw.decode())["project_mode"], u.NEW_PROJECT)

    def test_compatible_different_actions_and_scopes(self):
        pairs = [
            ("Display current score and best score.", "A lower-scoring round must not replace the best score."),
            ("A coin cannot award points repeatedly without another collection.", "Verify actual collection behavior."),
            ("A coin cannot award points repeatedly without another collection.", "Adapters must exercise collection transitions."),
            ("Display account details.", "Do not upload account details."),
            ("Display saved preferences.", "Never delete saved preferences."),
            ("Reset current score.", "Preserve highest score across reload."),
            ("Upload records after confirmation.", "Do not upload records before confirmation."),
            ("Show a Reset button with clear instructions.", "Preserve instructions and settings."),
        ]
        for pair in pairs:
            with self.subTest(pair=pair): self.assertEqual(self.conflicts(*pair), [])

    def test_arbitrary_predicates_keep_real_negation_conflicts(self):
        for verb in ("Encrypt", "Log", "Compress", "Display", "Upload", "Install", "Download", "Replace", "Archive", "Synchronize"):
            for neg in ("Do not", "Never", "The application must not"):
                with self.subTest(verb=verb,neg=neg):
                    self.assertEqual(len(self.conflicts(f"{verb} account records.", f"{neg} {verb.lower()} account records.")), 1)

    def test_removal_and_preservation_remain_conflicting(self):
        self.assertEqual(len(self.conflicts("Remove keyboard controls.", "Keyboard controls must remain unchanged.")), 1)
        self.assertEqual(len(self.conflicts("Delete saved preferences.", "Preserve saved preferences.")), 1)

    def test_negative_reset_is_not_an_affirmative_reset(self):
        self.assertEqual(self.conflicts("Restart must not erase all persisted data.", "Saved preferences must persist across restart."), [])

    def test_positive_reset_and_offline_conflicts_are_preserved(self):
        self.assertEqual(len(self.conflicts("Restart must erase all persisted data.", "Best score must persist across restart.")), 1)
        self.assertEqual(len(self.conflicts("Use only offline local data.", "Always retrieve required state from the live remote service.")), 1)

    def test_scoped_negation_does_not_hide_following_contradiction(self):
        self.assertEqual(len(self.conflicts("Support keyboard shortcuts.", "Do not delete saved preferences. Remove keyboard shortcuts.")), 1)

    def test_empty_workspace_build_is_greenfield(self):
        for goal in ("Build Coin Courier, a complete standalone browser game in this empty workspace. Preserve highest score. Modify only this workspace.", "Create an editor in a blank directory. Preserve saved preferences.", "Develop a dashboard in an empty folder. Update displayed count."):
            with self.subTest(goal=goal): self.assertEqual(u.classify_project_mode(goal)["project_mode"],u.NEW_PROJECT)

    def test_incidental_empty_location_does_not_override_existing_intent(self):
        for goal in ("Create a report in an empty directory. Fix the existing SettingsService.", "Create a cache in an empty folder for the existing application. Modify the current renderer.", "Fix the existing SettingsService in an empty workspace.", "Modify the current renderer."):
            with self.subTest(goal=goal): self.assertEqual(u.classify_project_mode(goal)["project_mode"],u.EXISTING_PROJECT)

    def test_actual_repository_contents_take_precedence(self):
        inventory={"files":[{"path":"index.html"}],"meaningful_files":["index.html"]}
        self.assertEqual(u.classify_project_mode("Build a game in an empty workspace.", inventory)["project_mode"],u.EXISTING_PROJECT)
