"""Controller manifest provenance across real sequential file transactions."""
import copy
from pathlib import Path
import tempfile
import unittest

import mini


class VerifiedManifestProvenanceTests(unittest.TestCase):
    def setUp(self):
        names=('WORKSPACE','RUN','RUN_ID','TASKS','ACTIVE_TRANSACTION','LAST_COMMITTED_TRANSACTION',
               'ACTIVE_PROJECT_WORLD_MODEL','MEMORY_STORE')
        old={name:getattr(mini,name) for name in names}
        self.addCleanup(lambda:[setattr(mini,k,v) for k,v in old.items()])
        temporary=tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root=Path(temporary.name)
        mini.WORKSPACE=self.root;mini.MEMORY_STORE=None;mini.ACTIVE_PROJECT_WORLD_MODEL=None
        mini.reset_run('recursive')

    def commit(self, task_id, path, content):
        target=self.root/path
        mini.begin_transaction(task_id)
        mini._transaction_capture(target)
        target.write_text(content,encoding='utf-8')
        changed=mini.commit_transaction()
        task=mini.make_task(task_id,'Implement assigned component',1,'ROOT',scope_hint=[path])
        task['changed_files']=[path]
        result={'status':'done','changed_files':changed,'summary':'Controlled transaction checkpoint'}
        mini.attach_verified_manifest(task,result)
        return task,result

    def test_empty_foundation_snapshot_does_not_acquire_successor_symbols(self):
        foundation,first=self.commit('1','app.js','// inert companion\n')
        before=copy.deepcopy(first['integration_manifest'])
        feature,second=self.commit('2','app.js','function render(){ return 1; }\n')
        mini.attach_verified_manifest(foundation,first)
        self.assertEqual(first['integration_manifest'],before)
        self.assertIn('render',second['integration_manifest']['introduced_symbols'])
        info=[{'task_id':t['id'],'integration_manifest':r['integration_manifest']} for t,r in
              [(foundation,first),(feature,second)]]
        preflight=mini.run_integration_preflight(child_info=info)
        self.assertFalse(any(c['kind']=='duplicate_child_symbol' for c in preflight['conflicts']),preflight)

    def test_prior_modified_symbols_do_not_use_latest_transaction_snapshot(self):
        first_task,first=self.commit('1','app.js','function render(){ return 1; }\n')
        before=copy.deepcopy(first['integration_manifest'])
        self.commit('2','app.js','function render(){ return 2; }\n')
        mini.attach_verified_manifest(first_task,first)
        self.assertEqual(first['integration_manifest'],before)
        self.assertEqual(first['integration_manifest']['modified_symbols'],[])

    def test_real_independent_duplicate_owners_still_fail(self):
        a,ra=self.commit('1','a.js','function shared(){ return 1; }\n')
        b,rb=self.commit('2','b.js','function shared(){ return 2; }\n')
        preflight=mini.run_integration_preflight(child_info=[
            {'task_id':a['id'],'integration_manifest':ra['integration_manifest']},
            {'task_id':b['id'],'integration_manifest':rb['integration_manifest']}])
        self.assertTrue(any(c['kind']=='duplicate_child_symbol' for c in preflight['conflicts']))

    def test_untrusted_builder_empty_manifest_does_not_suppress_source_inference(self):
        target=self.root/'app.js';mini.begin_transaction('1');mini._transaction_capture(target)
        target.write_text('function render(){ return 1; }\n',encoding='utf-8')
        changed=mini.commit_transaction()
        task=mini.make_task('1','Implement component',1,'ROOT',scope_hint=['app.js'])
        result={'status':'done','changed_files':changed,'builder':{'manifest':{'introduced_symbols':[]}}}
        mini.attach_verified_manifest(task,result)
        self.assertIn('render',result['integration_manifest']['introduced_symbols'])

    def test_current_duplicate_declarations_still_fail_after_snapshot_reuse(self):
        task,result=self.commit('1','app.js','function render(){ return 1; }\n')
        (self.root/'app.js').write_text('function render(){}\nfunction render(){}\n',encoding='utf-8')
        mini.attach_verified_manifest(task,result)
        preflight=mini.run_integration_preflight(child_info=[{'task_id':'1','integration_manifest':result['integration_manifest']}])
        self.assertTrue(any(c['kind']=='duplicate_declaration' for c in preflight['conflicts']))


if __name__=='__main__':unittest.main()
