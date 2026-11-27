# من merge شغال إلى prompt بيطلع برنامج حقيقي

> [!WARNING]
> **HISTORICAL ARCHIVE — RETIRED v1 (DO NOT USE):** Mini Hivo is **v2 only**. This document preserves historical v1 (`mini.py` / `gemma4:e4b`) validation records only and is no longer used. For active v2 verification and benchmarks, see [`../README.md`](../README.md), [`BENCHMARKING_ARCHITECTURE.md`](BENCHMARKING_ARCHITECTURE.md), and [`worklogs/INDEX.md`](worklogs/INDEX.md).

تاريخ المتابعة: 2026-11-17. الطلب الجديد كان إننا نكمّل إصلاح المسارات اللي
لسه فاشلة لحد live end-to-end بنتيجة حقيقية. نقطة البداية هي `3b02b3e`،
بعد توحيد الفروع وحفظ كل الـ original commits. تفاصيل الدمج القديمة ونتايج
المحاولات السابقة فضلت كما هي في [تقرير الدمج](BRANCH_CONSOLIDATION.md).

المهمة دي مش إعادة تسمية لنجاح إصلاح الـ clamp على إنه نجاح إنشاء مشروع.
القبول بيبدأ بمجلد فاضي وprompt حقيقية على `gemma4:e4b`، وبينتهي بملفات
محفوظة بعد خروج الـ CLI، وبعدها برنامج مستقل يختبر الناتج. ولو الـ agent
قال `done` والناتج خالف الطلب، ده فشل في القبول مش نجاح جزئي بنخفي وراه العيب.

## المثال اللي فضل ثابت

أول حالة هي نفس greeting prompt اللي فشلت أثناء الدمج: إنشاء Python CLI،
واسم افتراضي `World`، واسم من arguments، وfunction عامة وunit tests.
الـ CLI لازم يطلع `Hello, Ada!` مع newline، والدالة ترجع نفس الـ greeting
من غير الـ newline فقط. حالة تانية تطلب CLI لضرب عددين مع رفض missing
وinvalid وextra arguments. والحالة الأبسط تطلب ملف يطبع `MERGE_OK`.

مفيش كود جاهز اتحط في project عشان الموديل يكمله. الـ prompts الأصلية
اتثبتت، والتشغيل الجديد بيبدأ من directories جديدة. الـ independent
acceptance script مش من كتابة الموديل، ومش ضمن الملفات اللي الـ Worker
بيعدلها.

## ليه نجاح الـ unit tests ما كانش كفاية؟

إحدى المحاولات وصلت فعلًا لـ `done`، والـ CLI اشتغل:

```text
python greet.py Ada
Hello, Ada!
```

لكن الفحص المستقل لقى إن الدالة بترجع `Hello, Ada` من غير علامة التعجب.
الأخطر إن الـ Builder عدّل الـ tests المولّدة لتقبل نفس الغلط. الـ tests
كانت بتقيس توافق الكود مع تفسير الموديل، مش توافق الاتنين مع الطلب.

عشان كده اتضاف حد قبول مصدره النص الأصلي: الأمثلة اللي بتقول
`python <file>.py ... prints exactly ... followed by a newline` تتحول
لاختبارات exact stdout. ولو فيه declaration صريحة لدالة one-string-parameter
بترجع **نفس** الناتج من غير newline، كل مثال يتربط باستدعاء الدالة المقابل.
التوقعات بتفضل مرتبطة بـ Source Requirement IDs، وما بتتستخرجش من الكود
المولّد أو من الـ Builder summary.

الـ negative control استخدم اسم وسلوك مختلفين عن greeting case: الـ CLI
صح والدالة ناقصة punctuation. الفحوص رفضت الدالة، وبعد إصلاحها عدّت.
وفي تجربة حقيقية، نفس الحد رفض implementation كان ناسي default argument،
برغم إن named invocation كانت شغالة.

ده parser محدود وصريح، مش ادعاء بفهم كل prose أو كل اللغات. الـ unsupported
أو ambiguous equality ما بتتحولش لoracle مخترعة أو PASS. والـ source
assertions بتتعاد على الحالة الحالية **بعد كل repair**؛ فـ unit-test PASS
من الـ Repairer ما يقدرش يستبدل فشلًا لسه موجودًا في source acceptance.

## الإصلاحات السببية في مسار التنفيذ

### دليل جديد كان بيتقص قبل ما يوصل

الـ context completion كانت بتجمع initial packet طويلة مع evidence جديدة،
وبعدين تقص الاتنين إلى 4200 characters. لو الـ initial packet ملّت الحد،
الـ Worker ما يشوفش الدليل اللي لسه طلبه، ويكرر نفس السؤال.

اتصلّح النقل بحيث الـ stable task packet وcontext update يبقوا رسالتين
منفصلتين، من غير قصّ الدليل بسبب طول الرسالة الأولى. الـ regression بيمرّر
initial packet طويلة، ويفحص الـ provider-bound projection نفسها، ويتأكد إن
الـ original authority والدليل الجديد موجودين مع بعض.

ولما completion budget تنتهي، الـ terminal failure دلوقتي بتوقف الـ Worker
فورًا. قبل كده كان ممكن يكرر decision انتهت بالفعل لحد ما يستهلك باقي
الـ 28 rounds.

### مش كل سؤال عن contract معناه ملف ناقص

الموديل طلب contract بتاعة `run_command`، والـ resolver القديم راح يدور
عليها جوه project الفاضي. دلوقتي declaration الأداة نفسها هي مصدر النوع
ده من الأسئلة، من غير تنفيذها أو اختراع repository evidence.

ونفس الفصل اتطبق على `ROOT CONTRACT` وعلى expected behavior المرتبطة
بأمثلة source معلومة. الـ Source Requirement Ledger تجيب **المطلوب**،
والـ filesystem/resolver يجيب **الموجود**، والـ executed verifier يجيب
**اللي اتقاس فعلًا**. مفيش واحدة من الثلاثة بتتسجل مكان التانية.

الـ live replays أظهرت نفس اللبس بصيغ مختلفة، واتصلح على مستوى نوع الدليل
مش باسم الـ benchmark: sentence أو Requirement ID بتاعة القبول ترجع من
المصدر نفسه، وcallable signature جديدة ترجع إلى طلب إنشائها مع ملاحظة غياب
ملفها، و`sys.argv` ترجع من documentation الموجودة في الـ interpreter المثبت.
لا أسماء مستخدمين ولا current arguments ولا قيم runtime خاصة دخلت كدليل.

الـ repair كمان كان بيورّث inspection scope فاضية رغم إن request أصلية
سمّت ملفاتها صراحة. المسار غير المرتبط approved execution contract بقى
يقدر يقرأ الملفات المسماة في source authority فقط. أما explicit approved
inspection scope، حتى لو فاضية، فتفضل كما هي ولا تتوسع.

### prose بعد رجوع الدليل مش structured decision

الـ Repairer أحيانًا كان يقول إنه يقدر يبدأ، لكن ما يستدعيش gate تاني.
دلوقتي فيه protocol repair واحدة بعد evidence round: الموديل يرد بقرار
JSON مقيد بنفس context schema، والقرار يعدّي على نفس runtime validator
والـ gate المعتادة. ده مش تحويل prose أو Python-like text لتصريح تعديل.
الـ repair جوه الميزانية الأصلية، وclaim كاذبة بـ `sufficient` لا تلغي
dependency غير محلولة أو evidence متناقضة.

### نتيجة فاشلة قديمة كانت بتسمّم rerun ناجحة

الـ generic verification aggregation كانت بتشوف أي FAIL تاريخية لنفس
command وتمنع القبول، حتى بعد تعديل الكود وإعادة نفس الاختبار بنجاح.
اتعاد استخدام latest-evidence helper الموجودة أصلًا للـ legacy focused
tests وsyntax routes.

الاختبارات بتثبت الاتجاهين: FAIL ثم PASS لنفس command يقدر يتعافى؛ PASS ثم
FAIL تفضل فشلًا، وفشل command مختلفة لا يختفي بسبب نجاح command أخرى.
الـ strict semantic evidence والـ approved-authority/direct-oracle routes
فضلت على قواعدها الأقوى، من غير تعميم supersession عليها.

### الـ verification tools محتاجة تعبّر عن التوقع بدقة

`run_command` بقت تقبل `expected_stdout` بالـ newline، و
`expected_exit_code` كـ integer أو `nonzero`. كده رفض argument غير صالح
المطلوب في العقد ما يتصنفش تلقائيًا كعيب في التطبيق.

`run_file` تقدر تعمل assertion لدالة Python عامة باستعمال اسم الدالة،
JSON arguments، وexpected value. الـ invocation بتتنفذ في process منفصلة
وبحد زمني، من غير السماح بكود probe من الموديل، ومن غير كتابة test داخل
subject project. حظر inline Python وshell composition فضل قائمًا.

وكشف الـ live trace عيبًا في التوقع نفسه: الموديل كان ساعات يضيف quote
characters زيادة للـ expected string، ثم يحاول يعدّل التطبيق عشان يرضي
oracle الغلط. لو الحالة لها expected مربوطة بالـ source، تغيير التوقع
بيترد كـ **tool assertion rejection**، مش application failure ولا تعديل
تلقائي. لا الموديل ولا tests المولّدة يقدروا يبدلوا مصدر الحقيقة.

### الـ auto ما بقاش يقسم قبل ما يقيس من غير سبب

مسار `auto` القديم قسّم حتى CLI صغيرة لتفرعات متداخلة عن argument parsing
والحساب والطباعة. في new project فيه implementation owner واحدة مسماة
في المصدر، ومعاها focused tests، بيتجرب الباند المحدود الأول.

القرار مبني على source-declared mutation paths وexisting structural owner
analysis، مش أسماء benchmark أو رقم parameter-size للموديل. الميزانية
والـ context/impact gates ما اتغيروش. الـ multi-owner tasks والـ
force-smaller recovery لسه تقدر تستخدم الـ model-guided split. وأي
approved execution contract تفضل خاضعة للـ structural obligation الأصلية.

### إصلاح draft متماسك، مش إعادة كتابة ملفات المستخدم

إصلاحات الـ exact/range كانت بتدخل الموديل في loops عن line numbers
وmock decorators بدل السلوك المطلوب. اتعاد استخدام policy موجودة أصلًا
اسمها `coherent_rewrite`، مش فتح overwrite جديد: الملفات لازم تكون مخرجات
جديدة مسماة في source، ومفيش snapshot لملف user-owned سابق، ومفيش approved
execution contract بيتجاوز. أي ملف اتعمله verification أو اتعدل من المستخدم
تفضل حمايته الأصلية شغالة.

الـ draft Builder بقى يستقبل schema أصغر: كتابة draft كاملة، قراءة، وتشغيل
tests/commands. أدوات assertions الأغنى تفضل للـ verifier والمسارات العادية.
الاختبارات أثبتت إن model-owned draft تتعدل، لكن user file أو approved
scope لا يتحولوا لـ rewrite authority.

### الـ verifier الغلط مش معناه التطبيق غلط

في fresh release run، كل فحوص المصدر نجحت، لكن الـ Falsifier قدم اسم دالة
مش identifier صالح. ده اتصنف غلط كعيب في التطبيق، وفتح recovery على كود صحيح.
المدخلات غير الصالحة دلوقتي بتترفض في tool boundary من غير invocation.
وبالمثل، internal function غير مطلوبة من المصدر ما تتعاملش كأن غيابها فشل
في public API؛ الـ source-declared callable وmodule وexpected هما المرجع.

ده مش إسكات للفشل: assertion فعلية بقيمة مختلفة أو exception في الدالة
المطلوبة لسه بتمنع القبول. الـ negative controls بتفرق بين input rejection
وreal executable failure.

وبرضه نتايج الـ test runner المتغيرة مش exact stdout contract. الموديل
ما يقدرش يخترع `Ran 4 tests in 0.00Xs` كـ stdout مطلوب، أو يطلب test suite
تفشل ويتحسب ده نجاح. الـ runner لازم ينجح بالـ exit status الفعلية؛ exact
stdout مخصصة لناتج البرنامج اللي المصدر طلبه.

### السلطة القديمة لازم تبقى قديمة فعلًا

بعد إنشاء draft، الـ resolver ممكن يلاحظ facts عن الكود، وبعد مراجعة الكود
facts دي تبقى stale. لو facts اتعرفت بعد الـ impact contract ولم تكن ضمن
أدلته، قدمها ما ينفعش يسحب authority كانت مستمدة من المصدر الأصلي وحده.

الـ stale check اتربط بالـ provenance اللي العقد اعتمدت عليها فعلًا.
العقد اللي اتبنت على source fingerprint قديمة لسه بتترفض، والـ conflicting
facts لسه blocking. الـ regression قابل الحالتين: stale dependency مستخدمة
ترفض التعديل؛ observation لاحقة غير مستخدمة لا تبطل creation authority.

ولكي الـ repair ما يرجعش يضيع السبب وسط packet طويلة، آخر source assertion
فاشلة بتتحط في أول الـ repair packet بشكل صريح: requirement IDs،
expected، actual أو exception. الـ expected لا تتغير، وما فيش application
code جاهزة بتتلقن للموديل؛ ده نفس evidence اللي الـ verifier قاسها.

## حدود القياس والأدلة

### النتيجة النهائية: الحالات الثلاث عدّت على نفس implementation

النسخة المسلّمة:

```text
df7720643860a5c5b3a7e1b840df023aac700d50
```

الـ 71 implementation files في النسخة دي مطابقين byte-for-byte للملفات اللي
اشتغلت في الـ three final live runs، والـ full regression suite، والـ self-test.
الـ implementation اتثبتت في commit بعد القياس؛ لذلك execution records
بتسجل base revision `cfc6ba4` مع dirty source manifest، مش SHA نهائية
مختلقة. الربط النهائي للـ committed source والـ measured bytes موجود في
[release-acceptance.json](../reports/e2e/2026-11-17/release-acceptance.json).

الـ fingerprint المشتركة:

```text
45675cc05a93b09174345b5cbae86592097e0ddb472aac0a3d0dfa990cfe918c
```

| المهمة الأصلية | Run ID | Task model calls | Task tool calls | Wall time شامل preflight | النتيجة |
|---|---|---:|---:|---:|---|
| Greeting CLI + function + tests | `20261117T031623-3e49754b` | 17 | 12 | 176.225s | `done`، exit 0، Root verified، independent PASS |
| Integer product + invalid inputs | `20261117T031912-b38724fb` | 31 | 24 | 203.630s | `done`، exit 0، Root verified، independent PASS |
| Exact console output | `20261117T032232-6c1228c8` | 17 | 10 | 75.899s | `done`، exit 0، Root verified، independent PASS |

كل حالة بدأت من مجلد جديد، عن طريق `mini.py --workspace ... --prompt-file ...`
من غير `--mode`، أو experiment policy flags، أو monkey-patching.
الـ default `auto` اختار الـ shared bounded leaf في الحالات دي. كل الأدوار
استخدمت نفس installed local `gemma4:e4b`، digest:

```text
c6eb396dbd5992bbe3f5cdb947e8bbc0ee413d7c17e2beaae69f5d569cf982eb
```

Task model calls لا تشمل 3 host-preflight canary calls لكل محاولة.
HarrTest المحلية فضلت 4.1.0، ومفيش provider بديل اتستخدم.

الـ external acceptance قاست:

- Greeting: 3 CLI invocations، و3 return values للدالة، والـ generated
  unittest suite اللي نفذت 4 tests فعلية. النتيجة الصحيحة للدالة فيها `!`
  ومن غير newline، والـ CLI فيها نفس الـ greeting ومعاها newline.
- Multiply: 5 valid products تشمل negative وzero وlarge integers، و5 rejected
  invocations تشمل missing وinvalid وextra arguments. الرفض نفسه اتقاس بـ
  actual nonzero exit، مش باعتباره test failure غير مقصودة.
- Hello: actual stdout تساوي `MERGE_OK\n`، وprocess exit تساوي صفر.

كل ملفات الناتج اتفحصت واتشغلت بعد خروج orchestrator. مفيش patch يدوي
اتعمل للمنتجات عشان تعدّي الاختبارات.

### تقدر تشغّل الناتج دلوقتي

المخرجات الحية الأصلية متروكة تحت
`output/live-e2e-20261117-release/`، ونسخ byte-identical متسجلة في Git تحت
[evidence products](../reports/e2e/2026-11-17/live/).

من repository root:

```powershell
.\.venv\Scripts\python.exe output\live-e2e-20261117-release\greeting\greet.py Ada
.\.venv\Scripts\python.exe output\live-e2e-20261117-release\multiply\multiply.py 6 7
.\.venv\Scripts\python.exe output\live-e2e-20261117-release\hello\hello.py
```

الناتج بالترتيب:

```text
Hello, Ada!
42
MERGE_OK
```

إعادة الـ independent check، من غير تشغيل موديل أو تغيير source الملفات:

```powershell
.\.venv\Scripts\python.exe reports\e2e\2026-11-17\acceptance.py greeting output\live-e2e-20261117-release\greeting --output output\greeting-acceptance-recheck.json
.\.venv\Scripts\python.exe reports\e2e\2026-11-17\acceptance.py multiply output\live-e2e-20261117-release\multiply --output output\multiply-acceptance-recheck.json
.\.venv\Scripts\python.exe reports\e2e\2026-11-17\acceptance.py hello output\live-e2e-20261117-release\hello --output output\hello-acceptance-recheck.json
```

الـ acceptance script مستقلة ومش مقدمة كأداة للموديل. الـ trusted one-off
function probe اللي فيها تستخدم Python مباشرة في process منفصلة؛ ده مش
فتح inline Python في الـ agent tool allowlist.

### الـ offline والـ negative controls

آخر complete regression:
**1751 tests: OK، مع 4 pre-existing legacy skips**، في 204.618s للـ runner
و206.106s للـ recorded process. الـ public `mini.py --self-test --no-bootstrap`
رجع exit 0، في 11.898s. الـ receipts والـ logs محفوظة تحت
[offline evidence](../reports/e2e/2026-11-17/offline/).

الـ independent oracle نفسها رفضت فعليًا `e2e-greeting-direct-03`، رغم إن
الموديل والـ generated tests قالوا نجاح. الـ CLI كانت صحيحة لكن الدالة ناقصة
punctuation. [الرفض المسجل](../reports/e2e/2026-11-17/live/e2e-greeting-direct-03/independent.json)
بيثبت إن الفحص مش بيعيد تصديق status الـ agent.

الـ focused regressions كمان اختبرت رفض:
stale bound source authority، conflicting/unknown dependencies، invalid probe
source، undeclared callable، expected values مخالفة للمصدر، test reports
مخترعة، وبرنامج بيرجع exit 0 لما المطلوب يرفض arguments.
الفشل الحقيقي فضل failure؛ مفيش test اتعملها skip عشان المهمة تخلص.

### كل المحاولات محفوظة

في المتابعة دي **27 live attempts**:

| النتيجة المسجلة | العدد |
|---|---:|
| `done` وفحص مستقل PASS | 9 |
| `done` لكن الفحص المستقل رفضها | 1 |
| task failure | 13 |
| `too_broad` | 2 |
| interrupted diagnostic | 1 |
| host preflight failure | 1 |

الـ 37 offline check invocations تشمل reproductions قبل الإصلاح، وفشل
intermediate tests، والـ successful targeted/full checks بعدها.
[validation-summary.json](../reports/e2e/2026-11-17/validation-summary.json)
هو الفهرس الكامل، مش قائمة بأفضل المحاولات بس. الأرقام بتجمع مهام وrevisions
مختلفة، فمينفعش تتحول لنسبة reliability عامة أو model benchmark.

الـ host failure كانت `CRITICAL_MEMORY_HEADROOM`: حوالي 324 MB RAM متاحة
قبل أي canary. الحماية فضلت شغالة، واتسجلت المحاولة بفشل حقيقي. المتابعة
انتظرت bounded read-only memory readiness من غير قتل برامج تانية أو
تغيير خدمة Ollama؛ الـ final accepted runs عدّت preflight الطبيعي.

المحاولات اللي رجعت `done` واترفضت مستقلًا، والمحاولات اللي فشلت أثناء
repair، موجودة في نفس سجل المتابعة. تجربة auto متفرعة اتوقفت بعد إعادة
إنتاج نفس causal failure في عدة children؛ متعلّمة interrupted diagnostic،
من غير process exit مختلقة أو success claim.

الـ generated workspaces الناجحة والـ tool results والـ model-response
shapes والـ run metrics وexecution/source hashes محفوظة. الـ rollbacks
الفاشلة اللي مسحت generated candidate ما اتبدلتش بملفات متخيلة؛ المحفوظ
لها هو الـ trace والـ error والـ terminal result المتاحين فعلًا.

### حدود النتيجة

اتقفلت blockers اللي كانت مانعة الـ three predeclared Python CLI journeys،
واتثبت prompt-to-output حقيقي على النسخة المسلمة. ده مش إثبات إن أي طلب
مفتوح في أي لغة أو game/browser project هيكتمل، ولا إن weak-model sampling
بقى deterministic في كل الظروف. التاريخ نفسه بيحتفظ بالمحاولات اللي
فشلت قبل الإصلاح بدل مسحها.

المطلوب النهائي «نكتب prompt، نستنى، ونشوف ناتج شغال» اتحقق هنا من خلال
default public CLI، الملفات المحفوظة، وفحص مستقل بيقدر يرفض الناتج.

الـ original branch commits والـ stash والـ secondary worktree المحفوظة
ما اتغيرتش ضمن المتابعة. مفيش push أو remote branch deletion، ومفيش تغيير
لخدمة Ollama المشتركة أو model fallback.
