"""Opt-in REAL headed/headless browser smoke and broken-button negative control.
Run: PROVE_IT_BROWSER_E2E=1 python -m unittest discover -s tests -p test_browser_e2e.py
"""
import contextlib
import functools
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import io
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import threading
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import proof

class QuietHandler(SimpleHTTPRequestHandler):
    def log_message(self,*args): pass

@unittest.skipUnless(os.environ.get('PROVE_IT_BROWSER_E2E')=='1','Opt in to launch a real browser')
class BrowserE2E(unittest.TestCase):
    def test_headed_real_actions_and_broken_button_detection(self):
        output=Path(os.environ.get('PROVE_IT_VALIDATION_DIR',str(ROOT/'validation/browser-smoke')))
        output.mkdir(parents=True,exist_ok=True)
        with tempfile.TemporaryDirectory() as temp:
            project=Path(temp); (project/'index.html').write_bytes((ROOT/'examples/browser-demo.html').read_bytes())
            server=ThreadingHTTPServer(('127.0.0.1',0),functools.partial(QuietHandler,directory=str(project)))
            thread=threading.Thread(target=server.serve_forever,daemon=True); thread.start()
            try:
                plan={'base_url':f'http://127.0.0.1:{server.server_port}/','environment':'local',
                  'headed':bool(os.environ.get('DISPLAY') or os.name=='nt'),'timeout_ms':2000,
                  'scenarios':[{'name':'desktop-persistence','viewport':{'width':1280,'height':800},'steps':[
                    {'action':'goto'}, {'action':'fill','selector':'#item','value':'Verified browser item'},
                    {'action':'click','selector':'#add'},{'action':'expect_text','selector':'#count','value':'1 items'},
                    {'action':'expect_text','selector':'#items li','value':'Verified browser item'},
                    {'action':'reload'},{'action':'expect_text','selector':'#items li','value':'Verified browser item'}]},
                    {'name':'mobile-invalid-input','viewport':{'width':390,'height':844},'steps':[
                    {'action':'goto'},{'action':'click','selector':'#add'},
                    {'action':'expect_text','selector':'#error','value':'Enter an item'},
                    {'action':'expect_count','selector':'#items li','value':0}]}]}
                executable=shutil.which('chromium') or shutil.which('chromium-browser')
                if executable: plan['executable_path']=executable
                proof.save(project/'journey.json',plan)
                c=proof.load(ROOT/'examples/cli-contract.json')
                c.update(kind='web',task_id='browser-demo',source_paths=['index.html','journey.json'],goal='Exercise real desktop persistence and mobile validation in the supplied browser fixture.')
                req=c['requirements'][0]; req.update(claim='The actual UI adds and persists the item and rejects empty input.',
                    oracle='Observe the item text and persisted DOM after reload; empty input leaves the list empty.',
                    failure_example='A disconnected Add button must fail the expected item count.',review_required=True,checks=['browser'])
                c['checks']=[{'id':'browser','description':'Drive real browser input, clicks, persistence and validation.',
                 'mode':'live','role':'acceptance','command':['{python}',str(ROOT/'scripts/browser_probe.py'),'--plan','journey.json'],
                 'timeout_seconds':90,'expected_exit_codes':[0],
                 'assertions':[{'type':'json','file':'probe.json','pointer':'/passed','op':'eq','value':True},
                               {'type':'json','file':'probe.json','pointer':'/assertion_count','op':'ge','value':5}],
                 'artifacts':[{'glob':'screens/**/*.png','min_count':11,'min_bytes':500},
                              {'glob':'videos/**/*.webm','min_count':2,'min_bytes':500},
                              {'glob':'traces/*.zip','min_count':2,'min_bytes':500}]}]
                c['plan']['tasks'][0]['checks']=['browser']
                task=project/'.runtime-proof/browser-demo'; task.mkdir(parents=True)
                proof.save(task/'contract.json',c); proof.save(task/'context.json',{'project':str(project)})
                proof.validate_contract(c); proof.save(task/'seal.json',{'contract_hash':proof.digest(c),'engine_hash':proof.engine_hash()})
                with contextlib.redirect_stdout(io.StringIO()): good=proof.run_check(task,'browser')
                run=task/proof.load(task/'latest/browser.json')['run']
                shutil.copytree(run,output/(('working-' if good['passed'] else 'failed-') + good['run_id']),dirs_exist_ok=True)
                self.assertTrue(good['passed'],str(good['errors']) + (run/'probe.json').read_text())
                # Visual review is not fabricated by this test: final gate still refuses it.
                self.assertFalse(proof.verify(task)['passed'])
                original=(project/'index.html').read_text()
                (project/'index.html').write_text(original.replace("items.push(input.value.trim());", "/* deliberately disconnected add behavior */"))
                with contextlib.redirect_stdout(io.StringIO()): bad=proof.run_check(task,'browser')
                self.assertFalse(bad['passed'])
                run=task/proof.load(task/'latest/browser.json')['run']
                shutil.copytree(run,output/('broken-' + bad['run_id']),dirs_exist_ok=True)
                self.assertFalse(proof.verify(task)['passed'])
                proof.save(output/'summary.json',{'scope':'Harness demo only; not user project acceptance',
                    'headed':plan['headed'],'real_browser_good_passed':good['passed'],
                    'broken_button_correctly_rejected':not bad['passed'],
                    'uninspected_visual_evidence_did_not_clear_final_gate':True})
            finally:
                server.shutdown(); server.server_close(); thread.join(timeout=5)
if __name__=='__main__':unittest.main(verbosity=2)
