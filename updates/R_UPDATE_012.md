# R_UPDATE_012 — Preserve explicit model-option and reasoning intent

## A. Identification
2026-11-27, Africa/Cairo. VERIFIED offline/configuration scope. Branch `rodina/dev-turn-2026-11-20`, base `ef08b09708a295d5765d4c207141aa8a11d85f72` plus preserved local work. No containing commit/PR. [Source identities/results](../docs/worklogs/rodina/2026-11-27_model-configuration-fixes/results.json).
## B. Original problem
JSON conflicts depended on exact strings in global sys.argv. Equals-form settings escaped rejection; embedded callers could be affected by unrelated arguments. Cloud menu selection discarded an explicitly requested reasoning mode.
## C. Why necessary
Argument spelling/process embedding must not change configuration intent. Provider changes must not silently remove requested behavior.
## D. Root cause
`model_configuration.configure` searched raw process tokens, not parser assignments. `_choose_model` conditionally replaced cloud reasoning with None before capability admission.
## E. Changes
`hivo/model_configuration.py`: ModelSettingAction records explicitly assigned destination names; supplied_model_settings validates provenance. Without parser metadata, programmatically supplied setting properties are explicit. Full default namespaces may mark provenance empty. `_choose_model` retains reasoning for all providers and uses existing capability admission. `mini.py::parse_args(argv=None)` supports explicit argument vectors and tracks the seven setting options. New focused tests; provider adapter/free policy unchanged.
## F. Mechanism
Both '--flag value' and '--flag=value' invoke the same argparse action, even if value equals its default. JSON+explicit setting conflicts fail before provider access. Parser defaults are not explicit. No model/provider fallback was introduced. Existing capability checks reject unsupported requested controls.
## G. Functional verification
Real parser -> temporary on-disk JSON -> actual configure/selection objects: both spellings of seven settings reject consistently; default JSON loads; programmatic explicit defaults reject; unrelated host argv is ignored; supported reasoning persists and unsupported choices produce REASONING_CONTROL_UNSUPPORTED. Catalogue/metadata are scripted, HTTP transport fails closed in tests. This is controlled configuration proof, not model readiness.
## H. Additional tests
Final affected cohort:91 methods, zero failures/errors/skips, exit0. Includes10 new configuration methods plus routing, CLI migration, provider and startup checks. Do not sum overlapping earlier cohorts.
## I. Failures and compatibility
Baseline002:7 methods,10 failure records plus1 error; subtests account for multiple records. Baseline001 retained a helper whose argv scope also exposed embedding coupling; baseline002 keeps argv active for realistic CLI reproduction. Intermediate checks001:88 pass. Legacy parse_args() remains supported; new argv parameter is optional. Programmatic namespaces with explicit setting properties conflict with JSON unless those properties are explicitly marked as default-derived via model_options_provided. Safe CLI errors still avoid echoing secrets.
## J. Impact
Explicit intent is stable across syntax, embedding and provider selection. No cloud call or free-policy change occurred.
## K. Limits
Metadata compatibility is not live reasoning support; actual provider response/canary checks remain mandatory. This does not add residency coordination or alter workflow-selection policy.
## L. Evidence and commands
Private originals: `output/prioritized-handoff/20261127-phase-b-{baseline-001,baseline-002,checks-001,checks-final-001}`. Curated outcomes/source hashes linked above are working-tree identities, not staged blobs. Executed final command (choose a new directory when rerunning):
```powershell
.venv/Scripts/python.exe -B -X utf8 scripts/acceptance_phase_checks.py --output-dir output/prioritized-handoff/20261127-phase-b-checks-final-001 test_model_configuration_fixes test_model_routing test_provider_cli_migration test_providers test_host_preflight
```
## M. Team summary
Proposed PR title: Track explicit model settings and retain requested reasoning.91 focused offline methods pass; live providers NOT TESTED. Builds On R010/R011 and the November27 audit. Rule Proposal: None. Local/uncommitted; no publication.
