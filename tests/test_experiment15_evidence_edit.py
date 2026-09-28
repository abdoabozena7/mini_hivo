import tempfile
import unittest
from pathlib import Path

from hivo.mutation_grounding import MutationGrounding, MUTATION_TARGET_UNRESOLVED, MAX_REFRESH_LINES
from tests import test_experiment4_mutation_grounding as fixtures


class EvidenceEditBindingTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name);self.path=self.root/'code.js'
        self.original='const first = 1;\nconst second = 2;\n'
        self.path.write_text(self.original,encoding='utf-8')

    def state(self,policy):
        g=MutationGrounding(self.root,('code.js',),policy=policy)
        g.observe_read('read_file',{'path':'code.js'},self.path.read_text(encoding='utf-8'),self.path)
        return g

    def request(self,old='const second = 2;',new='const second = 3;'):
        return {'path':'code.js','old':old,'new':new}

    def failed_then_full_read(self,g):
        self.path.write_text('const first = 10;\nconst second = 2;\n',encoding='utf-8')
        rejected=g.before_mutation('edit_file',self.request(),self.path,tool_step=3)
        self.assertFalse(rejected['allowed'])
        g.observe_read('read_file',{'path':'code.js'},self.path.read_text(encoding='utf-8'),self.path)
        return rejected

    def test_identical_small_full_read_can_refresh_exact_candidate_only_in_variant(self):
        for policy,accepted in (('evidence_grounded',False),('evidence_bound',True)):
            self.path.write_text(self.original,encoding='utf-8')
            g=self.state(policy);self.failed_then_full_read(g)
            decision=g.before_mutation('edit_file',self.request(),self.path,tool_step=5)
            self.assertEqual(decision['allowed'],accepted)
            self.assertEqual(g.bounded_refreshes,int(accepted))
            if accepted:
                self.assertEqual(decision['attempt']['source_lines'],[2,2])
                self.assertIsNone(g.terminal_reason)

    def test_full_and_range_refresh_authorize_same_region_with_same_source_hash(self):
        results=[]
        for tool in ('read_file','read_file_range'):
            self.path.write_text(self.original,encoding='utf-8')
            g=self.state('evidence_bound')
            self.path.write_text('const first = 10;\nconst second = 2;\n',encoding='utf-8')
            g.before_mutation('edit_file',self.request(),self.path,tool_step=3)
            args={'path':'code.js','start_line':1,'end_line':2}
            text=self.path.read_text(encoding='utf-8') if tool=='read_file' else fixtures.range_result(self.path,1,2)
            g.observe_read(tool,args,text,self.path)
            d=g.before_mutation('edit_file',self.request(),self.path,tool_step=5)
            results.append((d['allowed'],d['attempt']['source_lines'],d['attempt']['source_before_hash']))
        self.assertEqual(results[0],results[1])

    def test_full_refresh_cannot_unlock_full_write_or_multiple_replacements(self):
        for tool,args in (('write_file',{'path':'code.js','content':'rewritten'}),
                          ('edit_file',{'path':'code.js','old':'const','new':'let','expected_replacements':2})):
            self.path.write_text(self.original,encoding='utf-8')
            g=self.state('evidence_bound');self.failed_then_full_read(g)
            d=g.before_mutation(tool,args,self.path,tool_step=5)
            self.assertFalse(d['allowed']);self.assertEqual(g.terminal_reason,MUTATION_TARGET_UNRESOLVED)

    def test_large_full_read_does_not_refresh_but_bounded_range_still_can(self):
        self.path.write_text('const x = 0;\n'*(MAX_REFRESH_LINES+1),encoding='utf-8')
        g=MutationGrounding(self.root,('code.js',),policy='evidence_bound')
        args=self.request('const x = 0;\nconst x = 0;','changed')
        g.before_mutation('edit_file',args,self.path,tool_step=1)
        g.observe_read('read_file',{'path':'code.js'},self.path.read_text(encoding='utf-8'),self.path)
        self.assertEqual(g.refresh['code.js'],'required')
        self.assertEqual(g.bounded_refreshes,0)
        g.observe_read('read_file_range',{'path':'code.js','start_line':1,'end_line':2},fixtures.range_result(self.path,1,2),self.path)
        self.assertEqual(g.refresh['code.js'],'ready')

    def test_fabricated_or_stale_read_does_not_refresh(self):
        g=self.state('evidence_bound')
        self.path.write_text('changed\n',encoding='utf-8')
        g.before_mutation('edit_file',self.request('changed'),self.path,tool_step=2)
        g.observe_read('read_file',{'path':'code.js'},self.original,self.path)
        self.assertEqual(g.refresh['code.js'],'required')
        d=g.before_mutation('edit_file',self.request('changed'),self.path,tool_step=4)
        self.assertFalse(d['allowed'])

    def test_stale_source_after_refresh_and_imagined_retry_remain_terminal(self):
        for mutate_after in (False,True):
            self.path.write_text(self.original,encoding='utf-8')
            g=self.state('evidence_bound');self.failed_then_full_read(g)
            if mutate_after:self.path.write_text('const second = 20;\n',encoding='utf-8')
            request=self.request('imagined') if not mutate_after else self.request('const second = 20;')
            d=g.before_mutation('edit_file',request,self.path,tool_step=5)
            self.assertFalse(d['allowed']);self.assertEqual(g.terminal_reason,MUTATION_TARGET_UNRESOLVED)

    def test_duplicate_occurrences_or_region_outside_refresh_are_not_authorized(self):
        for duplicate in (False,True):
            self.path.write_text(self.original,encoding='utf-8');g=self.state('evidence_bound')
            self.path.write_text('const first = 10;\nconst second = 2;\n'+('const second = 2;\n' if duplicate else ''),encoding='utf-8')
            g.before_mutation('edit_file',self.request(),self.path,tool_step=3)
            g.observe_read('read_file_range',{'path':'code.js','start_line':1,'end_line':1},fixtures.range_result(self.path,1,1),self.path)
            d=g.before_mutation('edit_file',self.request(),self.path,tool_step=5)
            self.assertFalse(d['allowed'])

    def test_unapproved_target_keeps_scope_authority_and_is_not_observed(self):
        other=self.root/'other.js';other.write_text('const x=1;',encoding='utf-8')
        g=self.state('evidence_bound')
        g.observe_read('read_file',{'path':'other.js'},other.read_text(),other)
        d=g.before_mutation('edit_file',{'path':'other.js','old':'const x=1;','new':'bad'},other,tool_step=2)
        # The outer scope gate owns rejection of an unapproved tool target.
        self.assertFalse(d['attempt']['grounded'])
        self.assertEqual(d['attempt']['evidence_reason'],'UNAPPROVED_TARGET')
        self.assertIsNone(d['attempt']['source_before_hash'])
        self.assertNotIn('other.js',g.anchors)


class EvidenceEditControllerTests(unittest.TestCase):
    def setUp(self):
        self.base=fixtures.MutationGroundingControllerTests();self.base.setUp();self.addCleanup(self.base.tearDown)

    def test_real_controller_stops_baseline_but_variant_applies_after_same_full_read(self):
        import mini
        for policy,expected in (('evidence_grounded',0),('evidence_bound',1)):
            mini.RUN['mutation_grounding_policy']=policy
            path=mini.WORKSPACE/'index.html'
            path.write_text('a\nif (event.key === "r") restart();\nz\n',encoding='utf-8')
            responses=[fixtures.tool_call('read_file',{'path':'index.html'}),
                fixtures.tool_call('context_sufficiency_check',{'context_status':'sufficient','reason':'source observed'}),
                fixtures.tool_call('edit_file',{'path':'index.html','old':'imagined','new':'bad'}),
                fixtures.tool_call('read_file',{'path':'index.html'}),
                fixtures.tool_call('edit_file',{'path':'index.html','old':'if (event.key === "r") restart();','new':'changed'}),
                fixtures.tool_call('run_command',{'command':'echo verified'}),
                {'role':'assistant','content':'completed','tool_calls':[]}]
            result,calls=self.base._run(responses)
            self.assertEqual(len(calls),expected)
            self.assertEqual(result['mutation_grounding']['applied_mutation_attempts'],expected)
            self.assertEqual(result['failure_type'],MUTATION_TARGET_UNRESOLVED if expected==0 else None)


if __name__=='__main__':unittest.main()
