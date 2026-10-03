# Experiment 6 — rkey_02

الخطة المعتمدة: `465262cd697d45053c410406edb607373e771ddf06568ef752b11e4646185d43`

| المقياس | current | resolved |
|---|---:|---:|
| Worker بدأ | نعم | نعم |
| أول تعديل قانوني: خطوة | 5 | 5 |
| استدعاءات Repairer | 1 | 0 |
| Child متحقق | لا | لا |
| Root متحقق | لا | لا |
| خرق النطاق | 0 | 0 |
| خرق preservation | 0 | 0 |
| حالة التشغيل | failed | failed |

## current

- أول توقف: `CHILD_VERIFICATION` / `CONTEXT_INSUFFICIENT`
- npm preflight: `[]`
- browser verifier: `[]`
- تصنيف التحقق: `[]`
- candidate patch محفوظ: `لا`
- {"role": "Falsifier", "tool": "run_command", "target": "echo \"Testing R key logic...\"", "status": "failed", "result": "error: command refused: executable 'echo' is not in the verification allowlist"}

## resolved

- أول توقف: `CHILD_VERIFICATION` / `VERIFIER_UNAVAILABLE`
- npm preflight: `[]`
- browser verifier: `[{'task_id': 'EXEC-001', 'status': 'VERIFIER_UNAVAILABLE', 'resolved_entrypoint': 'index.html', 'failure_codes': ['missing_game_bridge', 'missing_interaction', 'missing_interaction', 'missing_interaction', 'missing_interaction']}]`
- تصنيف التحقق: `[{'task_id': 'EXEC-001', 'status': 'VERIFIER_UNAVAILABLE', 'gate_checks': ['browser_contract', 'verification_aggregation']}]`
- candidate patch محفوظ: `نعم`

## Deterministic npm probe

- {"policy": "current", "result": "tool error: [WinError 2] The system cannot find the file specified", "preflight": [], "command_results": []}
- {"policy": "resolved", "result": "[not_applicable] VERIFICATION_NOT_APPLICABLE: package.json is absent", "preflight": [{"command": "npm test", "status": "VERIFICATION_NOT_APPLICABLE", "reason": "package.json is absent", "resolved_executable": null}], "command_results": []}

فشل أو تعذر التحقق لا يعني صحة الـpatch؛ candidate المحفوظ غير متحقق منه.
