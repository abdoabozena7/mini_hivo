# Experiment 15 — Mutation Grounding / Evidence-to-Edit Binding

3 مهام × 3 fresh runs × سياستين = 18 محاولة. gemma4:e4b، 28 خطوة، strict ثابتة. نفس عقود وبذور Experiment 14.

التغيير الوحيد: full read مطابقة للملف الحالي إذا كان ≤80 سطرًا تحتسب bounded refresh. لا fuzzy replacement، ولا زيادة retries أو budget. Refresh لا تفتح full-file write أو multiple replacements.

## تصحيح تشخيص الحالة الأصلية

Exp13 arena_arrow monotonic-3 نفّذت تعديلين قانونيين؛ أول تعديل عند الخطوة 3، ثم فشلت عند تعديل لاحق بالخطوة 9. full reread لم تسجل refresh، لأنها كانت تقبل read_file_range فقط.

الـold/new الكاملة لآخر محاولة مرفوضة غير محفوظة. لا ندّعي إعادة حرفية أو إثبات إصلاح الـpatch الأصلي. فحص البروتوكول يعيد نوع حالة الربط بأدلة وطلبات مرجعية معلنة.

## فحص الربط المعزول

| المقياس | evidence_grounded | evidence_bound |
|---|---:|---:|
| Legal mutation / positive challenges | 3/9 (33.33%) | 9/9 (100%) |
| False authorizations | 0/24 (0%) | 0/24 (0%) |
| Correct source region / applied | 3/3 (100%) | 9/9 (100%) |
| Native verification / applied | 3/3 (100%) | 9/9 (100%) |

نفس input hashes: **True**. الإيجابيات تشمل missing/stale anchor مع full read صغيرة وrange control؛ السلبيات تشمل fake/stale reads وold غير موجود وduplicate anchor وwrong region وlarge full read وforeign target وfull rewrite أثناء retry.

Scope counters تخص ملفات المشروع وread-only tests؛ controller logs/databases هي instrumentation. النسخة الأولى من حساب البروتوكول ضمّت logs ضمن scope/hash؛ binding-v2 تصحح المقام، دون أي تغيير في الإنتاج.

هذه حالات مصطنعة معلنة بلا model calls أو Worker/Root successes. كل تعديل مرجعي مقبول نفذته file tool الفعلية وتبعه browser/Node verification فعلية.

## الـWorker في المحاولات الجديدة

| المقياس | evidence_grounded | evidence_bound |
|---|---:|---:|
| Reached first legal mutation | 9/9 (100%) | 9/9 (100%) |
| Grounding terminal failure | 0/9 (0%) | 0/9 (0%) |
| First mutation on true target region | 9/9 (100%) | 9/9 (100%) |
| Any mutation on true target region | 9/9 (100%) | 9/9 (100%) |
| Verification PASS after mutation | 9/9 (100%) | 9/9 (100%) |
| Child verified | 9/9 (100%) | 9/9 (100%) |
| Root verified | 9/9 (100%) | 9/9 (100%) |
| Runs using Repairer | 0/9 (0%) | 0/9 (0%) |
| New full-refresh path exercised | 0/9 (0%) | 1/9 (11.11%) |

Steps to first legal mutation: grounded=[3, 3, 3, 3, 3, 3, 4, 4, 4], bound=[3, 3, 3, 3, 3, 3, 4, 4, 4].

| المهمة | grounded Root | bound Root |
|---|---:|---:|
| arena_arrow | 3/3 (100%) | 3/3 (100%) |
| arena_q_restart | 3/3 (100%) | 3/3 (100%) |
| node_unique | 3/3 (100%) | 3/3 (100%) |

True region oracle في القياس فقط: keydown handler للألعاب، وuniqueValues body لـNode. ليست prompt أو authorization إضافية. الـdiff الفعلي يجب أن يمس المنطقة، وhash كل mutation المطبقة يُطابق fresh binding.

Scope/preservation: grounded=0, bound=0. Read-only tests changed: grounded=0, bound=0.

كل المحاولات تدخل المقام. أي توقف قبل verification باقٍ في Root denominator. Parent verification جديدة واجبة؛ child proof ليست بديلًا. Worker strategies/budgets/verifier/evidence/integration ثابتة بـsource/AST pins.

## القرار

binding fix confirmed in declared challenges; no fresh grounding failure reduction demonstrated

إصلاح binding المثبت في الحالات المعلنة منفصل عن تحسن الـfresh Worker؛ لا تُحوّل 3/9→9/9 في البروتوكول إلى نسبة نجاح ميدانية. evidence_bound اختيارية experimental؛ default mutation policy=current، وstrict لا تتغير.

العينة ثلاثة مشاريع صغيرة. لا تعميم على ملفات كبيرة أو upstream tasks مستبعدة. الاختبارات المركزة وregression: 145 ناجحة.

- [Results](D:/projects/Ai/mini_hivo/reports/experiment15/experiment15-results.json).
- [Preregistered suite](D:/projects/Ai/mini_hivo_experiment15/suite-v1/manifest.json).
- [Binding protocol](D:/projects/Ai/mini_hivo_experiment15/binding-v2/comparison.json).
