# دمج تاريخ Mini Hivo من غير فقدان الـ commits

تاريخ المهمة: 2026-11-16. الـ validation workflow المستخدم هو HarrTest 4.1.0
المثبت محليًا؛ مفيش تحديث للـ skill أو تغيير للموديل أثناء المهمة.
آخر live runs اكتملت بعد منتصف الليل يوم 2026-11-17 بالتوقيت المحلي.

ده سجل checkpoint الدمج كما اتقاس وقتها. [المتابعة اللاحقة](LIVE_E2E_VALIDATION.md)
أصلحت blockers إضافية ووصلت إلى three fresh default-auto Python CLI
journeys بنتيجة محفوظة وفحص مستقل؛ نتائج المحاولات التاريخية هنا فضلت من غير تغيير.

[الدمج المحلي الأحدث والتحقق](#توحيد-main-المحلي-19-نوفمبر-2026)
يغطي كمان إصلاحات الـaudit وواجهة الـheadless jobs.

**النتيجة المختصرة:** فضل local branch واحد هو `main`، وكل الـ original
branch tips بقت reachable منه. الـ regression suite والـ public self-test
ناجحين، وفيه إصلاح Python حقيقي نجح مرتين بالـ local model واتراجع مستقلًا.
لكن الـ greenfield و`auto` لسه ليهم إخفاقات محفوظة تحت؛ النتيجة مش شهادة
إن الـ prototype بقى خاليًا من المشاكل في كل أنواع الطلبات.

المطلوب كان حاجتين مع بعض: يبقى فيه `main` واحد نشتغل عليه، وفي نفس الوقت
نقدر نرجع لأي شغل قديم بنفس الـ commit الأصلي، ونعرف ليه قرار الدمج اتاخد.
وده مختلف عن إننا ننسخ آخر نسخة من كل branch فوق بعض، أو نعمل squash ونفقد
العلاقة بين التجارب ونتايجها.

الجزء التاني من القبول هو التشغيل الحقيقي: الـ unit tests لوحدها مش دليل إن
الموديل هيستقبل prompt، يكتب الملفات، يشغّلها، ويوصل لناتج صحيح. عشان كده
المهمة احتفظت بالـ offline checks وبكل live attempt، بما فيها المحاولات اللي
فشلت قبل أو بعد كتابة كود.

## ليه 100 branch ما احتاجوش 99 content merge؟

الحصر الأول لقى **100 local branches**، و3 branches على `origin`.
الـ inventory فيه 104 refs لأن فيه كمان الـ remote-tracking `origin/HEAD`.
من الـ local branches، 33 كانوا أصلًا ancestors لـ `main`، و67 ما كانوش.
بس لما اتقارن الـ commit graph، كل الشغل غير المربوط بـ `main` كان متغطي
بمسارين نهائيين:

| المسار | الـ tip الأصلي | محتاجين نعمل إيه؟ |
|---|---|---|
| Original core / structured Worker | `8c8ff37f43246f225dbae67ea97a38276a93ecea` | نحفظ الـ ancestry الأصلية من غير ما نرجّع الكود لنسخة أقدم |
| Experiments 17–19 | `9ad7dafbdd8da29f215c1d0efed51a369f241cb1` | ندمج التغييرات والتقارير الجديدة فعلًا |

الأسماء والـ hashes الكاملة موجودة في
[الـ initial branch inventory](../reports/consolidation/2026-11-16/branch-inventory.json).
الـ inventory محفوظ قبل أي merge أو حذف لأي branch، مش مستنتج من الأسماء
اللي فضلت بعد التنظيف.

المشكلة الأساسية كانت إن الـ core اتنقل قبل كده لخط commits جديد. فمثلًا
النسخة الأصلية من feature والنسخة المنقولة ليها ممكن يكون ليهم نفس الـ patch،
بس SHA مختلف. مقارنة `git cherry` لقت 57 patch-equivalent commits و10 patches
متكيفة جوه التاريخ المنقول، ومقارنة `range-diff` سجلت المقابلات بدل التخمين.

الدليل الأقوى كان مقارنة الشجر نفسها: كل ملفات الـ core داخل `hivo` في
الـ original tip كانت مطابقة للـ linear checkpoint `7e96a37`. الاختلافات
كانت في الـ CLI وملفين regression tests؛ النسخة الخطية فيها إصلاحات أحدث
للـ mutation recovery. بالتالي إعادة تطبيق النسخة القديمة كانت هتخلق خطر
رجوع إصلاحات شغالة لورا، من غير ما تضيف feature ناقصة.

## إيه اللي اتعمل في Git بالضبط؟

أولًا اتعمل Git bundle كامل بـ `--all` واتراجع بـ `git bundle verify`.
النسخة دي بتشمل الـ branches والـ tags والـ stash والـ internal refs، ومفيش
reset أو rebase أو squash أو garbage collection اتعمل.

SHA-256 للـ bundle الأصلي:

```text
A648974560B11D361CF7001A46393936CEB233DB5C3058D6CAF8C21A21622E89
```

بعدها اتعمل merge من نوع ancestry-only:

```text
f65f1ab26116220a3a86bf2f46447ee1bd870776
parents:
  74752d3708578ea8efab2e59c0891d2ad50e2dbd
  8c8ff37f43246f225dbae67ea97a38276a93ecea
```

استخدام `-s ours` هنا **مش** معناه إننا تجاهلنا branch مختلف من غير فحص.
اتستخدم فقط للمسار اللي محتواه موجود بالفعل بنسخة أحدث. واتراجع إن الـ tree
بعد الـ merge مطابقة حرفيًا لـ `74752d3`. التغيير المقصود كان إضافة الـ
original commits كـ parents يمكن الوصول لهم، مش تغيير ملفات التشغيل.

الـ merge التاني كان normal content merge:

```text
1f067eda8ee46a72da81832fac5cae44b40edfec
parents:
  f65f1ab26116220a3a86bf2f46447ee1bd870776
  9ad7dafbdd8da29f215c1d0efed51a369f241cb1
```

ده دخل نتيجة Experiment 17 النهائية، وExperiment 18، وExperiment 19،
والـ CLI flags والـ tests المرتبطة بيهم. الدمج التلقائي ما طلعش conflicts.
وفي نفس الوقت فضل أرشيف Experiments 1–16 والـ classification protocol القديم
والـ Prove It skill موجودين؛ مفيش side اتاخد كنسخة كاملة على حساب التاني.

بعد الـ merge التاني، اتراجع كل SHA في الـ inventory:
**104/104 refs كانوا ancestors لـ `main`**. ده بيحفظ كل commit وراء أي branch
منهم، مش بس محتوى آخر ملف فيه.

بعد اكتمال القياس، اتشالت **99 local branch names** باستخدام `git branch -d`
فقط، وفضل `main`. الـ secondary worktree اتفصلت عن اسم branch عند نفس
`9ad7daf`؛ fingerprint للـ **248 tracked files** قبل وبعد الفصل كان مطابقًا،
والمجلد نفسه فضل موجود. الـ stash الأصلي `27a5404` فضل زي ما هو.
التفاصيل في [ancestry and retirement proof](../reports/consolidation/2026-11-16/ancestry-and-retirement.json)
و[سجل أسماء الفروع المحذوفة](../reports/consolidation/2026-11-16/retired-branches.txt).

إصلاحات التكامل اتسجلت في commits منفصلة بعد الـ merges:

| Commit | المسؤولية |
|---|---|
| `0fe01be` | correctness fixes، الـ batch exit status، والـ self-test fixture |
| `7f7dcee` | bounded native-tool format recovery وحفظ أول context failure |
| `92aee80` | source-qualified new-artifact context، من غير إعفاء dependencies مجهولة |

الـ live acceptance النهائية اتعملت على `92aee80321e6ee241b9885e266501a73b78491bd`.
أي commit توثيق بعدها لا يغير ملفات تشغيل المنتج اللي اتقاس.

## قصة الـ live testing والإصلاحات

اتثبت نفس prompt لتجارب الـ baseline: يعمل Python greeting utility،
سلوك CLI للاسم الافتراضي ولـ `Ada`، function قابلة للاستدعاء، وunit tests.
الـ prompt نفسه محفوظ مع الأدلة، وماتغيرش عشان يهرب من failure.

### الطلب وقف قبل الموديل

أول تشغيل من الـ CLI وقف عند `CLARIFICATION_REQUIRED` من غير أي task model
call. مثلًا كان بيعتبر شرط التشغيل بـ arguments وشرط التشغيل من غير arguments
متناقضين، وكمان بيعتبر منع عمل web application تعارض مع إنشاء Python file.

السبب كان مقارنة كلمات مشتركة بين positive requirement وnegative requirement
بدل التأكد إن النفي بيتكلم عن نفس target ونفس السياق. الإصلاح فصل targets
الممنوعة المتعاطفة، واحتفظ بسياق `without`، وبقى محتاج target كامل مش مجرد
كلمة مشتركة. اتضافت حالات فاشلة قبل الإصلاح، مع negative control يثبت إن
`Remove keyboard controls` لسه بيتعارض مع الحفاظ على نفس controls.

### الموديل دخل، بس الـ tool contract كان ناقص

المحاولة اللي بعدها وصلت للموديل، لكنه كرر evidence requests بأنواع runtime
مش بيقبلها. الـ provider schema كانت بتقول إن `kind` أي string، بينما
الـ validator عنده vocabulary محددة. اتربط الـ schema بنفس enum المستخدمة
في الـ validator، من غير قبول أسماء جديدة أو تخمين defaults.

كمان تعليمات الـ greenfield بقت تفرق بين dependency ناقصة فعلًا وبين ملف
المهمة لسه طالبة إنشاءه. ده ما بيفتحش الـ gate تلقائيًا: الموديل لسه لازم
يقدم decision، وأي contradictory أو unresolved evidence تفضل blocking.

الـ raw diagnostic capture كشف failure تانية مختلفة: الموديل كان ساعات
بيرجع `context_sufficiency_check(...)` كنص عادي في `content`، مع إن الـ API
مستنية native `tool_calls`. النص ده مش invocation، وما ينفعش نعمله `eval`
أو نعتبره تصريح تنفيذ.

اتوضحت الـ native-tool instructions، واتضاف protocol repair واحدة فقط
للـ known offered tools جوه نفس round budget. الإصلاح بيطلب native call جديدة
بـ JSON arguments؛ ما بينفذش النص ولا بياخد منه `sufficient` كدليل. لو الموديل
كرر النص، المحاولة بتفشل من غير mutation authority. الـ tests بتثبت إن gate
decision واحدة حقيقية لازمة قبل أول كتابة، وإن التكرار محدود. كمان failure
بتاعة الـ context ما بقاش بيتكتب فوق سببها برسالة impact gate لسه ما اتجربتش.

في تشخيص لاحق، الـ evidence provider نفسه بقى يفرق بشكل صريح بين تعريف
dependency مفقودة وبين تعريف output المستخدم طالب إنشاءه. الإعفاء
`not_applicable` محتاج دليلين مع بعض: source requirement أصلية بتطلب إنشاء
نفس المسار، وfilesystem observation إن المسار لسه مش موجود. ده ما بيدّعيش
إن implementation أو tests اتنفذوا، وما بيدخلش facts مصطنعة للـ World Model.
الـ Worker لسه لازم يقدم sufficiency decision فعلية، والـ unknown dependencies
والـ existing files ما بياخدوش الإعفاء. الـ negative controls بتثبت إن claim
من غير الدليلين مش كفاية لتصريح التعديل.

التعديل ده حلّ تصنيف requests بتاعة الملفات الجديدة في الـ trace، لكنه مش
دليل على نجاح الـ task: إحدى المحاولات بعدها طلبت `unittest execution`
كدليل repository غير موجود، وفضلت blocking. النتيجة دي محفوظة كفشل، مش
متقدمة على إنها uplift أو نجاح عام.

### تصريح التنفيذ اتفهم على إنه اكتمال المهمة

بعد نجاح الـ context check، كان ممكن الـ Worker يرد بوصف للـ check نفسها،
والـ controller يعتبره `done` قبل كتابة أي ملف. الإصلاح احتفظ بنتيجة الـ gate
في الـ transcript، وطلب تنفيذًا وverification فعليين. نجاح الـ authorization
لوحده ما بقاش completion.

الـ regression بيعيد نفس التسلسل: context PASS، بعده prose فقط، وبعده كتابة
وتشغيل. من غير الإصلاح كان بيقف قبل الكتابة؛ مع الإصلاح بيوصل للـ executable
evidence. ده مستقل عن الـ experimental context-closure policy.

### منع الـ web اتفهم على إنه طلب browser

جملة `Do not create a web application` كانت بتشغّل browser verification
وتطلب HTML entrypoint من Python project. اتصلّح negative browser signal
filter الموجود بالفعل. وفي نفس الاختبار، إضافة طلب positive منفصل للتحقق
من صفحة في المتصفح لسه بتخلي browser verification مطلوبة؛ مفيش تعطيل عام
للـ verifier.

### المحاولة ولّدت كود، والـ tests كشفت غلط فيه

محاولة لاحقة كتبت الملفين وشغّلت tests، لكن الكود المولّد كان فيه greeting
غلط. محاولات الإصلاح طلبت replacement count مقداره 2 مع إن المصدر فيه match
واحد، وبعدها قدمت range edits غير سليمة نحويًا. الرفض والـ rollback فضلوا
شغالين؛ مفيش تعديل مكسور اتقبل عشان نطلع PASS.

اتضح إن count mismatch غير الصفري كان بيتصنف `INVALID_MUTATION`، فمش بيوصل
له bounded current-source recovery packet الموجودة أصلًا. اتربط بنفس
`STALE_TARGET` recovery، وبقى الـ tool schema بيوضح إن default count هو 1.
الاختبار بيتأكد إن feedback فيها العدد المطلوب والفعلي والمصدر الحالي،
وإن الملف نفسه **ما اتغيرش** أثناء الرفض.

### behavior PASS ما كانش كفاية لحدود الـ impact

في محاولة تانية الـ Builder والـ Falsifier شغّلوا tests بنجاح، لكن آخر impact
audit رفض الملفات الصحيحة. السبب إن root goal العامة ما فيهاش أسماء الملفات؛
الأسماء كانت في الـ source requirements، بينما الـ fallback حوّل كلمات زي
`Python` و`greeting` إلى targets مطلوبة.

الإصلاح أعاد استخدام الـ code-location classifier والـ clause-local mutation
intent الموجودين في execution contracts. لو مفيش approved mutation paths،
الـ creation targets بتتربط بأوامر الإنشاء الصريحة في نفس local requirements،
ومعاها provenance. `Preserve settings.json` ما بتتحولش لطلب تعديل.
ولو فيه approved scope أصلًا، الـ hints الجديدة **ما بتوسعهوش**. الاتنين
متغطّيين باختبار فعلي للـ impact comparison واختبار رفض خارج النطاق.

### دقة الـ CLI والـ self-test

الـ batch CLI القديم كان بيرجع process exit `0` حتى مع task failure.
دلوقتي بيرجع `1` لأي نتيجة غير `done`، و`2` لخطأ setup/preflight، والـ baseline
كمان بيحترم إن `--prompt-file` noninteractive. دي إشارة failure صريحة،
مش استنتاج من آخر سطر في اللوج.

الـ architecture self-test نفسه كان عنده split وهمي إلى `part A` و`part B`
من غير independent verification. الـ semantic coupling الحديث كان بيدمجهم،
فـ recursion checks كانت بتفشل. اتصلّح الـ fixture ليستخدم independent mock
components بملفات وverification targets منفصلة، مع الاحتفاظ بنفس شرط العمق
وعدد المهام. وكمان اتحدثت مراجع الـ shared code-location helper بعد استخراجه.

## إيه اللي اترقّى للـ default وإيه اللي فضل تجريبي؟

الـ correctness fixes اللي فوق اتصلحت في المسار المشترك. لكن مفيش blanket
promotion لكل experiment policy. كل الـ existing policy defaults فضلت كما هي.

`bounded_reanchor` فضل explicit opt-in؛ اتوسع بس ليغطي new-project Builder
من غير approved path، بنفس re-anchor واحدة جوه الميزانية الأصلية ومن غير
منح mutation authority. أما `bounded_closure` ففضل تجريبي: نتيجة Experiment 19
الأصلية كانت 0/3 context decisions في الطرفين، ووقت وmodel calls أكتر.
ما ينفعش نستخدم نتيجة زي دي كدليل لتحسين default.

## سجل الاختبارات والقياس

الـ baseline offline suite شغّل **1703 tests: OK، مع 4 skipped**.
بعد الدمج والإصلاحات، الـ complete suite شغّل **1729 tests: OK، مع 4 skipped**.
الـ skips الأربعة دول legacy scheduler tests معلّمة أصلًا، مش tests جديدة
اتشالت عشان الدمج يعدّي. الـ self-test العام اتشغّل من نفس CLI واتراجع منفصلًا.

الـ focused evidence محفوظة للـ before/after، بما فيها:
false requirement conflicts، context-only completion، negated browser routing،
mutation count recovery، creation impact binding، وapproved-scope negative controls.
كان فيه كمان failed intermediate test run بسبب test selector كان بيفترض إن
أول tool message هي mutation feedback؛ بعد الاحتفاظ بالـ context transcript
اتحدث عشان يختار `edit_file` message بالاسم بدل ترتيب الرسائل.

### كل الـ live attempts، مش بس آخر محاولة ناجحة

السجل الكامل فيه **18 محاولة: 2 انتهوا `done` و16 فشلوا أو وقفوا**.
دي مهام وrevisions وdiagnostic variants مختلفة؛ العدد ده **مش** reliability
benchmark ولا مقارنة عادلة بين model policies. الـ two successful runs
بس هما إعادة مستقلة لنفس existing-code case على نفس source revision النهائية.

| المحاولة | المسار / النتيجة الفعلية |
|---|---|
| Greeting baseline قبل الإصلاح | clarification false conflicts؛ صفر task model calls، والـ exit القديم كان 0 رغم التوقف |
| Greeting direct 01 | invalid context request kinds؛ التوقف قبل mutation، والـ exit القديم كان 0 |
| Greeting direct 02 | context-only completion وبعدها browser route غلط؛ exit 1 بعد إصلاح الـ CLI |
| Greeting direct 03 | ملفات اتولدت، tests كشفت bug، ومحاولات exact/range repair فشلت واتبعتها rollback |
| Greeting direct 04 | behavior tests نجحت، لكن impact audit رفض targets غير مربوطة بالـ source requirements |
| Greeting direct 05 | Worker رجع tool call كنص؛ مفيش gate authorization |
| Greeting recursive 01 | تقسيم متكرر؛ child context/impact failures، من غير Root verified |
| Multiply auto 01 | default route اختار recursive وقسّم مهمة صغيرة؛ مفيش ناتج مكتمل |
| Multiply baseline 01 | prose-only context call؛ مفيش mutation authority |
| Multiply capture diagnostic 01 | نفس الفشل مع observational native request/response capture |
| Multiply baseline 02 | native-format repair اتنفذ، لكن Worker طلب ملفات/knowledge كـ missing evidence |
| Multiply thinking diagnostic 01 | Builder thinking override ما حلّش التوقف؛ مش production acceptance |
| Multiply tool-description diagnostic 01 | توضيح locked tools في offered description ما حلّش التوقف؛ مش production acceptance |
| Hello runtime baseline 01 | الملف اتكتب وطلع `MERGE_OK` فعلًا، لكن routing مفيهاش applicable focused-test route فأُرجع التغيير |
| Hello with tests 01 | Worker طلب تعريف الملفات الجديدة قبل إنشائها؛ bounded context failure |
| Hello with tests 02 | الـ new-file requests اتصنفت `not_applicable` بدليل مصدر، لكن طلب `unittest execution` فضل unresolved |
| Clamp repair 01 | `done`، process exit 0، Root verified، و8/8 independent cases PASS |
| Clamp repair 02 | fresh identical fixture؛ نفس النتيجة، والاختبارات المحمية ما اتغيرتش |

[validation-summary.json](../reports/consolidation/2026-11-16/validation-summary.json)
فيه الـ run IDs، source revisions/fingerprints، commands، task model/tool call
counts، exit codes، والـ elapsed times. ملفات كل محاولة تحت
[live evidence](../reports/consolidation/2026-11-16/live/).
الـ diagnostic overrides متعلّمة صراحة، وما دخلتش بدل تجربة public CLI ناجحة.

أول baseline اتشغل قبل إضافة الـ execution recorder؛ الـ run metrics واللوج
والـ process exit الملاحظ محفوظين، لكن الـ overall elapsed time والـ full
execution metadata مش متاحة له، ومتعلّمة `null` بدل تخمين قيم.

الـ console logs القديمة اللي كانت UTF-16 اتحفظت للقراءة كـ UTF-8، واتسجل hash
للأصل وللنسخة. باقي الأدلة متحفظة bytes زي ما هي، وlocal `.gitattributes`
بتمنع تغيير line endings للـ evidence. الملفات الكاملة اللي failed transaction
مسحتها بالـ rollback مش بيتدّعي إننا احتفظنا بنسخة كاملة منها؛ المحفوظ هو
tool results، runtime failures، metrics، events، والـ raw captures المتاحة.

### النتيجة اللي اتنفذت واتراجعت فعلًا

حالة القبول الناجحة بدأت بملف Python موجود فيه bug:

```python
def clamp_number(value, lower, upper):
    return value
```

الـ fixed unit tests اتكتبت قبل الموديل، وشغّلناها على الأصل: فشل اختبارا
lower وupper زي المتوقع. الـ prompt طلب إصلاح نفس الدالة، والحفاظ على الـ API
وعلى test file من غير تعديل. ده existing-code repair case، مش إنشاء project
كبير ولا fixture approved-plan replay.

الاتنين اتشغلوا من الـ public entrypoint من غير monkey-patching:

```powershell
.\.venv\Scripts\python.exe -X utf8 -u mini.py --mode baseline --workspace <fresh-clamp-workspace> --prompt-file <clamp-prompt.txt> --no-bootstrap
```

| Run ID | Source | Task model calls | Task tool calls | Wall time شامل preflight | النتيجة |
|---|---|---:|---:|---:|---|
| `20261117T000140-0ab9c94a` | `92aee80` | 11 | 8 | 51.266s | `done` / exit 0 / Root verified |
| `20261117T000516-1b8a1282` | `92aee80` | 10 | 7 | 43.027s | `done` / exit 0 / Root verified |

كل الأدوار استخدمت `gemma4:e4b`. الـ task model-call counts لا تشمل 3
host-preflight canary calls لكل محاولة. مفيش model fallback أو paid provider.

الموديل غيّر الـ implementation إلى:

```python
def clamp_number(value, lower, upper):
    return max(lower, min(value, upper))
```

بعدها [independent oracle](../reports/consolidation/2026-11-16/cases/clamp/verify_clamp.py)
شغّل 8 حالات محددة سلفًا: تحت الحد، فوق الحد، داخل النطاق، الحدين نفسيهما،
negative bounds، وfloat داخل عقد الأرقام. الاتنين نجحوا 8/8، والـ 3 original
unit tests نجحوا، والـ function signature فضلت كما هي.

SHA-256 لملف الاختبارات قبل وبعد كل محاولة كان:

```text
3f56c6f0c400b32dc52fb5a3d9488c0f6823c9fd5674268a3466eb9634873b2a
```

الـ oracle نفسها اتجربت على الأصل المعيوب: رفضته في 5/8 independent cases
وفي 2/3 unit tests. فإحنا مش معتمدين على إن الـ controller قال `done` أو على
tests كتبها الموديل لنفسه. النتائج موجودة في
[clamp 01](../reports/consolidation/2026-11-16/independent/clamp-01.json)،
[clamp 02](../reports/consolidation/2026-11-16/independent/clamp-02.json)،
و[negative control](../reports/consolidation/2026-11-16/independent/clamp-negative-control.json).

الـ [input fixture](../reports/consolidation/2026-11-16/cases/clamp/before/)،
[prompt](../reports/consolidation/2026-11-16/prompts/clamp.txt)، والناتج في كل
run موجودين عشان التجربة تبقى قابلة للفحص وإعادة التشغيل، مش مجرد screenshot
أو جملة نجاح.

### إيه اللي لسه مش متحقق؟

- الـ default `auto` والـ greenfield generation مش مثبت إنهم موثوقين؛ فيه
  over-decomposition وWorker requests غير مفيدة لسه بتوقف التنفيذ.
- نجاح تشغيل CLI بسيط من غير test file مش كفاية في الـ current route
  aggregator؛ حالة Hello اتنفذت لكن ما اتقبلتش. ما اتعملش fake test PASS عشان
  نلف حوالين الـ gate.
- browser families وplanning/approval/promotion end-to-end ما اتقاسوش fresh
  في المهمة دي. تقاريرهم التاريخية محفوظة من غير تغيير النسب أو إعادة تسميتها.

إذن اللي نقدر نثبته: الدمج والتاريخ والتنظيف المحلي ناجحين، الـ deterministic
regressions ناجحة، وفيه supported live existing-code path شغال فعلًا.
الشرط الأقوى «كل أنواع الطلبات شغالة من غير أي مشاكل» **لسه مش متحقق**.

## إزاي نعمل tracing بعد ما branch name تتشال؟

ابدأ من الـ branch inventory وخد الـ SHA الأصلي، وبعدها مثلًا:

```powershell
git log --graph --oneline --all
git show 9ad7dafbdd8da29f215c1d0efed51a369f241cb1
git merge-base --is-ancestor 8c8ff37f43246f225dbae67ea97a38276a93ecea main
git show --no-patch --format=fuller f65f1ab
git log --first-parent --oneline main
```

لو محتاج branch مؤقت للشغل القديم، ممكن تنشئه صراحة من الـ SHA المحفوظ.
ده إجراء استرجاع اختياري لاحق، مش معناه إن اسم branch لازم يفضل موجود عشان
الـ commits تفضل موجودة.

الـ source commits محتفظة بأصحابها وتواريخها. الـ merge commits فيها الآباء
الأصليين ورسالة السبب. الـ new validation records فيها command وexit code
وelapsed time والـ source fingerprints، مع فصل historical وoffline وlive.

## حدود الأمان والنشر

حذف الـ local branches اتعمل بعد إثبات ancestry لكل الـ tips. الـ stash
القديم محفوظ، والـ secondary worktree ما اتمسحتش ولا اتغير محتواها: فصلها عن
اسم branch حافظ على نفس commit ونفس الملفات بدل حذفها.

ما حصلش `push` أو حذف branches من GitHub. الطلب فوّض الدمج والتنظيف المحلي،
لكن مفيش تصريح صريح بالنشر؛ الـ remote branches الثلاثة تفضل محفوظة لحد ما
يحصل التصريح ده. بالتالي `main` الواحد هنا هو النتيجة المحلية، مش claim
إن GitHub اتنضف أو اتحدث تلقائيًا.

أي نشر لاحق لازم يبدأ بإعادة حصر remote tips، ودمج أي شغل جديد، وبعدها
normal non-force push لـ `main`. حذف remote names ييجي فقط بعد إثبات إن
نفس tips بقت reachable من الـ remote `main` المنشورة. مفيش force push
أو تخطي hooks ضمن الخطة.

`git fsck --full --no-reflogs` رجع exit 0. أبلغ عن dangling objects، من غير
corruption errors؛ ما اتمسحش أي object، وما اتعملش prune أو garbage collection.
الـ [integrity record](../reports/consolidation/2026-11-16/git-integrity.json)
بيفصل نتيجة الأمر عن وجود refs أو worktree إضافية.

المهمة ما غيرتش إعدادات خدمة Ollama المشتركة، وما شغلتش موديل خارجي مدفوع،
وما حذفتش user workspace أو runtime history قديم. نجاح sample جديدة لا
يلغي نتائج Timer/Python التاريخية ولا يثبت إن الـ prototype بقى موثوق في كل
أنواع المشاريع؛ الفرق بين الاتنين موضح في
[حالة المشروع](PROJECT_STATUS.md) و[فهرس النتائج](../reports/INDEX.md).

## توحيد main المحلي 19 نوفمبر 2026

الهدف في الجولة دي إن `main` المحلي يجمع الكود اللي اتراجع فعلًا، من
غير فقدان تاريخ أو الاعتماد على نتائج قديمة. الـ4 tips اللي على `origin`
غير `main` كانوا بالفعل ancestors للـbase `4096ccc`. الشغل الجديد اتسجّل
في `9e7f649` (إصلاحات التحقق والـrecovery والـbudget) و`91978cd`
(الـheadless jobs). الدمج `04e603d` احتفظ بالاتنين كـparents. التعارضين
كانوا إضافات في التوثيق؛ مفيش تغيير في ملفات التشغيل من حل التعارض.

أول تشغيل شامل في worktree جديدة كشف إن جزء من الاختبارات التاريخية
بيحتاج مدخلات replay أصلية غير موجودة في Git. مفيش بيانات اتفبركت أو
اترفعت بدلها. التشغيل في الـcheckout الأصلي بالمدخلات المحفوظة حصر
المشكلة في اختبارين: الـfixtures بتاعتهم كانت بتثبت إن السياق كافي
لكن من غير scope تعديل صريح. اتضاف نطاق موثّق للـpositive fixtures
وضابط سلبي يثبت إن صلاحية القراءة ما تديش صلاحية الكتابة. الـgates
بتاعة التشغيل نفسها ما اتخففتش.

**القياس على الكود المدمج `d6d6e69`:** 2,072 اختبار متسجّل: **2,067
نجحوا، 5 skips، 0 failures و0 errors**. الاختبارات دي تشمل 5 تشغيلات
على Edge الحقيقي، واختبار الـJobService لرحلة الموافقة واسترجاع الـpatch
مع ردود موديل مُحضّرة. أمر `mini.py --self-test --no-bootstrap` نجح كمان.
الـregression suite ما بعثتش طلبات للموديل؛ اختباراته القائمة على
الـhistorical replay استخدمت المدخلات المحفوظة في الـcheckout الأصلي.

الـCLI الحقيقي اشتغل على `gemma4:e4b` في folders جديدة. بعد الخروج،
oracle مستقلة قرأت `graduation-check.txt` من القرص وقارنت البايتات؛
الـlog لوحده ما اتحسبش دليل:

| المحاولة | الناتج المقاس | طلبات الموديل بعد preflight | الخروج |
|---|---|---:|---:|
| `20261119T001543-a76ba68f` | `MINI_HIVO_READY` بالضبط، من غير newline أو ملفات منتج إضافية | 8 | 0 |
| `20261119T001636-a971be98` | `Mini Hivo is ready.` بالضبط، بما فيها النقطة | 8 | 0 |
| `20261119T001727-02b26fde` | وقف عند سقف طلب واحد؛ لا ملف ولا root verification | 1 | 1 متوقّع |

طلبات الـlive دي استخدمت الـprovider المحلي الحقيقي، مع guard يمنع
تشغيل الكود المتولّد على الجهاز المشترك. الحالتين الناجحتين اختاروا
`baseline`؛ مش قياس لجودة الـrecursive split.

**الحد المفتوح:** الـheadless checkout اجتاز الاختبارات الوظيفية
الـcontrolled. في تجربة admission فعلية، الـJobService رجّع
`blocked/docker_unavailable`، من غير patch أو تغيير على الأصل.
ما اتنفّذش اختبار توليد patch لايف مع عامل Docker معزول لأن الـdaemon
غير متاح ومفيش image معتمدة متضبطة. ده واحد من الـ5 skips، والأربعة
التانيين اختبارات legacy كانت متوقفة من قبل.

الـraw logs، جرد الـrefs، والـGit bundle محفوظين محليًا منفصلين عن Git.
نظافة `main` المحلي لا تعني نشره: مفيش push ولا حذف لأي remote branch.
