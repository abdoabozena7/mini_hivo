"""Failure-oriented local tests. Does not claim CARLA/project/host-hook acceptance."""
import contextlib
import copy
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import proof
import planning
import install

class ProofTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.project = Path(self.temp.name)
        self.task = self.project / '.runtime-proof' / 'cli-demo'
        self.task.mkdir(parents=True)
        self.source = self.project / 'demo_cli.py'
        self.source.write_bytes((ROOT / 'examples/demo_cli.py').read_bytes())
        self.c = proof.load(ROOT / 'examples/cli-contract.json')
        proof.save(self.task / 'context.json', {'project':str(self.project)})
        proof.save(self.project / '.runtime-proof/active.json', {'task':'cli-demo','session_id':None})
        self.seal()
    def tearDown(self): self.temp.cleanup()
    def seal(self):
        proof.save(self.task / 'contract.json', self.c)
        proof.validate_contract(self.c)
        proof.save(self.task / 'seal.json', {'contract_hash':proof.digest(self.c), 'engine_hash':proof.engine_hash()})
    def run_check(self):
        with contextlib.redirect_stdout(io.StringIO()):
            return proof.run_check(self.task, 'addition')
    def complete(self):
        self.assertTrue(self.run_check()['passed'])
        proof.update_step(self.task,'T01','VERIFIED','Inspected actual subprocess output and exact arithmetic assertion.')
    def latest(self):
        return self.task / proof.load(self.task/'latest/addition.json')['run']
    def test_missing_execution_fails(self):
        self.assertFalse(proof.verify(self.task)['passed'])
    def test_real_process_and_plan_pass(self):
        self.complete()
        self.assertTrue(proof.verify(self.task)['passed'])
    def test_passing_execution_with_unfinished_todo_fails(self):
        self.assertTrue(self.run_check()['passed'])
        r=proof.verify(self.task)
        self.assertFalse(r['passed']); self.assertTrue(any('To-do' in e for e in r['errors']))
    def test_cannot_mark_verified_before_execution(self):
        with self.assertRaises(proof.ProofError):
            proof.update_step(self.task,'T01','VERIFIED','I claim the task is finished without running anything.')
    def test_wrong_actual_result_fails(self):
        self.source.write_text('print(\'{"sum":13}\')\n')
        self.assertFalse(self.run_check()['passed'])
        self.assertFalse(proof.verify(self.task)['passed'])
    def test_changed_source_invalidates_success(self):
        self.complete(); self.source.write_text(self.source.read_text()+'\n# change\n')
        self.assertFalse(proof.verify(self.task)['passed'])
    def test_tampered_stdout_fails(self):
        self.complete(); (self.latest()/'stdout.log').write_text('{"sum":12}\nmore\n')
        self.assertFalse(proof.verify(self.task)['passed'])
    def test_tampered_receipt_fails(self):
        self.complete(); p=self.latest()/'receipt.json'; r=proof.load(p); r['wall_seconds']=0; proof.save(p,r)
        self.assertFalse(proof.verify(self.task)['passed'])
    def test_missing_artifact_fails(self):
        self.c['checks'][0]['artifacts']=[{'glob':'video.mp4','min_count':1,'min_bytes':10}]
        self.seal(); self.assertFalse(self.run_check()['passed'])
    def test_timeout_fails_and_terminates(self):
        self.source.write_text('import time\ntime.sleep(10)\n')
        self.c['checks'][0]['timeout_seconds']=0.15; self.seal()
        receipt=self.run_check(); self.assertTrue(receipt['timeout']); self.assertFalse(receipt['passed'])
    def test_failed_exit_cannot_pass_with_right_output(self):
        self.source.write_text('print(\'{"sum":12}\')\nraise SystemExit(1)\n')
        self.assertFalse(self.run_check()['passed'])
    def test_stale_review_fails(self):
        self.c['requirements'][0]['review_required']=True; self.seal(); self.complete()
        self.assertFalse(proof.verify(self.task)['passed'])
        review={'reviewer':'test reviewer','independence':'same-agent','requirements':[{'requirement_id':'R01','verdict':'pass',
          'observations':'Inspected actual stdout: sum is numeric twelve, not a canned success label.',
          'evidence':[{'check_id':'addition','file':'stdout.log'}]}]}
        path=self.project/'review-input.json'; proof.save(path,review); proof.record_review(self.task,path)
        self.assertTrue(proof.verify(self.task)['passed'])
        self.run_check(); proof.update_step(self.task,'T01','VERIFIED','Inspected the repeated actual process output and numeric value.')
        self.assertFalse(proof.verify(self.task)['passed'])
    def test_new_interrupted_attempt_invalidates_older_success(self):
        self.complete()
        target=self.task/'runs/addition/interrupted'; target.mkdir()
        proof.save(target/'started.json',{'started':True})
        proof.save(self.task/'latest/addition.json',{'run':'runs/addition/interrupted','receipt_hash':None})
        self.assertFalse(proof.verify(self.task)['passed'])
    def test_contract_changes_fail_seal(self):
        self.complete(); c=copy.deepcopy(self.c); c['requirements'][0]['claim']='A secretly weakened alternative acceptance claim.'; proof.save(self.task/'contract.json',c)
        self.assertFalse(proof.verify(self.task)['passed'])
    def test_mock_only_cannot_satisfy_runtime(self):
        self.c['checks'][0]['mode']='fixture'
        with self.assertRaises(proof.ProofError): proof.validate_contract(self.c)
    def test_negative_control_expected_failure(self):
        negative=copy.deepcopy(self.c['checks'][0]); negative.update(id='negative',role='negative_control',fault='Supply nonnumeric operands to the actual argument parser.',command=['{python}','demo_cli.py','bad','5'],expected_exit_codes=[2],assertions=[{'type':'stderr_contains','value':'invalid int value'}])
        self.c['checks'].append(negative); self.c['requirements'][0]['negative_checks']=['negative']; self.seal(); self.complete()
        with contextlib.redirect_stdout(io.StringIO()): r=proof.run_check(self.task,'negative')
        self.assertTrue(r['passed']); self.assertTrue(proof.verify(self.task)['passed'])
    def test_shell_is_not_implicitly_enabled(self):
        self.c['checks'][0]['command']=['missing-nonexistent-executable-12345']; self.seal()
        self.assertFalse(self.run_check()['passed'])
    def test_numeric_string_is_not_numeric_proof(self):
        self.source.write_text('print(\'{"sum":"12"}\')\n'); self.assertFalse(self.run_check()['passed'])
    def test_reject_path_traversal(self):
        with self.assertRaises(proof.ProofError): proof.relative_file(self.project,'../elsewhere')
    @unittest.skipIf(os.name=='nt','Symlink setup may require Windows developer mode')
    def test_symlink_evidence_refused(self):
        p=self.project/'alias'; p.symlink_to(self.source)
        with self.assertRaises(proof.ProofError): proof.relative_file(self.project,'alias')
    def test_hook_blocks_missing_evidence(self):
        decision=proof.hook({'cwd':str(self.project),'stop_hook_active':False})
        self.assertEqual(decision.get('decision'),'block')
    def test_hook_no_progress_yields_without_certifying(self):
        proof.hook({'cwd':str(self.project),'stop_hook_active':False})
        result=proof.hook({'cwd':str(self.project),'stop_hook_active':True})
        self.assertEqual(result,{}); self.assertFalse(proof.load(self.task/'gate.json')['passed'])
        self.assertTrue((self.task/'needs-attention.json').exists())
    def test_hook_allows_verified_task(self):
        self.complete(); self.assertEqual(proof.hook({'cwd':str(self.project)}),{})
    def test_hook_other_session_ignored(self):
        proof.save(self.project/'.runtime-proof/active.json',{'task':'cli-demo','session_id':'abc'})
        self.assertEqual(proof.hook({'cwd':str(self.project),'session_id':'xyz'}),{})
    def test_blocked_handoff_not_success(self):
        proof.save(self.task/'blocked.json',{'reason':'The required local simulator runtime is not installed.'})
        self.assertEqual(proof.hook({'cwd':str(self.project)}),{})
        self.assertFalse(proof.verify(self.task)['passed'])
    def test_plan_cycle_rejected(self):
        self.c['plan']['tasks'][0]['depends_on']=['T01']
        with self.assertRaises(proof.ProofError): proof.validate_contract(self.c)
    def test_missing_integration_rejected(self):
        self.c['plan']['tasks'][0]['role']='implement'
        with self.assertRaises(proof.ProofError): proof.validate_contract(self.c)
    def test_subagent_not_available_rejected(self):
        self.c['plan']['tasks'][0]['execution']='subagent'
        with self.assertRaises(proof.ProofError): proof.validate_contract(self.c)
    def test_subagent_no_invocation_rejected(self):
        self.c['plan']['strategy']='hybrid'; self.c['plan']['delegation']['available']=True
        self.c['plan']['tasks'][0]['execution']='subagent'; self.seal()
        with self.assertRaises(proof.ProofError): proof.update_step(self.task,'T01','IN_PROGRESS','Starting a worker without a real invocation id.')
    def test_source_mutates_while_checking_fails(self):
        self.source.write_text('from pathlib import Path\np=Path(__file__)\np.write_text(p.read_text()+"\\n#mutation\\n")\nprint(\'{"sum":12}\')\n')
        self.assertFalse(self.run_check()['passed'])
    def test_stdout_overflow_not_silent_success(self):
        self.source.write_text('print("x"*100000)\n')
        with patch.object(proof,'MAX_LOG_BYTES',128):
            r=self.run_check()
        self.assertTrue(r['overflow']); self.assertFalse(r['passed'])
    def test_installer_preserves_existing_instructions_and_hooks(self):
        home=self.project/'home'; home.mkdir()
        settings=self.project/'.claude/settings.local.json'; settings.parent.mkdir()
        original={'permissions':{'allow':['Read']},'hooks':{'Stop':[{'hooks':[{'type':'command','command':'existing-tool'}]}]}}
        proof.save(settings,original)
        instructions=self.project/'CLAUDE.md'; instructions.write_text('Original project policy.\n')
        result=install.install('claude','user',self.project,home,True,True)
        config=proof.load(settings)
        self.assertEqual(config['permissions'],original['permissions']); self.assertEqual(len(config['hooks']['Stop']),2)
        self.assertTrue(instructions.read_text().startswith('Original project policy.'))
        self.assertTrue(result['backups'])
    def test_copilot_hook_serializes_expected_schema(self):
        home=self.project/'home'; home.mkdir()
        install.install('copilot','user',self.project,home,True,True)
        h=proof.load(self.project/'.github/hooks/prove-it.json')
        self.assertEqual(h['version'],1); self.assertIn('powershell',h['hooks']['agentStop'][0])
    def test_legitimate_todo_app_description_is_allowed(self):
        self.c['goal']='Build a working TODO app with real persistence and UI behavior.'
        proof.validate_contract(self.c)
    def two_step_plan(self):
        first=copy.deepcopy(self.c['plan']['tasks'][0])
        first.update(id='T00',role='implement',title='Implement arithmetic command behavior')
        self.c['plan']['tasks'][0]['depends_on']=['T00']
        self.c['plan']['tasks'].insert(0,first)
        self.seal()
    def test_dependency_cannot_start_before_deliverable(self):
        self.two_step_plan()
        with self.assertRaises(proof.ProofError):
            proof.update_step(self.task,'T01','IN_PROGRESS','Trying to integrate before the upstream deliverable exists.')
        proof.update_step(self.task,'T00','IMPLEMENTED','Implementation deliverable exists; actual acceptance is pending.')
        proof.update_step(self.task,'T01','IN_PROGRESS','Starting integration using the implemented upstream deliverable.')
    def test_all_plan_tasks_must_be_verified(self):
        self.two_step_plan()
        proof.update_step(self.task,'T00','IMPLEMENTED','Implementation deliverable exists; final runtime evidence is pending.')
        self.run_check()
        proof.update_step(self.task,'T01','VERIFIED','Verified actual integrated CLI arithmetic output on current source.')
        self.assertFalse(proof.verify(self.task)['passed'])
        proof.update_step(self.task,'T00','VERIFIED','Verified the implementation using the actual numeric output receipt.')
        self.assertTrue(proof.verify(self.task)['passed'])
    def test_two_node_dependency_cycle_rejected(self):
        self.two_step_plan()
        self.c['plan']['tasks'][0]['depends_on']=['T01']
        with self.assertRaises(proof.ProofError):proof.validate_contract(self.c)
    def test_subagent_handoff_required_and_integrity_bound(self):
        self.c['plan']['strategy']='hybrid'; self.c['plan']['delegation']['available']=True
        self.c['plan']['tasks'][0]['execution']='subagent'; self.seal()
        self.run_check()
        with self.assertRaises(proof.ProofError):
            proof.update_step(self.task,'T01','VERIFIED','Synthetic unit-test delegation entry without handoff.',agent_ref='synthetic-test-worker')
        handoff=self.task/'handoffs/worker.md'; handoff.parent.mkdir(); handoff.write_text('Synthetic unit-test handoff; not a real model invocation.')
        proof.update_step(self.task,'T01','VERIFIED','Synthetic test: actual arithmetic receipt plus a stored handoff.',agent_ref='synthetic-test-worker',handoff='handoffs/worker.md')
        self.assertTrue(proof.verify(self.task)['passed'])
        handoff.write_text('Changed synthetic test handoff after verification.')
        self.assertFalse(proof.verify(self.task)['passed'])
    def test_empty_assertions_rejected(self):
        self.c['checks'][0]['assertions']=[]
        with self.assertRaises(proof.ProofError): proof.validate_contract(self.c)
    def test_real_cli_entrypoint_smoke(self):
        result=subprocess.run([sys.executable,str(ROOT/'scripts/proof.py'),'verify','--task',str(self.task)],capture_output=True,text=True)
        self.assertEqual(result.returncode,1); self.assertFalse(json.loads(result.stdout)['passed'])

if __name__=='__main__': unittest.main(verbosity=2)
