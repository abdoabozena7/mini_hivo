# دمج تاريخ Mini Hivo من غير فقدان الـ commits

تاريخ المهمة: 2026-11-16. الـ validation workflow المستخدم هو HarrTest 4.1.0
المثبت محليًا؛ مفيش تحديث للـ skill أو تغيير للموديل أثناء المهمة.

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
بعد الدمج والإصلاحات، الـ complete suite شغّل **1726 tests: OK، مع 4 skipped**.
الـ skips الأربعة دول legacy scheduler tests معلّمة أصلًا، مش tests جديدة
اتشالت عشان الدمج يعدّي. الـ self-test العام اتشغّل من نفس CLI واتراجع منفصلًا.

الـ focused evidence محفوظة للـ before/after، بما فيها:
false requirement conflicts، context-only completion، negated browser routing،
mutation count recovery، creation impact binding، وapproved-scope negative controls.
كان فيه كمان failed intermediate test run بسبب test selector كان بيفترض إن
أول tool message هي mutation feedback؛ بعد الاحتفاظ بالـ context transcript
اتحدث عشان يختار `edit_file` message بالاسم بدل ترتيب الرسائل.

**LIVE_ACCEPTANCE_PENDING:** سجل المحاولات النهائي ونتيجة فحص الناتج المستقل
بيتكملوا قبل إغلاق المهمة. وجود offline PASS هنا مش claim إن live acceptance
خلصت، ولا إن أي successful generated test يعتبر independent oracle.

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

حذف الـ local branches مش بيتم إلا بعد إثبات ancestry لكل الـ tips. الـ stash
القديم محفوظ، والـ secondary worktree ما بتتمسحش ولا بيتغير محتواها: فصلها عن
اسم branch بيحافظ على نفس commit ونفس الملفات بدل حذفها.

ما حصلش `push` أو حذف branches من GitHub. الطلب فوّض الدمج والتنظيف المحلي،
لكن مفيش تصريح صريح بالنشر؛ الـ remote branches الثلاثة تفضل محفوظة لحد ما
يحصل التصريح ده. بالتالي `main` الواحد هنا هو النتيجة المحلية، مش claim
إن GitHub اتنضف أو اتحدث تلقائيًا.

أي نشر لاحق لازم يبدأ بإعادة حصر remote tips، ودمج أي شغل جديد، وبعدها
normal non-force push لـ `main`. حذف remote names ييجي فقط بعد إثبات إن
نفس tips بقت reachable من الـ remote `main` المنشورة. مفيش force push
أو تخطي hooks ضمن الخطة.

المهمة ما غيرتش إعدادات خدمة Ollama المشتركة، وما شغلتش موديل خارجي مدفوع،
وما حذفتش user workspace أو runtime history قديم. نجاح sample جديدة لا
يلغي نتائج Timer/Python التاريخية ولا يثبت إن الـ prototype بقى موثوق في كل
أنواع المشاريع؛ الفرق بين الاتنين موضح في
[حالة المشروع](PROJECT_STATUS.md) و[فهرس النتائج](../reports/INDEX.md).
