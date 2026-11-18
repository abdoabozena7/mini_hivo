# Experiment 10 — Child Verification Handoff Stability

حالة واحدة ثابتة، و5 إعادات لحدّ التحقق، من غير إعادة Worker أو Falsifier أو Repairer.
Input mode: `full_pre_browser_handoff`.
مدخلات gate محفوظة مباشرة بعد Falsifier وقبل Browser كما هي، دون اختصار إضافي أثناء التسجيل.
دي تجربة تشخيصية؛ إصدار receipt والـcommit والـParent integration لم يُعاد تشغيلهم.

| المرحلة | الوصول |
|---|---:|
| Target resolved | 5/5 (100%) |
| Verification applicable | 5/5 (100%) |
| Existing Worker context sufficient | 5/5 (100%) |
| Verification started | 5/5 (100%) |
| Fresh behavioral PASS | 5/5 (100%) |
| Evidence gate accepted | 5/5 (100%) |

- Behavior checks: 20/20 (100%)
- Same source/input hashes: True
- Same gate decision: True
- First blocker: `None`
- Browser related tools: `['run_file', 'run_file', 'run_file', 'verify_web_app']`; matched tools: `['verify_web_app']`
- Separate fresh Browser PASS: True
- Model / Repairer calls: 0 / 0
- Receipts issued: 0; gate bypasses: 0
- Source unchanged: True

## أول سبب في التشغيلين الأصليين

- `20260928T084006-f38f1d1b`: Browser PASS ثم `INVALID_RECEIPT` في evidence aggregation.
  - النهاية المعلنة: `VERIFICATION_NOT_APPLICABLE`؛ Repairer started: False.
- `20260928T084614-07b8ff93`: Browser PASS ثم `INVALID_RECEIPT` في evidence aggregation.
  - النهاية المعلنة: `CONTEXT_INSUFFICIENT`؛ Repairer started: True.

## إعادات الحالة التاريخية المختصرة

- Input mode: `historical_compact_projection`; decision consistent: True
- Verification started: 5/5 (100%)
- Evidence gate accepted: 0/5 (0%)
- First blocker: `{'stage': 'VERIFICATION_EVIDENCE_AGGREGATION', 'reason': 'INVALID_RECEIPT'}`
- نفس bytes للـcandidate، لكن هذه الحالة تستعمل مدخلات أدوات مختصرة من الأرشيف.

## التشغيل الجديد الذي سجّل الحالة الكاملة

- ROOT_VERIFIED: True; status: done
- Valid verified child: 1
- Repairer calls: 0
- Scope / preservation violations: 0 / 0
- Plan hash: `465262cd697d45053c410406edb607373e771ddf06568ef752b11e4646185d43`
- تشغيل جديد واحد مع تسجيل observational؛ النتيجة لا تعني إن سبب الرفض اتصلح أو إن reliability = 100%.

## النتيجة

مدخلات الحالة الكاملة اجتازت verification handoff في كل الإعادات.
الحالة الكاملة تحتوي verify_web_app evidence من الـFalsifier؛ الحالة التاريخية المرفوضة تحتوي run_file لنفس target دون evidence مطابقة لأداة Browser.
القرار ثابت داخل كل حالة. الاختلاف بين الحالات في protocol/projection للأدلة، ويظهر أولًا في aggregation بعد تنفيذ Browser ناجح.
لم يتم إصلاح القرار في هذه التجربة. النتيجة تخص حالة واحدة؛ الإعادات لا تقيس end-to-end reliability.
