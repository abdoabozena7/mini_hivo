# Experiment 10 — Child Verification Handoff Stability

حالة واحدة ثابتة، و5 إعادات لحدّ التحقق، من غير إعادة Worker أو Falsifier أو Repairer.
Input mode: `historical_compact_projection`.
الحالات مأخوذة من الأرشيف؛ نتائج الأدوات محفوظة مختصرة.
دي تجربة تشخيصية؛ إصدار receipt والـcommit والـParent integration لم يُعاد تشغيلهم.

| المرحلة | الوصول |
|---|---:|
| Target resolved | 5/5 (100%) |
| Verification applicable | 5/5 (100%) |
| Existing Worker context sufficient | 5/5 (100%) |
| Verification started | 5/5 (100%) |
| Fresh behavioral PASS | 5/5 (100%) |
| Evidence gate accepted | 0/5 (0%) |

- Behavior checks: 20/20 (100%)
- Same source/input hashes: True
- Same gate decision: True
- First blocker: `{'stage': 'VERIFICATION_EVIDENCE_AGGREGATION', 'reason': 'INVALID_RECEIPT'}`
- Browser related tools: `['run_file', 'run_file', 'run_file']`; matched tools: `[]`
- Separate fresh Browser PASS: True
- Model / Repairer calls: 0 / 0
- Receipts issued: 0; gate bypasses: 0
- Source unchanged: True

## أول سبب في التشغيلين الأصليين

- `20260928T084006-f38f1d1b`: Browser PASS ثم `INVALID_RECEIPT` في evidence aggregation.
  - النهاية المعلنة: `VERIFICATION_NOT_APPLICABLE`؛ Repairer started: False.
- `20260928T084614-07b8ff93`: Browser PASS ثم `INVALID_RECEIPT` في evidence aggregation.
  - النهاية المعلنة: `CONTEXT_INSUFFICIENT`؛ Repairer started: True.

## النتيجة

الـChild المؤهل يصل لبدء التحقق بشكل ثابت. الفشل المشترك يأتي بعد Browser PASS، عند مطابقة أدلة الـBrowser.
أدلة run_file المرتبطة بنفس target لا تطابق verify_web_app؛ existing aggregator يعطيها أولوية تجعل route = INVALID_RECEIPT.
NOT_APPLICABLE وCONTEXT_INSUFFICIENT في التشغيلين الأصليين نهايتان لاحقتان لنفس الرفض الأول؛ مش دليل على عدم استقرار applicability أو Worker context.
لم يتم إصلاح القرار في هذه التجربة. النتيجة تخص حالة واحدة؛ الإعادات لا تقيس end-to-end reliability.
