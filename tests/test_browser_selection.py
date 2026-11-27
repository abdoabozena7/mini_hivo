"""Browser harness path contracts; no model calls or browser installation."""
from pathlib import Path
import json
import tempfile
import unittest
from unittest.mock import Mock, MagicMock, patch
from scripts.browser_selection import select_browser, validate_browser, BrowserSelectionError


class HistoricalDependencyTests(unittest.TestCase):
    def test_harness_has_no_private_historical_browser_dependency(self):
        source = (Path(__file__).resolve().parents[1] / 'scripts/provider_controller_functional.py').read_text(encoding='utf-8')
        self.assertNotIn('20261120-canonical-005', source)


class BrowserSelectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.browser = self.root / 'chromium.exe'
        self.browser.write_text('unit fixture, never executed', encoding='utf-8')
        self.browser.chmod(self.browser.stat().st_mode | 0o111)

    def test_explicit_valid_override_has_priority(self):
        which = Mock()
        selection = select_browser(str(self.browser), platform='win32', which=which, environ={})
        self.assertEqual(selection.executable, str(self.browser.resolve()))
        self.assertEqual(selection.source, 'explicit'); which.assert_not_called()

    def test_missing_or_directory_override_never_falls_back(self):
        which = Mock(return_value=str(self.browser))
        for path in [self.root / 'missing.exe', self.root]:
            with self.assertRaisesRegex(BrowserSelectionError, 'OVERRIDE_MISSING_OR_UNUSABLE'):
                select_browser(path, bundled_path=self.browser, platform='win32', which=which)
        which.assert_not_called()

    def test_installed_bundle_works_without_any_history(self):
        which = Mock()
        with patch.object(Path, 'read_text', side_effect=AssertionError('No historical evidence reads')):
            selection = select_browser(bundled_path=self.browser, platform='win32', which=which, environ={})
        self.assertEqual(selection.source, 'playwright-bundled'); which.assert_not_called()

    def test_missing_bundle_falls_back_to_valid_path_candidate(self):
        selection = select_browser(bundled_path=self.root / 'absent', platform='win32', environ={},
                                   which=lambda name: str(self.browser) if name == 'chromium' else None)
        self.assertEqual(selection.source, 'PATH')

    def test_standard_installed_location_is_discovered(self):
        chrome = self.root / 'Google/Chrome/Application/chrome.exe'
        chrome.parent.mkdir(parents=True); chrome.write_text('fixture', encoding='utf-8')
        selection = select_browser(platform='win32', environ={'ProgramFiles': str(self.root)}, which=lambda _: None)
        self.assertEqual(selection.executable, str(chrome.resolve()))
        self.assertEqual(selection.source, 'installed-location')

    def test_absent_browser_is_explicit_failure_not_installation(self):
        with self.assertRaisesRegex(BrowserSelectionError, 'BROWSER_NOT_FOUND'):
            select_browser(platform='win32', environ={}, which=lambda _: None)

    def test_launch_validation_records_actual_selected_path_and_version(self):
        selection = select_browser(self.browser, platform='win32')
        instance = Mock(); instance.version = 'fixture Chromium version'
        chromium = Mock(); chromium.launch.return_value = instance
        result = validate_browser(selection, chromium)
        chromium.launch.assert_called_once_with(headless=True, executable_path=selection.executable, timeout=5000)
        instance.close.assert_called_once()
        self.assertEqual(result['status'], 'READY')
        self.assertEqual(result['executable'], selection.executable)
        self.assertEqual(result['version'], instance.version)

    def test_incompatible_executable_cannot_become_ready(self):
        chromium = Mock(); chromium.launch.side_effect = RuntimeError('unit failure')
        with self.assertRaisesRegex(BrowserSelectionError, 'BROWSER_LAUNCH_UNAVAILABLE'):
            validate_browser(select_browser(self.browser, platform='win32'), chromium)

    def test_missing_version_and_failed_cleanup_are_failures(self):
        instance = Mock(); instance.version = ''
        chromium = Mock(); chromium.launch.return_value = instance
        with self.assertRaisesRegex(BrowserSelectionError, 'VERSION_UNAVAILABLE'):
            validate_browser(select_browser(self.browser, platform='win32'), chromium)
        instance.close.assert_called_once()
        instance.version = 'fixture'; instance.close.side_effect = RuntimeError('cannot close')
        with self.assertRaisesRegex(BrowserSelectionError, 'CLEANUP_FAILED'):
            validate_browser(select_browser(self.browser, platform='win32'), chromium)

    def test_harness_missing_override_stops_before_provider_or_project(self):
        from scripts import provider_controller_functional as harness
        out = self.root / 'unavailable-run'
        with patch('sys.argv', ['harness', '--output-dir', str(out), '--browser-executable', str(self.root / 'missing.exe')]), \
             patch.object(harness, 'ProviderClient') as provider, patch.object(harness, 'initialize') as initialize:
            self.assertEqual(harness.main(), 2)
        provider.assert_not_called(); initialize.assert_not_called()
        self.assertFalse((out / 'workspace').exists())
        self.assertFalse(json.loads((out / 'results.json').read_text())['checks']['browser_ready'])
        self.assertEqual(json.loads((out / 'browser-provenance.json').read_text())['status'], 'UNAVAILABLE')

    def test_harness_launch_failure_cannot_produce_application_success(self):
        from scripts import provider_controller_functional as harness
        out = self.root / 'launch-failed-run'
        manager = MagicMock()
        manager.__enter__.return_value.chromium.launch.side_effect = RuntimeError('incompatible executable')
        with patch('sys.argv', ['harness', '--output-dir', str(out), '--browser-executable', str(self.browser)]), \
             patch.object(harness, 'sync_playwright', return_value=manager), \
             patch.object(harness, 'ProviderClient') as provider, patch.object(harness, 'initialize') as initialize:
            self.assertEqual(harness.main(), 2)
        provider.assert_not_called(); initialize.assert_not_called()
        self.assertFalse((out / 'workspace').exists())
        result = json.loads((out / 'results.json').read_text())
        self.assertEqual(result['status'], 'BROWSER_UNAVAILABLE')
        self.assertFalse(result['checks']['browser_ready'])


if __name__ == '__main__': unittest.main()
