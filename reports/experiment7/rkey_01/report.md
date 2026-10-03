# Experiment 7 — Verification Surface Discovery

المقارنة الأساسية تستخدم نفس candidate byte-for-byte؛ الملف الأصلي ضابط سلبي للاختبار.

| المقياس | current candidate | discovery candidate | original discovery |
|---|---:|---:|---:|
| نوع سطح التحقق | — | existing_app_hook | existing_app_hook |
| الواجهة المختارة | — | __HOPLINE__ | __HOPLINE__ |
| اختبار سلوكي نُفذ | لا | نعم | نعم |
| التصنيف | VERIFIER_UNAVAILABLE | PASS | TEST_FAILED |
| النتيجة | لا | نعم | لا |

## اختبارات السلوك

| الاختبار | candidate | original |
|---|---:|---:|
| keyboard_movement | نعم | نعم |
| restart_resets_state | نعم | لا |
| goal_win_state | نعم | نعم |
| touch_control | نعم | نعم |

## HIVO live runs

### Run 1

- أول تعديل قانوني: الخطوة 5
- candidate hash: `['4ad2bdaf3edd59687e504c5c543d1c694c038aaa1a85e3e6c244a049f70f475c']`
- final source hash: `3d031b1f28499a3bf0fc3f0f5bbac6521476e566373ad22ea75b2ab72293c661`
- browser: `[{'task_id': 'EXEC-001', 'status': 'VERIFIER_UNAVAILABLE', 'resolved_entrypoint': 'index.html', 'surface_type': None, 'behavior_test_executed': False, 'failure_codes': []}]`
- Repairer calls: 0
- Child verified: لا
- Child receipt verified: لا
- Integration readiness: `NOT_READY_CHILD_FAILURE`
- Missing integration coverage: `['NODE-001']`
- Root verified: لا
- أول توقف: `{'stage': 'CHILD_VERIFICATION', 'reason': 'VERIFIER_UNAVAILABLE', 'detail': 'verification failed: VERIFIER_UNAVAILABLE'}`
- Scope / preservation violations: 0 / 0

### Run 2

- أول تعديل قانوني: الخطوة 5
- candidate hash: `[]`
- final source hash: `4ad2bdaf3edd59687e504c5c543d1c694c038aaa1a85e3e6c244a049f70f475c`
- browser: `[{'task_id': 'EXEC-001', 'status': 'PASS', 'resolved_entrypoint': 'index.html', 'surface_type': 'existing_app_hook', 'behavior_test_executed': True, 'failure_codes': []}]`
- Repairer calls: 0
- Child verified: نعم
- Child receipt verified: لا
- Integration readiness: `NOT_READY_CHILD_UNVERIFIED`
- Missing integration coverage: `['NODE-001']`
- Root verified: لا
- أول توقف: `{'stage': 'PARENT_INTEGRATION', 'reason': 'INTEGRATION_NOT_READY', 'detail': 'approved plan execution graph is not ready for parent integration'}`
- Scope / preservation violations: 0 / 0
