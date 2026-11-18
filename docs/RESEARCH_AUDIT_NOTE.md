# Research note — When splitting helps a small coding model

**2026-11-18. Proposal, not a measured model-quality gain.** This note follows the project's existing [evidence-licensed decomposition direction](RESEARCH_DIRECTION.md). The fresh results in [R_UPDATE_005](../updates/R_UPDATE_005.md) show that the controller can misread both success and failure. They do not show that an adaptive swarm finishes more real tasks.

## أقوى فكرة للـpaper

**Before You Split: Evidence-Licensed Decomposition for Small Coding Agents**

السؤال مش «هل تقسيم الشغل كويس؟». السؤال: **هل نقدر نعرف إمتى المشكلة كبيرة فعلًا، وإمتى المهمة وقفت عشان الـtool contract أو الـverifier أو الـhandoff غلط، ونستخدم الفرق ده عشان الموديل الصغير يسلّم شغل أحسن بنفس الميزانية؟**

الـmechanism المقترحة: لو الفشل له سبب مرصود ينفع يتصلّح جوه **نفس الصلاحية ونفس الميزانية**، نفّذ تصحيح واحد محدد، وبعدين خُد observation جديدة قبل ما تستخدم الفشل كدليل على إنك لازم تقسّم أو توقف بسبب القدرة. لو السبب مش واضح، سجّله `unknown`. لو في منع حقيقي، approval ناقصة، إلغاء أو deadline، اقف فورًا. التصحيح ما يخمّنش arguments، ما يغيّرش scope، وما يبدّلش oracle عشان كود يعدّي.

المفيد في النتائج الجديدة إننا قدرنا نفصل حاجتين: استدعاء ناقص اتردّ من غير ما يلمس المنتج؛ وتعديل حقيقي غيّر المنتج بعد الـPASS. تثبيت الفرق ده شرط للقياس، لكن **لسه ما نفّذناش أو قسنا سياسة الـlicensing الكاملة**. ما نكتبش في الـabstract إننا قللنا نسبة التقسيم أو رفعنا live success بناءً على replay.

## ليه الأرقام الحالية ما تجاوبش سؤال الـswarm

- [ملف release acceptance](../reports/e2e/2026-11-17/release-acceptance.json) فيه تلات مهام Python CLI متقبلة باختبار مستقل. التلاتة دخلوا من `auto`، لكن التلاتة اختاروا `baseline`. ده دليل إن المسار المركّز نجح في الحالات دي، **مش** دليل إن التقسيم هو سبب النجاح.
- [سجل الـ27 محاولة](../reports/e2e/2026-11-17/validation-summary.json) فيه 10 `done`، منهم 9 اتقبلوا مستقلًا وواحدة اترفضت. المحاولات على revisions وsource fingerprints مختلفة، ومنها interruption وhost block. ما ينفعش نطلع rate لنسخة ثابتة من الـ27، ولا نخفي السلبيات ونقول 3/3 reliability.
- [Experiment 1](../reports/experiment1/final/report.md): التقسيم المبكّر وفّر calls/وقتًا في العينة، لكن مفيش Root verified في أي arm (`0/2` و`0/2`) ووقف أبكر. الفشل الرخيص مش نجاح أكفأ.
- [Experiment 12](../reports/experiment12/experiment12-report.md): `compatible` رفع Root verified إجمالًا من `3/15` إلى `5/15` في frozen contracts، لكن Node نزل من `3/3` إلى `0/3`، والـTimer وPython فضلوا `0/3`. وفي الـprotocol set، تقليل قبول الأدلة الغلط صاحبه زيادة رفض الأدلة الصحيحة (`5/17` إلى `11/17`). لازم نقيس الاتنين ونفصّل النتائج بالعائلة.
- [Experiment 17](../reports/experiment17/experiment17-report.md): تصنيف Timer اتحسن من `0/3` إلى `3/3` في الـclassification fixtures. وفي محاولات العلاج browser behavior كان PASS (`3/3`)، لكن Root فضل `0/3`. نقل أول blocker مش هو تسليم المنتج. [Experiment 19](../reports/experiment19/context-decision-closure-report.md) كمان فضل `0/3` في قرار السياق في كل arm، مع زيادة إجمالي calls من 15 إلى 27.
- الـfreeze من approved contract مفيد لعزل execution، لكن ما يقيسش فهم الطلب أو اختيار الـpath أو الموافقة. وعشان `baseline` و`recursive` مش بيستقبلوا نفس preparation، مقارنة الـCLI flags كما هي مش ablation للتقسيم وحده. سجل `current` كسياسة كاملة، مش كاسم مقياس صالح للمقارنة عبر الفروع.

## تجربة تفصل بين أسباب التحسّن

**1. تحقق إن المشكلة بتظهر طبيعيًا.** خُد cohort development جديدة ومقفولة قبل ضبط السياسة. سجّل نسبة المهام والـfailure episodes اللي حصل قبل split/stop فيها tool-schema أو stale-context أو verifier-mode failure مثبت. شخصين يراجعوا عينة صغيرة من traces من غير ما يعرفوا الـarm، مع تسجيل اختلافهم و`unknown`. الحقن المقصود يدي ground truth في cohort منفصلة؛ ما يتحسبش كانه انتشار طبيعي. الـThree.js run الحالية development evidence مش holdout.

**2. اعمل مقارنة على نفس الـengine في أربع arms.** ثبّت Gemma model digest/quantization، prompts المشتركة، repo state، الصلاحيات، الـtool schemas، الـfalsifier/acceptance protocol، وميزانية واحدة للـtokens والـtools والـwall time. ما تطفّيش safety checks عشان تعمل control.

| | نفس سياسة الفشل الحالية | تصحيح سببي محدود قبل قرار الـsplit/stop |
|---|---|---|
| **Focused / لا تقسيم اختياري** | تكلفة ونجاح المسار الواحد | يختبر لو التصحيح وحده كفاية من غير swarm |
| **Adaptive split** | أثر التقسيم الحالي | يختبر هل التصحيح يساعد اختيار حجم المهمة |

المهام اللي فيها structural decomposition obligation ما تتنفذش بسلطة مخالفة عشان تدخل arm الـfocused. إمّا كل arms تحترم نفس الـmandatory split، وتقارن بعدها اختيارات الـgranularity المسموحة، أو تقيس المجموعة دي separately. اعمل بعد الـpilot مقارنة مستقلة بـ **diagnostic message فقط** و**generic retry بنفس التكلفة** عشان تعرف إن المكسب مش من إضافة شوية tokens. Candidate escalation لأكبر model يبقى reference منفصل لو اتقاس؛ مش علاج مخفي جوه arm الموديل الصغير.

**3. اختبر الـgranularity بدل افتراض «الأكتر أحسن».** ثبّت intent والـscope. قارن شغل جوه owner واحدة، split على interfaces فعلاً مستقلة، وsplit أنعم. صنّف coupling من العقد والملفات قبل النتائج. مثال full-stack: الـbackend والـfrontend يتفقوا على schema ومعاني الأخطاء؛ اختبر رحلة browser بتكتب للـAPI وبعدين تقرا النتيجة بعد reload. اختبار منفصل لكل جزء مش هيكشف توافق غلط بين الاتنين. ما تسميش الـscheduler الموجود parallel؛ أي parallel treatment لاحق يحتاج isolated edits، frozen interfaces، merge وroot acceptance، ويحسب تكلفتهم.

## الـbenchmark والـoracles

| عائلة | النجاح اللي نحسبه | الـnegative control |
|---|---|---|
| Python/Node CLI صغيرة | exact output، exit behavior ومدخلات حدودية من test مستقل | التنفيذ يشتغل في happy path بس؛ أو test منتَج يقبل output غلط |
| Existing repo | صلاحية محددة، behavior جديد + regressions على interfaces المحمية | patch يعدّي test جديد لكنه يكسر consumer موجود أو يغير غير المصرّح |
| Full-stack مترابط | رحلة HTTP/browser للمنتج المحفوظ، success وfailure وstate بعد reload | backend وfrontend كل واحد يعدّي لوحده لكن الـschema مش متوافق |
| Recovery/denial | تصحيح مسموح يوصل لإثبات جديد؛ رفض مشروع يفضل blocked بلا mutation | outcome قديم، verifier مشغّل في mode غلط، أو prerequisite اتعمله rollback |

افصل الـdev prompts عن holdout من repositories/tasks مش مستخدمة في tuning. الـoracle يبقى خارج مساحة تعديل الـWorker ويعدّي positive reference ويرفض defective variants قبل التجربة. سجّل كل المحاولات في المقام المحدد مسبقًا؛ اعرض host/approval/budget blocks منفصلة بدون تحويلها لنجاح أو حذفها. الحالة اللي هدفها رفض صحيح تُقاس كمهمة safety منفصلة، مش كنجاح توليد منتج.

## الأرقام اللي نخليها تحسم القرار

1. **الـprimary endpoint:** نسبة المهام اللي الـartifact النهائي بتاعها عدى **كل** checks المستقلة عند budget ثابت. `ROOT VERIFIED` والـchild receipts وfirst legal mutation تبقى diagnostics، مش البديل.
2. **هل القرار اتحسن؟** كم split أو capability stop كان مبنيًّا على خطأ مش في الـcoding؟ وفي المقابل، كم split مفيد اتأخّر أو ما حصلش في clean hard tasks؟ ممنوع نكسب المقياس الأول بمنع التقسيم في كل الحالات.
3. **تكلفة إجمالية:** سجّل كل calls والأدوار، prompt and output tokens (والقياس الناقص يتوسم missing)، tool usage وlatency. احسب التكلفة لكل نجاح مستقل من تكلفة **كل** المحاولات، وعند صفر نجاح ما تعرضش رقم تكلفة مزيف. كون inference local ومفيش فاتورة API لكل call ما يخليش الوقت أو compute ببلاش.
4. **Fairness & integrity:** ثبّت model/runtime fingerprints، workspace resets، permissions وtest hashes. [الـprovider حاليًا](../mini.py) بيبعت `seed: 0`؛ عرّف دعم seeds متقابلة قبل ادّعاء multi-seed. وزّع ترتيب arms واعزل cold/warm runs. درّب حدود الميزانية والعينة على dev فقط، وبعدها preregister رقم العينة وعتبة التحسّن وعدم التراجع. اعرض paired intervals على مستوى المهمة/المستودع، مش كل child أو retry كعينة مستقلة.

ادّعاء **جودة أعلى عند نفس التكلفة** يختلف عن **نفس الجودة عند تكلفة أقل**؛ اختبر الأول بميزانيات متساوية، والتاني بمنحنى cost/quality وحد non-inferiority محدد مسبقًا. الـpaper تبقى أقوى لو بتبين فين التقسيم بيضر كمان، خصوصًا في المهام اللي الـinterface فيها لسه بيتغير.

## حدود novelty وإمتى نغيّر رأينا

[ADaPT](https://aclanthology.org/2024.findings-naacl.264/) سبق adaptive splitting بعد تعثر التنفيذ. [Meta-Agent](https://arxiv.org/abs/2605.25233) بالفعل بيربط attribution بإعادة التنفيذ أو التقسيم. و[AI Agents That Matter](https://arxiv.org/abs/2407.01502) وضّح ليه لازم cost وholdout سليمين. مش هنقول إن «أول swarm بالتقسيم والـverification». الفرضية الأضيق القابلة للنشر هي **شرط تصحيح منفَّذ وإثبات حديث قبل تفسير الفشل كدليل على حجم المهمة، مع اختبار أثره عند budget واحد ومن غير تعديل السلطة**. لسه محتاج citation review أدق قبل أي novelty claim.

لو السبب المستهدف نادر في natural runs، أو العلاج generic بنفس التكلفة بيجيب نفس النتيجة، أو المكسب اختفى على holdout، أو منع تقسيم مفيد، يبقى دي نتيجة سلبية مهمة. ما نقلبش definition الجودة، وما نختارش أفضل retry. أول خطوة عملية بعد الـaudit: cohort تطوير صغيرة محفوظة، task budget حقيقي على مستوى الـroot، وoracles مستقلة؛ بعدها نفكر في حملة live بميزانية محددة، على بيئة تنفيذ معزولة وبموافقة واضحة.

## متابعة تجربة الإصلاح المتوازي

- **تحديد سبب الفشل غير إثبات إن تصحيحه حسّن الناتج.** لما schema rejections أو browser stagnation تتسجل بالسبب/الملاحظة بدل `TASK_TOO_BROAD`، نقدر نعدّ قرارات الـsplit الغلط. لكن لازم arm منفصلة تنفذ correction وتتحقق من النتيجة؛ مجرد تسمية أدق أو توقف أبكر مش مكسب في task success.
- **الترتيب غير التوازي.** لو producer اتأخر عن consumer في ترتيب الخطة، لازم الـscheduler يحترم dependency المرصودة، من غير ما يدّعي تشغيل متوازٍ أو يخترع edge مش معلنة. قبل أي مقارنة parallel، افصل overhead التسليم والدمج وفشل الـinterface عن تكلفة التنفيذ نفسه.
- **الـreceipts لازم تمثل المسار اللي اتنفذ فعليًا.** PASS جديد على test مختلف لا يمحو FAIL في obligation تانية، وتغير dependency ممكن يبطل PASS حتى لو ملف الـentrypoint نفسه ثابت. قِس رفض المنتج الصحيح وقبول المنتج الغلط كل واحد لوحده؛ تشديد الـgate ممكن يخفض الأوّل أو يرفع تكلفة الاسترجاع لو اتطبق بزيادة.
- **سقف الاستدعاءات مش سقف الـtokens.** المقياس الجديد يفرّق بين عدّ طلبات inference (بما فيها retry) وبين `prompt_eval_count` و`eval_count` اللي المزود بلّغ عنهم. في تحليل الورقة نفصل task time عن startup canaries، ونحفظ missing telemetry كـmissing. المقارنة ذات سقف call/time متساوي لسه مش برهان على تساوي compute.
- **الـhost block جزء من النتائج، مش فشل من الموديل في حل المهمة.** أول تشغيلين حقيقيين للـbaseline على نفس `gemma4:e4b` ما وصلوش لطلب المهمة: واحد وقف بـ`MemoryError` عند التحميل، والتاني نفّذ 3/3 canaries فعلية لكن فشل في `CRITICAL_MEMORY_HEADROOM`. لحد ما يشتغل الـCLI وينتج artifact يعدّي الحكم المستقل، ما نعتبرش canary ناجحة دليل إن المهمة اتعملت.

### نتيجة الـlive pilot بعد ما الجهاز قدر يشغّل المهمة

النسخة قبل الإصلاح والنسخة بعده سلّموا نفس الـ14 bytes المطلوبة على `gemma4:e4b`، واتقرت من ملف محفوظ بعد الخروج، مش من رد الموديل. **الاتنين: 10 model calls و5 tool calls، والـauto اختار `baseline`.** يعني نتيجة الجودة في الحالة دي متعادلة، مش مكسب للـswarm. المحاولتين اللي وقفوا في التهيئة يفضلوا في السجل كمحاولات host-blocked.

النسخة الجديدة عدّت negative control لايف: `--max-model-calls 1` سمح بطلب مهمة واحد فقط بعد الـpreflight، وبعده وقف من غير artifact ومن غير `ROOT VERIFIED`. وفي التشغيل الناجح الـprovider سجّل **20,701 input / 926 output tokens**. حوالي **28% من التوكنز المبلّغ عنها** كانت في الـClarifier والـSpecifier والـFalsifier، مش الـBuilder. ده **وصف لرحلة واحدة**، مش تقدير تكلفة ثابت. النسخة الأقدم ما سجّلتش التوكنز، فما نقولش إن واحدة أرخص من التانية.

ده بيحدد حاجة عملية للـpaper: نحسب تكلفة التخطيط والـverification في نفس الميزانية، ونفرّق بين طلبات المهمة والـpreflight، ونساوي السقف من غير ما نعتبر عدد الـcalls بديلًا عن عدد الـtokens. كمان نختبر **ترتيب الـdependencies** و**قرار التقسيم** كل واحد لوحده؛ لو أصلحت handoff مع تغيير سياسة التقسيم في نفس المقارنة، مش هتعرف أنهي واحدة رفعت الجودة.

التفاصيل والـrun IDs والـoffline controls في [R_UPDATE_006](../updates/R_UPDATE_006.md). لسه محتاجين تجربة مستقلة على مهام مترابطة فعلًا وoracles خارجية؛ ما اتقاسش live full-stack أو إثبات سببي لصالح التقسيم.

### نتيجة جديدة: إمتى الـverifier يغني عن model review؟

في [R_UPDATE_007](../updates/R_UPDATE_007.md)، جرّبنا نفس العامل على نسختين ونفس الطلب في حالتين: ملف فيه كلمة واحدة، وملف فيه جملة وعلامة ترقيم. في الـ4 تشغيلات الفعلية الناتج المحفوظ طابق البايتات المطلوبة. لما الـreadback أثبت **كل** المطلوب، شِلنا مراجعة الموديل للنتيجة نفسها، مش الـreadback ولا الـimpact gate. إجمالي الـmodel calls نزل من **21 لـ17**، والتوكنز المبلّغ عنها من **44,843 لـ37,735 (15.9% أقل)**. ده قياس على حالتين development، والـauto اختار `baseline` فيهم كلهم؛ مش نتيجة عن جودة الـswarm.

النتيجة مفيدة لتصميم الـpaper: **اكتمال الـoracle متغير لازم يتثبت أو يتقاس لوحده**. لو arm عندها حزم صغيرة بمخرجات قابلة للقياس بالكامل والتانية لسه محتاجة model review، ممكن جزء من توفير التكلفة ييجي من نوع الـverification، مش من قرار التقسيم. خَلّي سياسة الـverification واحدة في مقارنة `focused` و`adaptive split` الأساسية، ولو هتدرسها لوحدها قارِن مهام الـoracle بيغطيها بالكامل بمهام سلوك وتكامل مش مقفولة، وسجّل توفير التكلفة جنب نسبة النتائج الغلط اللي عَدّت أو النتائج الصح اللي اترفضت.

### Headless jobs: إثبات التسليم غير قياس جودة الموديل

في اختبار controlled، الـJobService وقف على خطة، وكمّل بعد موافقة على نفس الخطة من عملية Python جديدة، ورجّع diff اتطبّق على نسخة اختبار مستقلة. الـCLI طبع `SHIPPED` بدل `READY`، والمدخل الغلط فضل بيرجع exit code `2`، والنسخة الأصلية ما اتغيّرتش. اختبار تاني وصل من الواجهة للمحرّك الحقيقي ومرّ على خطوات التعديل والتحقق، لكن ردود الموديل فيه كانت scripted. ده يثبت سلوك الـworkflow في الحالات دي، مش نسبة نجاح Gemma على تعديل مشاريع موجودة.

محاولة الـlive على نفس الـAPI وقفت في `blocked/docker_unavailable` قبل تشغيل الـworker. مفيش patch اتسلّم، ومفيش محاولة استدلال اتقاس منها quality أو cost. للتجربة البحثية الجاية، نسجّل admission، والموافقة، وإنتاج candidate، وقبول الـpatch كحدود منفصلة. إلغاء المهمة أو إعادة المحاولة ما يحوّلش نجاح جزء داخلي إلى نجاح نهائي، ومينفعش تستبعد محاولات الجهاز المحجوبة من التقرير بعد ما تشوف النتيجة.
