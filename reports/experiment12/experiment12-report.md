# Experiment 12 — Generalization & Reliability

## النطاق الثابت

5 مهام × 3 fresh runs × سياستين = 30 محاولة. الموديل gemma4:e4b، وWorker budget = 28.

السياسة الإنتاجية لم تتغير. كل مهمة تبدأ من نفس approved contract في workspace نظيف، ثم تمر على Worker والتحقق والـreceipt والتكامل الأصليين.

القياس يبدأ من العقد المعتمد؛ التخطيط مثبت ومُستبعد من calls/time. لذلك هذه نتيجة execution-to-root وليست قياسًا للتخطيط من طلب حر.

## النتائج الفعلية

| المقياس | current | compatible |
|---|---:|---:|
| Verification PASS / fresh attempts | 8/15 (53.33%) | 8/15 (53.33%) |
| Valid receipt / Verification PASS | 3/8 (37.5%) | 5/8 (62.5%) |
| Child verified / fresh attempts | 3/15 (20%) | 5/15 (33.33%) |
| Root verified / fresh attempts | 3/15 (20%) | 5/15 (33.33%) |
| False rejection / actual PASS | 5/8 (62.5%) | 3/8 (37.5%) |
| Runs using Repairer | 5/15 (33.33%) | 0/15 (0%) |
| Repairer calls | 5 | 0 |
| Model calls / Root verified | 41.67 | 24.4 |
| Agent tool calls / Root verified | 28.33 | 17.4 |
| Seconds / Root verified | 216.47 | 129.39 |

التكلفة = مجموع تكلفة كل المحاولات، بما فيها الفشل، ÷ عدد Root verified؛ ليست متوسط تكلفة المحاولات الناجحة فقط.

### لكل مهمة

| المهمة | current Root | compatible Root | current receipt/PASS | compatible receipt/PASS |
|---|---:|---:|---:|---:|
| arena_arrow | 0/3 (0%) | 2/3 (66.67%) | 0/2 (0%) | 2/2 (100%) |
| arena_q_restart | 0/3 (0%) | 3/3 (100%) | 0/3 (0%) | 3/3 (100%) |
| timer_pause | 0/3 (0%) | 0/3 (0%) | N/A (0 cases) | N/A (0 cases) |
| python_clamp | 0/3 (0%) | 0/3 (0%) | N/A (0 cases) | N/A (0 cases) |
| node_unique | 3/3 (100%) | 0/3 (0%) | 3/3 (100%) | 0/3 (0%) |

المهام التي وصلت فعليًا إلى executable verification في المحاولات الطازجة: **3/5** (arena_arrow, arena_q_restart, node_unique).
Timer توقف عند mutation grounding، وPython عند pre-mutation impact. لذلك هذه العينة لا تحقق شرط 5–8 مهام مؤهلة من Worker؛ لا يُستنتج منها تعميم end-to-end على الخمس مهام.

قراءة الصفحة فقط، أو syntax-only، لا تُحسب behavior PASS. الـTimer يُحسب من before/after الفعلية حتى لو افتقد executed flag؛ نقص الـflag هو أحد الأشياء التي تختبرها التجربة.

## Same-child paired handoff

هذه إعادة تحقق جديدة لنفس post-child state تحت السياستين، بدون model أو Repairer. لا تدخل في fresh-run denominator ولا تثبت Root success.

| المهمة | current Child | compatible Child | نفس input hash |
|---|---|---|---|
| arena_arrow | False | True | True |
| arena_q_restart | False | True | True |
| node_unique | True | False | True |

اختيار handoff = أقدم Worker مكتمل لكل مهمة، وليس اختيار PASS. أي مهمة بدون Worker مكتمل تُذكر كغير مؤهلة لهذا القياس فقط.

## اختبارات قبول الأدلة المختلفة

مجموعة protocol مستقلة: نتائج reference verification حقيقية، مع أدلة behavior/target مختلفة وrecords requirement مختلفة عمدًا، وتبديل provenance معلن. ليست fresh model runs، ولا تُفسر كنسبة أخطاء ميدانية.

| المقياس | current | compatible |
|---|---:|---:|
| Final receipt false acceptance | 15/20 (75%) | 0/20 (0%) |
| False rejection of compatible reference | 5/17 (29.41%) | 11/17 (64.71%) |
| Aggregation false acceptance (before receipt) | 15/20 (75%) | 6/20 (30%) |

الـaggregation والـfinal receipt مقاسان منفصلان؛ رفض receipt لاحقًا لا يمحو قبول aggregation غير صحيح.

### تحقق reference جديد، 3 مرات لكل مهمة

هذه candidate patches صحيحة مستقلة عن Worker، ونُفِّذت اختبارات السلوك عليها فعليًا قبل تمرير الأدلة لكل سياسة. 15 native verifications، و30 paired policy evaluations؛ لا model calls ولا Root success من هذا القياس.

| المهمة | native PASS | current native receipt | compatible native receipt |
|---|---:|---:|---:|
| arena_arrow | 3/3 | 3/3 (100%) | 3/3 (100%) |
| arena_q_restart | 3/3 | 3/3 (100%) | 3/3 (100%) |
| timer_pause | 3/3 | 3/3 (100%) | 0/3 (0%) |
| python_clamp | 3/3 | 3/3 (100%) | 0/3 (0%) |
| node_unique | 3/3 | 3/3 (100%) | 0/3 (0%) |

اتفاق نتائج الـprotocol بين الدورات: **True**. تكرار نفس الحالات لا يجعلها 3 مجموعات مستقلة لتقدير نسبة الأخطاء في الاستخدام الحقيقي.

## السلامة والقرار

Production hashes unchanged: **True**. All 30 completed: **True**.

إجمالي مخالفات scope/preservation المسجلة: current=0, compatible=0. تفاصيل العدادات في JSON.
تعديلات ملفات الاختبارات المحمية: current=0, compatible=0.

لا تُرقَّى السياسة إلى default في هذه التجربة. التحسن في الألعاب لا يثبت تعميمًا على Timer أو unit/test evidence؛ النتائج التفصيلية تحدد حدود السياسة الحالية.

**سبب الرفض محدد:** Timer لا يخرج `behavior_test_executed` و`executed` التي يتطلبها normalizer. وفي unit routes تمرَّر `semantic_browser_evidence={}`، ثم يرفض validator الـinventory الفارغة. الـNode fresh run والـsame-child replay يؤكدان تراجعًا حقيقيًا: current ينجح وcompatible يرفض نفس الدليل الصحيح.
صفر final false accepts في compatible يصاحبه رفض أدلة صحيحة؛ لا يُعد ذلك وحده تعميمًا آمنًا. non-browser aggregation ما زال يقبل 6 حالات غير متوافقة من مجموعة الـprotocol، ثم يمنعها رفض الـreceipt الفارغة.

حجم العينة 3 لكل arm/task؛ ليس تقديرًا قويًا للموثوقية على مستودعات حقيقية. المسارات المستقلة تبدأ من authority معلومة، والألعاب توفر hooks موجودة مسبقًا.

## الملفات القابلة للمراجعة

- Manifest + seeds + frozen authority + full original observations: [suite](D:/projects/Ai/mini_hivo_experiment12/suite-v1).
- Machine-readable metrics: [experiment12-results.json](D:/projects/Ai/mini_hivo/reports/experiment12/experiment12-results.json).
- Protocol raw inputs and output: [matrix.json](D:/projects/Ai/mini_hivo_experiment12/evidence-matrix-v4/matrix.json).
