"""Fresh controlled chain after the provenance correction; never invent root success."""
import argparse,hashlib,json,sys
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'scripts')]
import mini
from m0_characterize import chain,dump,digest

def main():
    p=argparse.ArgumentParser();p.add_argument('--output-dir',type=Path,required=True);a=p.parse_args()
    out=a.output_dir.resolve();out.mkdir(parents=True,exist_ok=False)
    baseline=ROOT/'output/m0-characterization/20261120-canonical-005/provenance.json'
    old=json.loads(baseline.read_text());source=old['source_contract'];browser=Path(old['browser_executable'])
    mini._load_optional_imports()
    with patch.object(mini,'browser_launch_kwargs',return_value={'headless':True,'executable_path':str(browser)}),patch.object(mini,'ask_ollama',side_effect=AssertionError('No unscripted provider')),patch.object(mini,'structured_model_call',side_effect=mini.StructuredOutputError('M0 bounded planner stop')),patch.object(mini,'http_post_json',side_effect=AssertionError('No provider HTTP')),patch.object(mini,'http_get_json',side_effect=AssertionError('No provider HTTP')):
        result=chain(out,source,'full',browser,supply_syntax=True)
    before=json.loads((out/'chain_full/manifests-before-parent.json').read_text())
    preflight=json.loads((out/'chain_full/parent-preflights.json').read_text())[0]
    first_before=before[0]['manifest'];first_after=preflight['child_info'][0]['integration_manifest']
    checks={'children_accepted':all(x['result']['status']=='done' for x in result['children']),
        'independent_behavior':result['independent_behavior']['passed'],
        'foundation_attribution_unchanged':first_before==first_after,
        'no_false_duplicate_owner':not any(c['kind']=='duplicate_child_symbol' for c in preflight['result']['conflicts']),
        'parent_scope_remains_blocking':result['parent_result']['status']=='failed' and 'IMPACT_CONTRACT_INCOMPLETE' in result['parent_result']['summary'],
        'retained_successor_bytes':all(digest(out/'chain_full/workspace'/n)==h for n,h in result['children'][1]['after'].items())}
    dump(out/'results.json',{'checks':checks,'successful':all(checks.values()),'chain_result':result,
        'head':old['head'],'python':sys.version,'argv':sys.argv,
        'source_sha256':{n:digest(ROOT/n) for n in ['mini.py','scripts/m0_manifest_functional.py','scripts/m0_characterize.py']},
        'scope':'Scripted model choices; real scheduler, tools, authorization, transactions, browser and parent path. Root remains failed.'})
    print(json.dumps(checks));return int(not all(checks.values()))
if __name__=='__main__':raise SystemExit(main())
