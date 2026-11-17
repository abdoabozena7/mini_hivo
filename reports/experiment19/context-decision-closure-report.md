# Experiment 19 — Mandatory Context Decision Closure

مقارنة Python على نفس العقد والموديل و28 خطوة؛ Experiment 18 guard ثابت. المتغير الوحيد هو إغلاق قرار السياق بعد inspection.

| المسار | أول tool | قرار context | أول legal mutation | Verification PASS | Root verified | missing exits |
|---|---:|---:|---:|---:|---:|---:|
| current guard | 3/3 | 0/3 | 0/3 | 0/3 | 0/3 | 0 |
| closure guard | 3/3 | 0/3 | 0/3 | 0/3 | 0/3 | 3 |

## Safety وموضع التوقف

- current guard: decision statuses={}; reanchors=0; filtered empty Builder responses=0; model calls=15; elapsed seconds=78.46; Repairer calls=0; missing sources={}; unsupported sufficient authorizations=0; first blockers={'CONTEXT_INSUFFICIENT': 3}
- closure guard: decision statuses={}; reanchors=3; filtered empty Builder responses=9; model calls=27; elapsed seconds=465.55; Repairer calls=0; missing sources={'empty_model_response_after_reanchor': 3}; unsupported sufficient authorizations=0; first blockers={'CONTEXT_DECISION_MISSING': 3}

Scope/preservation counters: 0. Protected tests unchanged: yes.
فحص false sufficient هنا يغطي التفويض رغم evidence فارغة أو متناقضة أو semantic status غير محسوم. بدون behavior verification لا يمكن الجزم بصحة كل قرار sufficient دلاليًا.
لم يُقدَّم أي قرار sufficient في التشغيلات الستة، لذا false-sufficient rate غير قابل للحساب من الـfresh runs؛ الاختبارات المباشرة تثبت رفض claim كاذب عند وجود أدلة متعارضة.

## القرار

فرضية رفع معدل قرار السياق لم تتأكد في هذه العينة: 0/3 في المسارين. الحارس الجديد حسّن تصنيف أول عائق فقط، وتسبب في model calls ووقت إضافيين؛ لذلك يبقى تجريبيًا ولا يتحول إلى default.
العقود معتمدة مسبقًا؛ التخطيط الحر غير مقاس. 3 محاولات لكل مسار لا تقدر reliability العامة.

[Raw results](C:/Users/A-plus/.codex/worktrees/experiment17-18/mini_hivo/reports/experiment19/experiment19-results.json)
