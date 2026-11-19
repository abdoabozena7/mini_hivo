"""Live-006: opaque receipt hashes are data, not browser requirements."""
import copy
import unittest
from unittest.mock import patch

import mini
from hivo.verification import evaluate_web_snapshot, infer_web_profile
import test_repair_cycle_001 as fixtures


class BrowserRequirementAuthorityTests(unittest.TestCase):
    def setUp(self):
        self.case=fixtures.RepairCycleTests('test_recorded_nine_lexical_targets_are_replaced_by_assigned_paths')
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)

    def test_recorded_applicability_hash_cannot_add_game_obligations(self):
        contract={'goal':'Build a responsive task-list web application.',
                  'requirements':['Provide a task input and list.']}
        baseline=mini._scoped_browser_profile(contract['goal'],contract)
        contaminated=copy.deepcopy(contract)
        contaminated['verification_applicability']={
            'verification_applicability_hash':'a369fb73ad53f3dcceaa96a94351c98563761aac25f02d652b61c38a6edfe91c'}
        self.assertEqual(mini._scoped_browser_profile(contract['goal'],contaminated),baseline)
        self.assertEqual(baseline.kind,'web')

    def test_diagnostics_and_tool_descriptions_cannot_create_requirements(self):
        contract={'goal':'Create a browser utility.', 'requirements':['Show the requested controls.'],
                  'diagnostics':{'previous_profile':'game','notes':'canvas AGENT_GAME keyboard touch win'},
                  'receipt_hash':'3d'*32}
        profile=mini._scoped_browser_profile(contract['goal'],contract)
        self.assertEqual(profile.kind,'web')
        self.assertFalse(profile.require_canvas)
        self.assertEqual(profile.required_interactions,())

    def test_real_game_and_timer_requirements_remain_enforced(self):
        for goal,kind in [('Build a game with keyboard movement, coin collection, obstacles, restart and a win state.','game'),
                          ('Build a countdown timer with start, pause and reset.','timer')]:
            with self.subTest(kind=kind):
                profile=mini._scoped_browser_profile(goal,{'goal':goal,'requirements':[goal],'receipt_hash':'3d'*32})
                self.assertEqual(profile.kind,kind)
                self.assertTrue(profile.required_interactions)
                if kind=='game':
                    self.assertTrue(profile.require_canvas)
                    self.assertTrue(profile.require_game_bridge)
                    snapshot={'title':'Game','text':'Game','console_errors':[],'network_errors':[],
                              'page_errors':[],'runtime_state':{},'interaction_checks':[]}
                    self.assertFalse(evaluate_web_snapshot(snapshot,profile)['passed'])

    def test_real_web_errors_are_not_suppressed_by_profile_correction(self):
        goal='Build a browser utility.'
        profile=mini._scoped_browser_profile(goal,{'goal':goal})
        snapshot={'title':'Utility','text':'Utility','console_errors':[],
                  'network_errors':['404 /missing.js'],'page_errors':[],
                  'runtime_state':{},'interaction_checks':[]}
        self.assertFalse(evaluate_web_snapshot(snapshot,profile)['passed'])

    def test_explicit_verification_requirements_are_not_dropped(self):
        contract={'goal':'Update an interface.',
                  'verification_requirements':['A 3D game must support keyboard movement and a win state.']}
        profile=mini._scoped_browser_profile(contract['goal'],contract)
        self.assertEqual(profile.kind,'game')
        self.assertIn('keyboard_movement',profile.required_interactions)
        self.assertIn('goal_win_state',profile.required_interactions)
        contract['requirements']=[{'text':'Build a countdown timer with pause and reset.'}]
        contract.pop('verification_requirements')
        self.assertEqual(mini._scoped_browser_profile(contract['goal'],contract).kind,'timer')

    def test_run_file_and_explicit_browser_tool_use_the_same_authority(self):
        (self.case.root/'index.html').write_text('<html><title>Utility</title><body>Utility</body></html>')
        mini.ACTIVE_TOOL_CONTRACT={'goal':'Build a browser utility.', 'requirements':['Show a useful page.'],
            'task_id':'1','receipt_hash':'3d'*32}
        profiles=[]
        def snapshot(path,task_id,profile=None,**kwargs):
            profiles.append(profile)
            return {'passed':True,'environment_error':False,'title':'Utility','text':'Utility'}
        with patch.object(mini,'browser_workspace_snapshot',side_effect=snapshot):
            mini.run_file('index.html')
            mini.run_tool('verify_web_app',{'path':'index.html'},role='Falsifier')
        self.assertEqual(len(profiles),2)
        self.assertEqual(profiles[0],profiles[1])
        self.assertEqual(profiles[0].kind,'web')

    def test_css_is_not_executable_and_skip_does_not_satisfy_verification(self):
        (self.case.root/'view.css').write_text('body { color: navy; }')
        result=mini.run_file('view.css')
        self.assertTrue(result.startswith('[not_applicable]'),result)
        self.assertFalse(mini.evidence_gate({'status':'done','tool_evidence':[
            {'tool':'run_file','target':'view.css','result':result}]})['passed'])


if __name__=='__main__': unittest.main()
