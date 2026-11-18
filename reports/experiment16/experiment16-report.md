# Experiment 16 — Cross-Domain First-Blocker Isolation

Timer وPython فقط؛ 3 fresh runs لكل مهمة، من عقود Experiment 12 المعتمدة وبذور مطابقة.
gemma4:e4b و28 خطوة، contract_fallback + strict evidence + evidence_bound. لا تغيير في production أو الـdefault.

## الوصول إلى الحدود

| الحد | Timer | Python |
|---|---:|---:|
| Contract ready | 3/3 (100%) | 3/3 (100%) |
| Worker started | 3/3 (100%) | 3/3 (100%) |
| Context sufficient | 3/3 (100%) | 0/3 (0%) |
| Source actually inspected | 3/3 (100%) | 0/3 (0%) |
| First legal mutation | 3/3 (100%) | 0/3 (0%) |
| File changed before rollback | 3/3 (100%) | 0/3 (0%) |
| Child executable route observed | 0/3 (0%) | 0/3 (0%) |
| Formal child verification invoked | 2/3 (66.67%) | 0/3 (0%) |
| Child verified | 0/3 (0%) | 0/3 (0%) |

هذه milestones وليست بالضرورة ترتيب استدعاء الأدوات؛ بعض القراءة تحدث قبل context gate.
وجود ROOT applicability artifact أو browser call داخل الـWorker لا يعني أن Child verification بدأت.
File changed تعني تعديلًا فعليًا أثناء محاولة الـWorker؛ عند فشل الـChild قد تُرجع transaction الملف لاحقًا.

## أول blocker حقيقي

| المهمة | أول مرحلة توقف / 3 runs | التفاصيل |
|---|---:|---|
| timer_pause | mutation_grounding_after_worker: 1/3, child_verification_profile_mismatch: 2/3 | run 1: mutation_grounding_after_worker (terminal=MUTATION_TARGET_UNRESOLVED, underlying=REPLACE_NOT_FOUND, commits=3, full_refreshes=3, no-op attempts=9); run 2: child_verification_profile_mismatch (terminal=VERIFIER_UNAVAILABLE, underlying=MUTATION_ANCHOR_REQUIRED, commits=3, full_refreshes=1, no-op attempts=1); run 3: child_verification_profile_mismatch (terminal=MUTATION_TARGET_UNRESOLVED, underlying=MUTATION_ANCHOR_REQUIRED, commits=11, full_refreshes=6, no-op attempts=5) |
| python_clamp | pre_mutation_context_or_impact: 3/3 | run 1: pre_mutation_context_or_impact (terminal=CONTEXT_INSUFFICIENT, underlying=n/a, commits=0, full_refreshes=0, no-op attempts=0); run 2: pre_mutation_context_or_impact (terminal=CONTEXT_INSUFFICIENT, underlying=n/a, commits=0, full_refreshes=0, no-op attempts=0); run 3: pre_mutation_context_or_impact (terminal=CONTEXT_INSUFFICIENT, underlying=n/a, commits=0, full_refreshes=0, no-op attempts=0) |

Shared first-blocker phase: **none**.
Parent INTEGRATION_NOT_READY بعد فشل الـChild سبب ثانوي، وليس أول blocker.
في Timer run 3 فشل browser verification أولًا، ثم انتهت محاولة Recovery لاحقة عند grounding؛ الجدول يسجل أول فشل سببي والـterminal كلًا على حدة.
في Python نفّذ الـWorker صفر tool steps في المحاولات الثلاث، فلم يصل إلى context decision؛ رفض الـpre-mutation impact contract نتيجة لهذا المسار.

## تشخيص profile المتصفح

في 2 محاولة، فحص المتصفح اختار game للمؤقّت. إعادة حساب نفس infer_web_profile بعد حذف execution_contract_hash فقط تعطي timer؛ الـhash يحتوي النص `3d`، والخوارزمية تبحث عنه كـsubstring داخل JSON العقد كله. المتصفح فتح الصفحة وenvironment_error=false؛ الرفض بسبب profile غير مناسب. هذا تشخيص read-only، ولم تُعدَّل دالة التصنيف أو الـverifier.

## الضبط وحدود الاستنتاج

Scope/preservation counters: **0**؛ protected tests unchanged: **yes**.
العقود والبذور والموديل والميزانية والسياسات مثبتة؛ تم تسجيل الأدوات والحدود فقط، دون إصلاح أو تغيير قرار.
هذه عينة مهمتين وثلاث محاولات لكل واحدة. لا تعميم على كل browser/Python projects.

[Raw results](D:/projects/Ai/mini_hivo/reports/experiment16/experiment16-results.json)
[Frozen suite](D:/projects/Ai/mini_hivo_experiment16/suite-v1)
