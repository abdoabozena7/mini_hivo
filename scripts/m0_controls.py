"""Selected offline M0 boundary controls and decomposition coverage probe."""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'tests'),str(ROOT/'scripts')]
import mini
from m0_characterize import initialize, dump
from hivo import requirements as req

NAMES=[
 'test_repair_cycle_001.RepairCycleTests.test_decomposition_preserves_explicit_dependencies',
 'test_repair_cycle_001.RepairCycleTests.test_dependency_schema_rejects_forward_cycles_and_invalid_references',
 'test_repair_cycle_001.RepairCycleTests.test_decomposed_dependent_is_not_dispatched_after_rollback',
 'test_repair_cycle_001.RepairCycleTests.test_scheduler_refreshes_disk_context_after_commit_and_rollback',
 'test_repair_cycle_001.RepairCycleTests.test_real_dependency_source_resolves_context_without_authorizing_its_mutation',
 'test_repair_cycle_001.RepairCycleTests.test_explicit_empty_outer_scope_cannot_be_expanded_by_child',
 'test_repair_cycle_001.RepairCycleTests.test_explicit_required_target_is_not_downgraded_to_optional_scope',
 'test_run4_scope_regression.Run4ScopeRegressionTests.test_real_leaf_repairer_mutation_fresh_verification_and_commit',
 'test_run4_scope_regression.Run4ScopeRegressionTests.test_terminal_repairer_scope_failure_cannot_be_promoted_by_fresh_verification',
 'test_run4_scope_regression.Run4ScopeRegressionTests.test_scope_failure_rolls_back_provisional_valid_writes_without_verification_promotion',
 'test_verification_outcome_integrity.VerificationOutcomeIntegrityTests.test_other_target_pass_cannot_satisfy_required_route',
 'test_verification_outcome_integrity.VerificationOutcomeIntegrityTests.test_cached_route_pass_without_execution_evidence_is_not_proof',
 'test_verification_outcome_integrity.VerificationOutcomeIntegrityTests.test_incomplete_same_role_receipt_cannot_displace_failure',
]


def main():
    p=argparse.ArgumentParser();p.add_argument('--output-dir',type=Path,required=True);a=p.parse_args()
    out=a.output_dir.resolve();out.mkdir(parents=True,exist_ok=False)
    os.environ['PYTHONDONTWRITEBYTECODE']='1'
    tmp=out/'tmp';tmp.mkdir();os.environ['TEMP']=str(tmp);os.environ['TMP']=str(tmp)
    import tempfile
    tempfile.tempdir=str(tmp)
    raw=(ROOT/'tests/fixtures/new_application_requirements.txt').read_bytes()
    ledger=req.extract_source_requirements(raw.decode())
    source=mini.normalize_goal_contract(raw.decode(),mini._deterministic_contract_from_ledger(raw.decode(),ledger),source_ledger=ledger)
    initialize(out/'coverage-workspace',source)
    parent=mini.make_task('ROOT',source['goal'],done_when=source['requirements'])
    specs={'children':[
        {'goal':'Create the HTML page','done_when':['HTML loads'],'scope_hint':['index.html'],'depends_on':[]},
        {'goal':'Style the page','done_when':['Stylesheet loads'],'scope_hint':['style.css'],'depends_on':['1']}]}
    with patch.object(mini,'structured_model_call',return_value=specs), \
         patch.object(mini,'ask_ollama',side_effect=AssertionError('No live model')):
        children=mini.decompose_task(parent,source,mini.inspect_repository())
    dump(out/'coverage-probe.json',{'source_ledger':ledger,'scripted_model_plan':specs,
         'schema_validator_accepts':mini._children_validator(specs),'actual_children':children,
         'missing_file_owner':'app.js',
         'missing_behavior_owners':['add','toggle','delete','persistence'],
         'interpretation':'Incomplete model plan accepted by ordinary decomposition; no runtime root verdict inferred.'})
    with (out/'tests.log').open('x',encoding='utf-8') as stream, \
         patch.object(mini,'ask_ollama',side_effect=AssertionError('No live model')), \
         patch.object(mini,'structured_model_call',side_effect=AssertionError('No live model')), \
         patch.object(mini,'http_post_json',side_effect=AssertionError('No provider HTTP')), \
         patch.object(mini,'http_get_json',side_effect=AssertionError('No provider HTTP')):
        result=unittest.TextTestRunner(stream=stream,verbosity=2).run(unittest.TestLoader().loadTestsFromNames(NAMES))
    data={'names':NAMES,'tests_run':result.testsRun,'failures':[(str(t),s) for t,s in result.failures],
          'errors':[(str(t),s) for t,s in result.errors],'skipped':result.skipped,'successful':result.wasSuccessful(),
          'head':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
          'harness_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'argv':sys.argv,
          'python':sys.version,'scope':'Fresh selected offline controls; scripted replies and some injected scheduler failures; no live validation.'}
    dump(out/'results.json',data)
    print(json.dumps(data,indent=2))
    return int(not result.wasSuccessful())


if __name__=='__main__':raise SystemExit(main())
