# Experiment 11 — Semantic Evidence Compatibility

## المقارنة على نفس الحالة القديمة

نفس approved contract ونفس candidate patch، مع اختبار Browser جديد في كل مسار.

| المسار | اختبار behavior | Evidence gate | Verified Child Receipt |
|---|---|---|---|
| current | PASS | INVALID_RECEIPT | False |
| compatible | PASS | PASS | True |

## المحاولات الجديدة من البداية للنهاية

| المحاولة | Worker | Child verified | Parent test جديد | Root verified | أول blocker |
|---|---|---|---|---|---|
| fresh-1 | True | 1 | True | True | لا يوجد |
| fresh-2 | True | 1 | True | True | لا يوجد |
| fresh-3 | True | 1 | True | True | لا يوجد |

## النسب

| القياس | النتيجة |
|---|---|
| الوصول للـWorker | 3/3 (100%) |
| اختبار Child سلوكي ناجح | 3/3 (100%) |
| قبول الأدلة المتوافقة | 3/3 (100%) |
| الحفاظ على تغطية NODE-001 | 3/3 (100%) |
| تنفيذ اختبار Parent جديد | 3/3 (100%) |
| نجاح Root | 3/3 (100%) |
| Receipts صحيحة / CHILD_VERIFIED | 3/3 (100%) |

مخالفات scope/preservation المسجلة: **0**.
استدعاءات Repairer: **0**. إعادة استخدام child proof بدل parent proof: **0**.

## اختبارات قبول ورفض الأدلة

- أدوات مختلفة لنفس requirement/target/assertions: ACCEPT.
- نفس الملف مع behavior مختلف، أو target/requirement/input مختلف: REJECT.
- Page-load فقط، evidence قديمة، interaction لم ينفذ، أو terminal case فاشلة: REJECT.
- Approved authority/direct oracle/scope/impact gates: الاختبارات الحالية مستمرة.

## حدود الاستنتاج وإعادة التشغيل

هذه محاولات متكررة لمهمة R-key واحدة؛ النسب لا تمثل كل مشاريع HIVO.
الاختبار المجمد يعزل سبب aggregation. المحاولات الجديدة تختبر السلسلة كاملة، وتشمل أي فشل سابق للتحقق في المقام.
الأرشيف القديم يحتفظ بنتائج tools مختصرة. تمت استعادة accepted Impact Contract من capture لاحقة بعد مطابقة hash مع authorization القديمة، ومطابقة execution contract وcontext anchor وsource bytes.
المقارنة المجمدة لا تتضمن Worker/Falsifier أو Parent جديدين؛ الـBrowser جديد والـimpact/commit/receipt seam فعلي.
اختلف hash لملف mini.py أثناء تجهيز helper لإعادة دخول نفس post-verification block؛ تفاصيل hash محفوظة لكل محاولة. منطق block والـWorker والـverification والـintegration لم يتغير.

تفاصيل كل run والسياسات وhashes وreceipt validation موجودة في ملف JSON المجاور.

## ملفات الأدلة

- [Frozen comparison](D:/projects/Ai/mini_hivo_experiment11/rkey_01/frozen-comparison/comparison.json)
- [fresh-1](D:/projects/Ai/mini_hivo_experiment11/rkey_01/fresh-1/.agent_experiment.jsonl)
- [fresh-2](D:/projects/Ai/mini_hivo_experiment11/rkey_01/fresh-2/.agent_experiment.jsonl)
- [fresh-3](D:/projects/Ai/mini_hivo_experiment11/rkey_01/fresh-3/.agent_experiment.jsonl)
