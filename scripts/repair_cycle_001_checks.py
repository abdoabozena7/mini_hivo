"""Selected offline repair checks; blocks shared runtime model calls."""
import argparse, hashlib, json, subprocess, sys, unittest
from pathlib import Path
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tests')]
MODULES=[
    'test_repair_cycle_001', 'test_project_mode_intent', 'test_greenfield_context_progress',
    'test_greenfield_impact_lifecycle', 'test_pre_mutation_impact', 'test_context_sufficiency_gate',
    'test_dependency_aware_scheduler', 'test_repair_impact_anchor', 'test_project_understanding',
    'test_ingestion_integration', 'test_semantic_evidence_resolver', 'test_project_world_model',
    'test_execution_contracts', 'test_core_integration', 'test_verified_child_integration',
    'test_impact_planning', 'test_impact_map_contract', 'test_verification_outcome_integrity',
    'test_experiment20_child_scope', 'test_authority_fail_closed', 'test_authority_drift',
    'test_adaptive_architecture', 'test_run4_scope_regression',
    'test_browser_requirement_authority',
]
def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path)
    args=parser.parse_args()
    if args.output and args.output.exists(): parser.error('Choose a new output path; evidence is never overwritten')
    import mini
    with patch.object(mini,'ask_ollama',side_effect=AssertionError('Live inference forbidden')), patch.object(mini,'structured_model_call',side_effect=AssertionError('Live inference forbidden')):
        result=unittest.TextTestRunner(verbosity=2).run(unittest.TestLoader().loadTestsFromNames(MODULES))
    data={'scope':'selected offline integration/regression cohort; not live E2E or full suite','modules':MODULES,'tests_run':result.testsRun,'failures':[str(t) for t,_ in result.failures],'errors':[str(t) for t,_ in result.errors],'skipped':[[str(t),reason] for t,reason in result.skipped],'successful':result.wasSuccessful(),'runtime_sha256':{p:hashlib.sha256((ROOT/p).read_bytes()).hexdigest() for p in ['mini.py','hivo/project_understanding.py','hivo/semantic_evidence.py','hivo/verification_scope.py']}}
    if args.output:
        with args.output.open('x',encoding='utf-8',newline='\n') as out: out.write(json.dumps(data,indent=2)+'\n')
    else: print(json.dumps(data,indent=2))
    return int(not result.wasSuccessful())
if __name__=='__main__': raise SystemExit(main())
