# Experiment 14 — Strict Aggregation Compatibility

3 مهام × 3 محاولات جديدة × سياستين = 18 محاولة. نفس gemma4:e4b و28 خطوة وعقود Experiment 13.

المتغير الوحيد: aggregation matching. بوابة final receipt والـWorker والـgrounding والـVerifier والـintegration ثابتة. default ما زال current.

## الأدلة: أول طبقة مقابل آخر طبقة

| المقياس | monotonic | strict |
|---|---:|---:|
| False aggregation accepts | 9/12 (75%) | 0/12 (0%) |
| Final false accepts | 0/12 (0%) | 0/12 (0%) |
| Positive evidence accepted | 9/10 (90%) | 9/10 (90%) |

الأدلة الصحيحة القديمة محفوظة: current **7/7 (100%)**، monotonic **9/9 (100%)**.

UNKNOWN لا يساوي MATCH. Browser يحتاج كل assertions المطلوبة منفذة على نفس surface؛ نجاح تحميل الصفحة وحده لا يكفي. Node يقبل نتيجة تنفيذ فعلية لـsuite المحددة في route المعتمدة، التي تربط obligation بالـbehavior. لا يعتمد على كلمة tests أو path داخل stdout.

الـprovenance موثقة ومقيدة بقنوات التنفيذ المعروفة؛ unit_test_result alias غير المدعومة تظل مرفوضة كما قبل التجربة. ليست regression جديدة.

هذه حالات protocol معلنة وليست تقديرًا لمعدل الأخطاء الميداني. الاختبارات البديلة للـbehavior والـtarget منفذة بالفعل؛ تغيير provenance/requirement جزء معلن من إعادة تشغيل البروتوكول.

## نفس post-child state

| المهمة | monotonic child | strict child |
|---|---:|---:|
| arena_arrow | 2/2 (100%) | 2/2 (100%) |
| arena_q_restart | 3/3 (100%) | 3/3 (100%) |
| node_unique | 3/3 (100%) | 3/3 (100%) |

نفس input hashes: **True**. كل Worker مكتملة من Exp13 monotonic أُعيدت دون اختيار حسب PASS، مع Browser جديد وتأكيد Node suite فعلية. هذا القياس لا يدّعي Worker أو Root جديدين.

## المحاولات الجديدة

| المقياس | monotonic | strict |
|---|---:|---:|
| Valid receipt / actual PASS | 9/9 (100%) | 9/9 (100%) |
| Child verified | 9/9 (100%) | 9/9 (100%) |
| Root verified | 9/9 (100%) | 9/9 (100%) |
| Receipt rejection / actual PASS | 0/9 (0%) | 0/9 (0%) |
| Runs using Repairer | 0/9 (0%) | 0/9 (0%) |
| Model calls / Root success | 11.11 | 11.11 |
| Seconds / Root success | 58.63 | 59.54 |

| المهمة | monotonic Root | strict Root |
|---|---:|---:|
| arena_arrow | 3/3 (100%) | 3/3 (100%) |
| arena_q_restart | 3/3 (100%) | 3/3 (100%) |
| node_unique | 3/3 (100%) | 3/3 (100%) |

تكاليف كل المحاولات الفاشلة داخلة في calls/time لكل Root ناجحة. التخطيط وhost preflight خارج حدود القياس. نجاح Root يتطلب parent verification جديدة تغطي requirement؛ child evidence لم تُستخدم كبديل.

Scope/preservation: monotonic=0, strict=0. Read-only tests changed: monotonic=0, strict=0.

## القرار وحدود القياس

Hypothesis confirmed on tested sample: **True**.

strict تظل experimental اختيارية. العينة صغيرة؛ لا تعميم على wrappers أو verifier protocols غير المدعومة أو على Timer/Python المستبعدتين upstream. mutation grounding لم يتغير، وأي فشل قبل verification يظل داخل denominator.

نسخة التطوير v1 كشفت artifact فارغة من browser غير applicable عند Node؛ أُصلح توليدها في aggregation فقط. v1 محفوظة، والمحاولات التجريبية الموقوفة لا تُخلط مع الـ18 محاولة المكتملة بعد تثبيت v2.

- [Results](D:/projects/Ai/mini_hivo/reports/experiment14/experiment14-results.json).
- [Preregistered suite](D:/projects/Ai/mini_hivo_experiment14/suite-v2/manifest.json).
- [Protocol evidence](D:/projects/Ai/mini_hivo_experiment14/evidence-v2/comparison.json).
- [Paired handoffs](D:/projects/Ai/mini_hivo_experiment14/handoffs-v2/comparison.json).
