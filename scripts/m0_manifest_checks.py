"""Bounded offline manifest correction checks; preserve each invocation separately."""
import argparse,hashlib,json,os,subprocess,sys,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
import mini

def main():
    p=argparse.ArgumentParser();p.add_argument('--output-dir',type=Path,required=True)
    p.add_argument('--adjacent',action='store_true');a=p.parse_args()
    out=a.output_dir.resolve();out.mkdir(parents=True,exist_ok=False)
    tmp=out/'tmp';tmp.mkdir();tempfile.tempdir=str(tmp)
    os.environ['PYTHONDONTWRITEBYTECODE']='1'
    names=['test_verified_manifest_provenance']
    if a.adjacent:names+=['test_adaptive_architecture','test_verified_child_integration','test_verification_outcome_integrity','test_run4_scope_regression']
    with (out/'tests.log').open('x',encoding='utf-8') as stream,patch.object(mini,'ask_ollama',side_effect=AssertionError('No live provider')),patch.object(mini,'structured_model_call',side_effect=AssertionError('No live provider')):
        result=unittest.TextTestRunner(stream=stream,verbosity=2).run(unittest.TestLoader().loadTestsFromNames(names))
    data={'tests_run':result.testsRun,'failures':[(str(t),s) for t,s in result.failures],
          'errors':[(str(t),s) for t,s in result.errors],'skipped':result.skipped,'successful':result.wasSuccessful(),
          'argv':sys.argv,'modules':names,'python':sys.version,
          'head':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
          'source_sha256':{n:hashlib.sha256((ROOT/n).read_bytes()).hexdigest() for n in ['mini.py','tests/test_verified_manifest_provenance.py','scripts/m0_manifest_checks.py']}}
    (out/'results.json').write_text(json.dumps(data,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:data[k] for k in ['tests_run','successful','modules']}))
    return int(not result.wasSuccessful())
if __name__=='__main__':raise SystemExit(main())
