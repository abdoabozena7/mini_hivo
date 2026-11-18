# Experiment 8 — Atomic Verified Child Receipt

المقارنة المعزولة تستخدم نفس patch ونفس دليل نجاح Child المحفوظ من Experiment 7.
النسب تخص حالة R-key واحدة، وليست تقديرًا لأداء HIVO عمومًا.

| المقياس | current | atomic_verified |
|---|---:|---:|
| Receipts صالحة لكل Child ناجح | 0/1 (0%) | 1/1 (100%) |
| حفظ تغطية الـnodes | 0/1 (0%) | 1/1 (100%) |
| مطابقة hash الدليل | N/A | 1/1 (100%) |
| جاهزية Integration | NOT_READY | READY |

- نفس candidate SHA-256: `4ad2bdaf3edd59687e504c5c543d1c694c038aaa1a85e3e6c244a049f70f475c`
- Nodes وصلت للـParent: `['NODE-001']`
- لا توجد استدعاءات model أو تعديل source أثناء replay.

## إعادة HIVO الفعلية

- CHILD_VERIFIED: 1
- Receipts صالحة / children verified: 1/1 (100%)
- Hash event/receipt/evidence: 1/1 (100%)
- Coverage: 1/1 (100%); nodes: `['NODE-001']`
- Integration: `READY` / `None`
- ROOT_VERIFIED: False
- First blocker: `{'stage': 'PARENT_INTEGRATION', 'reason': 'INTEGRATION_FAILED', 'detail': 'required integration target is unresolved'}`
- Repairer: 0
- Scope / preservation violations: 0 / 0

## حدود النتيجة

نجاح replay يثبت إصلاح تسليم الدليل والتغطية إلى بوابة integration القائمة.
ROOT_VERIFIED يُقاس فقط من الإعادة الفعلية. منطق integration والـVerifier والـWorker لم يتغيروا.
