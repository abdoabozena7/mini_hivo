# Experiment 13 — Monotonic Semantic Compatibility

3 مهام مؤهلة × 3 fresh runs × سياستين = 18 محاولة. gemma4:e4b، 28 خطوة، ونفس عقود Experiment 12.

المقارنة تبدأ من approved contract ثابتة؛ تكاليف التخطيط وpreflight مستبعدة. Timer وPython خارج حكم التجربة.

## النتائج الطازجة

| المقياس | current | monotonic |
|---|---:|---:|
| Valid receipt / actual PASS | 3/9 (33.33%) | 8/8 (100%) |
| Child verified | 3/9 (33.33%) | 8/9 (88.89%) |
| Root verified | 3/9 (33.33%) | 8/9 (88.89%) |
| False rejection / actual PASS | 6/9 (66.67%) | 0/8 (0%) |
| Runs using Repairer | 6/9 (66.67%) | 0/9 (0%) |
| Model calls / Root success | 35.33 | 11.25 |
| Seconds / Root success | 171.44 | 58.2 |

التكلفة تشمل المحاولات الفاشلة أيضًا، ثم تُقسم على Root successes.

| المهمة | current Root | monotonic Root |
|---|---:|---:|
| arena_arrow | 0/3 (0%) | 2/3 (66.67%) |
| arena_q_restart | 0/3 (0%) | 3/3 (100%) |
| node_unique | 3/3 (100%) | 3/3 (100%) |

## الحفاظ على الأدلة الصحيحة

Gold-correct current evidence preserved: **7/7 (100%)**. Different evidence final false accepts: **0/12 (0%)**.

منهج الاختيار: كل handoff من current انتهى Worker فيها، بدون اختيار بناءً على PASS. نفس input hash لكل السياسات، ثم تحقق Browser جديد أو إعادة تأكيد فعلية لاختبارات Node.

| نفس post-child state | current receipt | compatible receipt | monotonic receipt |
|---|---:|---:|---:|
| arena_arrow | 0/2 (0%) | 2/2 (100%) | 2/2 (100%) |
| arena_q_restart | 0/3 (0%) | 3/3 (100%) | 3/3 (100%) |
| node_unique | 3/3 (100%) | 0/3 (0%) | 3/3 (100%) |

هذا القياس لا يتضمن Worker جديدًا أو Root success؛ هو إثبات سببي للحفاظ على نفس الأدلة، منفصل عن الـ18 fresh runs.

## معنى monotonic في هذه التجربة

الحفاظ يخص الأدلة الصحيحة التي قبلها current. current نفسه قبل 9/12 أدلة خاطئة في مجموعة الهوية السلبية؛ لذلك الحفاظ الحرفي على كل قبول سابق يتعارض مع شرط صفر false accepts.

Matching يبدأ بـcurrent. النجاح الصحيح يظل مقبولًا، وغياب semantic inventory يصبح UNKNOWN، ولا يخلق سبب رفض مستقل. إن فشل matching فقط، يُجرب semantic rescue عند وجود metadata قابلة للمقارنة.

الـreceipt النهائية ترفض الهوية المخالفة المعلنة: requirement أو target أو behavior مختلف. المخزون المتاح يُعاد ربطه بالعقد ومتطلبات المهمة وhash المصدر الحالي. authority-bound/direct routes وscope/freshness/closure gates باقية.

الـaggregator ما زال يقبل **9/12 (75%)** من الحالات السلبية قبل رفض receipt. matching الخاص به لم يُشدَّد؛ Experiment 14 مؤجل.

Positive protocol fixtures تشمل provenance aliases مصطنعة معلنة، والبدائل Browser behaviors/targets منفذة فعليًا. ليست نسبة أخطاء ميدانية.

## القرار والملفات

All 18 complete: **True**. Same frozen inputs: **True**. Production component pins: **True**.

Scope/preservation counters: current=0, monotonic=0. Read-only tests changed: current=0, monotonic=0.

`monotonic` اختيار experimental جديد؛ default ما زال current، وcompatible القديمة باقية للمقارنة. لا يُدَّعى تعميم على مهام upstream مستبعدة أو على مشاريع لم تُختبر.

- [Machine-readable results](D:/projects/Ai/mini_hivo/reports/experiment13/experiment13-results.json).
- [Preregistered manifest](D:/projects/Ai/mini_hivo_experiment13/suite-v1/manifest.json).
- [Negative/positive evidence records](D:/projects/Ai/mini_hivo_experiment13/evidence-v1/comparison.json).
- [Exact handoff replays](D:/projects/Ai/mini_hivo_experiment13/handoffs-v1/comparison.json).
