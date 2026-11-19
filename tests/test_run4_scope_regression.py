"""Run 2/3 handoff reproductions; scripted AI, production gates/tools/transactions."""
import copy
import unittest
from unittest.mock import patch

import mini
from hivo import pre_mutation_impact as impact
import test_repair_cycle_001 as fixtures
from test_repair_cycle_001 import call


class Run4ScopeRegressionTests(unittest.TestCase):
    def setUp(self):
        self.case = fixtures.RepairCycleTests('test_recorded_nine_lexical_targets_are_replaced_by_assigned_paths')
        self.case.setUp()
        self.addCleanup(self.case.doCleanups)
        self.root = self.case.root

    def task(self, hints=None, targets=None):
        task = self.case.task(hints or ('implementation responsibility',))
        task['worker_mission'] = {'targets': targets or ['engine.py']}
        return task

    def test_recorded_run3_semantic_hints_do_not_override_compiled_file_targets(self):
        task = self.task(['HTML structure','CSS styling','Basic layout'],['index.html','style.css'])
        candidate = mini._prepare_task_impact_contract(task,self.case.contract)
        self.assertEqual(candidate['authorized_mutation_paths'],['index.html','style.css'])
        self.assertNotIn('app.js',candidate['authorized_mutation_paths'])
        self.assertFalse(any('structure' in row['target'] for row in candidate['expected_targets']))

    def test_concrete_child_scope_cannot_be_expanded_by_compiler(self):
        task = self.task(['engine.py'],['foreign.py'])
        candidate = mini._prepare_task_impact_contract(task,self.case.contract)
        self.assertEqual(candidate['authorized_mutation_paths'],[])
        self.assertFalse(impact.accept_pre_mutation_impact_contract(candidate)['accepted'])

    def test_failed_verification_empty_completion_hands_off_without_claiming_success(self):
        import json
        task=self.task(['engine.py'],['engine.py'])
        real_tool=mini.run_tool
        def tool(name,args,role='Builder'):
            if name=='verify_web_app':
                return json.dumps({'passed':False,'environment_error':False,'failures':[{'code':'missing_dependency'}]})
            return real_tool(name,args,role=role)
        with patch.object(mini,'run_tool',side_effect=tool):
            result=self.case.worker(task,[call('context_sufficiency_check',context_status='sufficient'),
                call('write_file',path='engine.py',content='print("pending")'),
                call('verify_web_app',path='engine.py'),{'role':'assistant','content':'','tool_calls':[]}])
        self.assertEqual(result['status'],'verification_failed',result)
        self.assertEqual(result['failure_type'],'IMPLEMENTATION_ERROR')
        self.assertIsNone(mini.LAST_COMMITTED_TRANSACTION)
        self.assertFalse(mini.evidence_gate(result)['passed'])

    def test_handoff_does_not_invent_a_verdict_for_malformed_or_optional_checks(self):
        for result in ['{"passed":false', '{"passed":null}', '{"passed":true}',
                       '{"passed":false,"environment_error":true}',
                       '{"passed":false,"verification_route":{"required":false}}']:
            self.assertIsNone(mini._failed_verification_handoff([
                {'tool':'verify_web_app','target':'view.html','result':result}]))
        rows=[{'tool':'verify_web_app','target':'view.html','result':'{"passed":false}'},
              {'tool':'verify_web_app','target':'view.html','result':'{"passed":true}'}]
        self.assertIsNone(mini._failed_verification_handoff(rows))
        self.assertIsNone(mini._failed_verification_handoff([
            {'tool':'run_file','target':'engine.py','result':'[exit_code=1]\nassertion failed'},
            {'tool':'edit_file','target':'engine.py','result':'edited file: engine.py'}]))

    def test_empty_builder_failure_reaches_real_falsifier_repairer_and_fresh_commit(self):
        code='def value():\n    return 2\n\nassert value() == 3\n'
        replies=[call('context_sufficiency_check',context_status='sufficient'),
            call('write_file',path='engine.py',content=code),call('run_file',path='engine.py'),
            {'role':'assistant','content':'','tool_calls':[]},call('run_file',path='engine.py'),self.done(),
            call('context_sufficiency_check',context_status='sufficient'),call('read_file',path='engine.py'),
            call('edit_file',path='engine.py',old='return 2',new='return 3'),call('run_file',path='engine.py'),self.done()]
        result,_=self.execute(replies)
        self.assertEqual(result['status'],'done',result)
        self.assertTrue(result['gate']['passed'])
        self.assertTrue(result['impact_comparison']['passed'])
        self.assertGreater(mini.RUN['falsifier_calls'],0)
        self.assertGreater(mini.RUN['repairer_calls'],0)
        self.assertIn('return 3',(self.root/'engine.py').read_text())
        self.assertIsNone(mini.ACTIVE_TRANSACTION)

    def test_command_schema_advertises_actual_policy_and_inspection_tools(self):
        tool=next(t for t in mini.TOOLS if t['function']['name']=='run_command')['function']
        self.assertIn('list_files',tool['description'])
        for executable in mini.VERIFICATION_EXECUTABLES:
            self.assertIn(executable,tool['description'])
        self.assertIsNone(mini._validated_command_parts('ls')[0])
        self.assertIsNone(mini._validated_command_parts('echo pretend-pass')[0])

    def test_creation_context_distinguishes_absent_outputs_from_existing_source(self):
        task=self.task(['implementation responsibility'],['engine.py','theme.css'])
        (self.root/'theme.css').write_text('body{}')
        candidate=mini._prepare_task_impact_contract(task,self.case.contract)
        packet=mini._greenfield_creation_context(task['id'],candidate)
        self.assertIn('absent: assigned new artifact',packet)
        self.assertIn('present: inspect before editing',packet)
        self.assertIn('not a sufficiency decision or mutation authorization',packet)
        self.assertFalse((self.root/'engine.py').exists())
        mini.RUN['project_mode']=mini.EXISTING_PROJECT
        self.assertEqual(mini._greenfield_creation_context(task['id'],candidate),'')

    def test_extensionless_explicit_relative_path_and_spaced_filename_are_supported(self):
        task = self.task(['local outputs'],['./Buildfile','meeting notes.txt'])
        candidate = mini._prepare_task_impact_contract(task,self.case.contract)
        self.assertEqual(candidate['authorized_mutation_paths'],['Buildfile','meeting notes.txt'])

    def test_unsafe_and_semantic_targets_do_not_become_file_permissions(self):
        for target in ['../outside.py','.hivo/private.txt','.HIVO/private.txt','.GIT/config','HTML structure','src/*.py']:
            with self.subTest(target=target):
                task = self.task(['responsibility'],[target])
                candidate = mini._prepare_task_impact_contract(task,self.case.contract)
                self.assertEqual(candidate['authorized_mutation_paths'],[])
                self.assertFalse(impact.accept_pre_mutation_impact_contract(candidate)['accepted'])
        task = self.task(['responsibility'],['./src'])
        candidate = mini._prepare_task_impact_contract(task,
            dict(self.case.contract,allowed_mutation_paths=['src/allowed.py']))
        self.assertEqual(candidate['authorized_mutation_paths'],[])

    def test_descriptive_only_scope_fails_before_worker_dispatch(self):
        task = self.task(['presentation responsibility'],['visual structure'])
        mission = self.mission(task,targets=['visual structure'])
        with patch.object(mini,'structured_model_call',return_value=mission), \
             patch.object(mini,'execute_agent_task',side_effect=AssertionError('invalid assignment must not dispatch')):
            result = mini.execute_leaf(task,self.case.contract,{},mini.inspect_repository())
        self.assertEqual(result['failure_type'],impact.IMPACT_INCOMPLETE)
        self.assertIsNone(mini.ACTIVE_TRANSACTION)

    def test_repeated_scope_refusals_are_not_task_too_broad_or_strategy_evidence(self):
        task = self.task(['engine.py'],['engine.py'])
        asked=[]
        def reply(*_args,**_kwargs):
            asked.append(1)
            if len(asked)==1:
                return call('context_sufficiency_check',context_status='sufficient')
            return call('write_file',path='foreign.py',content='blocked')
        result = self.case.worker(task,reply)
        self.assertEqual(result['status'],'failed')
        self.assertEqual(result['failure_type'],impact.IMPACT_INVALID)
        self.assertLessEqual(len(asked),4)
        self.assertEqual(mini.diagnose_failure(task,result)['category'],'orchestration_failure')
        self.assertFalse((self.root/'foreign.py').exists())

    def mission(self,task,targets=None):
        return {'goal_anchor':self.case.goal,'task':task['goal'],'expected_outcome':'self-check passes',
            'targets':targets or ['engine.py'],'existing_facts':[],
            'implementation_plan':['Implement the bounded utility and execute its self-check'],
            'interfaces_to_reuse':[],'invariants':[],'project_specific_quality_rules':[],
            'do_not':['Do not change unrelated files'],'verification_plan':['run_file engine.py'],
            'done_when':task['done_when']}

    def test_compiler_requests_runtime_prerequisites_without_expanding_explicit_scope(self):
        task=self.task(['implementation responsibility'],['engine.py'])
        def compiler(prompt,validator,*args,**kwargs):
            self.assertIn('runtime\nprerequisites',prompt)
            self.assertIn('Never expand explicit child',prompt)
            result=self.mission(task)
            self.assertTrue(validator(result))
            return result
        with patch.object(mini,'structured_model_call',side_effect=compiler):
            mission=mini.compile_worker_mission(task,{'root_goal_anchor':self.case.goal},[],{'files':[]})
        self.assertEqual(mission['targets'],['engine.py'])

    def execute(self, replies, through_solver=False):
        task = self.task(['implementation responsibility'],['engine.py'])
        task['goal'] = 'Implement a calculation utility with an executable self-check.'
        task['done_when'] = ['The calculation utility self-check passes.']
        spec={field:[] for field in mini._PROJECT_SPECIFICATION_FIELDS}
        spec['root_goal']=self.case.goal
        mini.RUN['project_brain']=mini.build_project_brain(self.case.contract,spec,mini.inspect_repository())
        mission=self.mission(task)
        with patch.object(mini,'structured_model_call',return_value=mission), \
             patch.object(mini,'ask_ollama',side_effect=replies):
            if through_solver:
                with patch.object(mini,'_maybe_search_alternate_strategy',side_effect=AssertionError('scope is not strategy evidence')), \
                     patch.object(mini,'decompose_task',side_effect=AssertionError('scope is not decomposition evidence')):
                    return mini.solve_task(task,1,self.case.contract,{},mini.inspect_repository(),
                        fit_decider=lambda *_args:{'decision':'execute'},leaf_executor=mini.execute_leaf),task
            return mini.execute_leaf(task,self.case.contract,{},mini.inspect_repository()),task

    @staticmethod
    def done(): return {'role':'assistant','content':'Self-check evaluated.','tool_calls':[]}

    def test_real_leaf_writes_falsifies_verifies_commits_and_retains_files(self):
        code='def value():\n    return 3\n\nassert value() == 3\nprint("SELF_CHECK_OK")\n'
        replies=[call('context_sufficiency_check',context_status='sufficient'),
            call('write_file',path='engine.py',content=code),call('run_file',path='engine.py'),self.done(),
            call('run_file',path='engine.py'),self.done()]
        result,_=self.execute(replies)
        self.assertEqual(result['status'],'done',result)
        self.assertEqual((self.root/'engine.py').read_text(),code)
        self.assertTrue(result['gate']['passed'])
        self.assertTrue(result['impact_comparison']['passed'])
        self.assertGreater(mini.RUN['falsifier_calls'],0)
        self.assertIsNone(mini.ACTIVE_TRANSACTION)
        self.assertIsNotNone(mini.LAST_COMMITTED_TRANSACTION)

    def test_real_leaf_repairer_mutation_fresh_verification_and_commit(self):
        code='def value():\n    return 2\n\nassert value() == 3\nprint("SELF_CHECK_OK")\n'
        replies=[call('context_sufficiency_check',context_status='sufficient'),
            call('write_file',path='engine.py',content=code),call('run_file',path='engine.py'),self.done(),
            call('run_file',path='engine.py'),self.done(),
            call('context_sufficiency_check',context_status='sufficient'),call('read_file',path='engine.py'),
            call('edit_file',path='engine.py',old='return 2',new='return 3'),
            call('run_file',path='engine.py'),self.done(),call('run_file',path='engine.py'),self.done()]
        result,_=self.execute(replies)
        self.assertEqual(result['status'],'done',result)
        self.assertIn('return 3',(self.root/'engine.py').read_text())
        self.assertTrue(result['gate']['passed'])
        self.assertTrue(result['impact_comparison']['passed'])
        self.assertGreater(mini.RUN['repairer_calls'],0)
        self.assertIsNone(mini.ACTIVE_TRANSACTION)

    def test_one_scope_refusal_can_be_corrected_without_losing_authorized_progress(self):
        code='print("SELF_CHECK_OK")\n'
        replies=[call('context_sufficiency_check',context_status='sufficient'),
            call('write_file',path='foreign.py',content='blocked'),
            call('write_file',path='engine.py',content=code),call('run_file',path='engine.py'),self.done(),
            call('run_file',path='engine.py'),self.done()]
        result,_=self.execute(replies)
        self.assertEqual(result['status'],'done',result)
        self.assertTrue(result['gate']['passed'])
        self.assertTrue(result['impact_comparison']['passed'])
        self.assertFalse((self.root/'foreign.py').exists())
        self.assertEqual((self.root/'engine.py').read_text(),code)

    def test_terminal_repairer_scope_failure_cannot_be_promoted_by_fresh_verification(self):
        code='def value():\n    return 2\n\nassert value() == 3\n'
        replies=[call('context_sufficiency_check',context_status='sufficient'),
            call('write_file',path='engine.py',content=code),call('run_file',path='engine.py'),self.done(),
            call('run_file',path='engine.py'),self.done(),
            call('context_sufficiency_check',context_status='sufficient'),call('read_file',path='engine.py'),
            call('edit_file',path='engine.py',old='return 2',new='return 3'),
            *[call('edit_file',path='foreign.py',old='old',new='new') for _ in range(3)]]
        real_falsifier=mini.falsify_task
        calls=[]
        def falsifier(*args,**kwargs):
            calls.append(1)
            self.assertEqual(len(calls),1,'terminal Repairer failure must not enter fresh verification')
            return real_falsifier(*args,**kwargs)
        with patch.object(mini,'falsify_task',side_effect=falsifier):
            result,_=self.execute(replies)
        self.assertEqual(result['status'],'failed',result)
        self.assertEqual(result['failure_type'],impact.IMPACT_INVALID)
        self.assertFalse((self.root/'engine.py').exists())
        self.assertFalse((self.root/'foreign.py').exists())
        self.assertIsNone(mini.LAST_COMMITTED_TRANSACTION)

    def test_scope_failure_rolls_back_provisional_valid_writes_without_verification_promotion(self):
        replies=[call('context_sufficiency_check',context_status='sufficient'),
            call('write_file',path='engine.py',content='print("provisional")'),
            *[call('write_file',path='foreign.py',content='blocked') for _ in range(3)],self.done()]
        result,_=self.execute(replies,through_solver=True)
        self.assertEqual(result['status'],'failed',result)
        self.assertEqual(result['failure_type'],impact.IMPACT_INVALID)
        self.assertFalse((self.root/'engine.py').exists())
        self.assertFalse((self.root/'foreign.py').exists())
        self.assertEqual(mini.RUN['falsifier_calls'],0)
        self.assertIsNone(mini.LAST_COMMITTED_TRANSACTION)


if __name__=='__main__': unittest.main()
