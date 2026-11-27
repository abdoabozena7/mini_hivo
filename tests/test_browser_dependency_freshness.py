"""Offline receipt controls: scripted verification, real files and parent gates."""
import json
import unittest

from hivo import integration_gate as gate
import test_verified_child_integration as fixtures


class BrowserDependencyFreshnessTests(unittest.TestCase):
    def setUp(self):
        self.case = fixtures.VerifiedChildIntegrationGateTests()
        self.case.setUp()
        self.addCleanup(self.case.tearDown)
        self.root = self.case.root
        self.case.write('index.html', '<link rel="stylesheet" href="style.css">'
                        '<script type="module" src="src/app.js?v=1#boot"></script>')
        self.case.write('style.css', 'body {color: navy}')
        self.case.write('src/app.js', "import './state.js';\n")
        self.case.write('src/state.js', 'export const value = 1;')

    def receipt(self, *, expect_verified=True):
        task, result = self.case.child('A', 'index.html', focused='index.html')
        route = {'kind': 'BROWSER', 'required': True, 'applicable': True,
                 'target': 'index.html', 'result': 'PASS'}
        result['gate']['verification_aggregation'].update(
            verification_routes=[route], actual_passes=[route], skipped_not_applicable=[])
        result['builder']['tool_evidence'] = [
            {'tool': 'verify_web_app', 'target': 'index.html',
             'result': json.dumps({'passed': True, 'resolved_entrypoint': 'index.html'})}]
        receipt = gate.create_verified_child_receipt(
            task, result, parent_id='PARENT', parent_contract=self.case.parent_contract,
            workspace=self.root)
        self.assertEqual(receipt['verified'], expect_verified)
        return task, result, receipt

    def paths(self):
        return gate.derive_evidence_dependency_paths(
            verification_evidence=[{'tool': 'verify_web_app', 'target': 'index.html'}],
            workspace=self.root)

    def test_html_links_and_module_imports_are_fingerprinted(self):
        self.assertEqual(set(self.paths()),
                         {'index.html', 'style.css', 'src/app.js', 'src/state.js'})

    def test_linked_script_change_blocks_parent_readiness(self):
        task, result, receipt = self.receipt()
        def readiness():
            return self.case.readiness([(task, result)], {'A': receipt}, plan=self.case.plan[:1])
        self.assertEqual(readiness()['readiness'], 'READY')
        self.case.write('src/app.js', 'throw new Error("changed after verification");')
        actual = readiness()
        self.assertEqual(actual['reason'], gate.NOT_READY_STALE_EVIDENCE)
        self.assertIn('A', actual['freshness']['stale_child_ids'])

    def test_stylesheet_change_invalidates_receipt(self):
        receipt = self.receipt()[2]
        self.case.write('style.css', 'body {display:none}')
        self.assertFalse(gate.receipt_freshness(receipt, self.root)['fresh'])

    def test_transitive_module_change_invalidates_receipt(self):
        receipt = self.receipt()[2]
        self.case.write('src/state.js', 'export const value = 2;')
        self.assertFalse(gate.receipt_freshness(receipt, self.root)['fresh'])

    def test_unrelated_file_does_not_invalidate_receipt(self):
        receipt = self.receipt()[2]
        self.case.write('unrelated.js', '// unrelated')
        self.assertTrue(gate.receipt_freshness(receipt, self.root)['fresh'])

    def test_missing_linked_file_is_recorded_and_creation_changes_state(self):
        self.case.write('index.html', '<script src="missing.js"></script>')
        self.assertIn('missing.js', self.paths())
        receipt = self.receipt()[2]  # Synthetic PASS only tests identity, not browser acceptance.
        self.case.write('missing.js', 'console.log("now exists")')
        self.assertFalse(gate.receipt_freshness(receipt, self.root)['fresh'])

    def test_local_base_url_encoded_names_and_root_links(self):
        self.case.write('index.html', '<base href="/src/"><script src="space%20name.js?q=1"></script>'
                        '<link rel="stylesheet" href="/style.css">')
        self.case.write('src/space name.js', 'console.log(1)')
        self.assertEqual(set(self.paths()), {'index.html', 'src/space name.js', 'style.css'})

    def test_external_base_and_navigation_are_not_local_dependencies(self):
        self.case.write('index.html', '<base href="https://example.invalid/">'
                        '<script src="remote.js"></script><a href="private.html">go</a>')
        self.assertEqual(self.paths(), ['index.html'])

    def test_comments_and_data_urls_do_not_add_files(self):
        self.case.write('index.html', '<!-- <script src="unused.js"></script> -->'
                        '<script src="data:text/javascript,alert(1)"></script>')
        self.assertEqual(self.paths(), ['index.html'])

    def test_document_directory_with_url_metacharacters_stays_literal(self):
        self.case.write('part#1/index.html', '<script src="app.js"></script>')
        actual = gate.derive_evidence_dependency_paths(
            verification_evidence=[{'target': 'part#1/index.html'}], workspace=self.root)
        self.assertIn('part#1/app.js', actual)

    def test_linked_file_removal_invalidates_receipt(self):
        receipt = self.receipt()[2]
        (self.root / 'src/app.js').unlink()  # Disposable test fixture only.
        self.assertFalse(gate.receipt_freshness(receipt, self.root)['fresh'])

    def test_malformed_external_and_escaped_parent_references_are_not_read(self):
        self.case.write('index.html', '<script src="http://[invalid"></script>'
                        '<script src="%2e%2e%2foutside.js"></script>'
                        '<script src="//example.invalid/remote.js"></script>')
        self.assertEqual(self.paths(), ['index.html'])

    def test_cyclic_local_modules_finish_and_remain_tracked(self):
        self.case.write('src/state.js', "import './app.js';")
        self.assertEqual(set(self.paths()),
                         {'index.html', 'style.css', 'src/app.js', 'src/state.js'})

    def test_overflow_is_bounded_and_cannot_issue_verified_receipt(self):
        self.case.write('index.html', ''.join(
            f'<script src="part{i}.js"></script>' for i in range(140)))
        self.assertLessEqual(len(self.paths()), 120)
        receipt = self.receipt(expect_verified=False)[2]
        self.assertIn('EVIDENCE_DEPENDENCY_LIMIT_EXCEEDED', receipt['verification_failure_reasons'])


if __name__ == '__main__':
    unittest.main()
