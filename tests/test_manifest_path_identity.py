"""Snapshot lookup must use Windows filesystem identity, not string casing."""
import os
import unittest

import mini
import test_verified_manifest_provenance as provenance


@unittest.skipUnless(os.name == 'nt', 'Windows case-insensitive path identity')
class ManifestPathIdentityTests(unittest.TestCase):
    def setUp(self):
        self.fixture = provenance.VerifiedManifestProvenanceTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root

    def attach(self, changed):
        task = mini.make_task('1', 'Implement assigned component', 1, 'ROOT', scope_hint=['app.js'])
        result = {'status': 'done', 'changed_files': changed}
        return mini.attach_verified_manifest(task, result)

    def test_case_alias_of_created_file_retains_introduced_symbols(self):
        mini.begin_transaction('1')
        mini._transaction_capture(self.root / 'APP.JS')
        (self.root / 'app.js').write_text('function render(){return 1;}')
        changed = mini.commit_transaction()
        self.assertIn('render', self.attach(changed)['introduced_symbols'])

    def test_case_alias_of_modified_file_retains_prior_symbol_history(self):
        (self.root / 'app.js').write_text('function render(){return 1;}')
        mini.begin_transaction('1')
        mini._transaction_capture(self.root / 'APP.JS')
        (self.root / 'app.js').write_text('function render(){return 2;}\nfunction added(){}')
        manifest = self.attach(mini.commit_transaction())
        self.assertIn('render', manifest['modified_symbols'])
        self.assertNotIn('render', manifest['introduced_symbols'])
        self.assertIn('added', manifest['introduced_symbols'])

    def test_unrelated_file_snapshot_cannot_supply_prior_symbol_history(self):
        (self.root / 'other.js').write_text('function render(){return 1;}')
        mini.begin_transaction('1')
        mini._transaction_capture(self.root / 'other.js')
        (self.root / 'app.js').write_text('function render(){return 2;}')
        mini.commit_transaction()
        self.assertNotIn('render', self.attach(['app.js'])['modified_symbols'])


if __name__ == '__main__':
    unittest.main()
