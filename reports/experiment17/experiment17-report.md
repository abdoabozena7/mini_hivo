# Experiment 17 — Field-Scoped Verification Classification

التغيير الوحيد هو مدخلات infer_web_profile: goal/requirements/approved paths بدل JSON العقد كله. current يظل الـdefault.

## عقود مجمدة ونفس المعنى

| تحقق التصنيف | current | field_scoped |
|---|---:|---:|
| Timer contracts classified timer | 0/3 | 3/3 |
| Game contracts classified game | 6/6 | 6/6 |
| Identity/hash perturbations preserving field-scoped profile | N/A | 27/27 |

كل perturbation يغير IDs أو hashes أو provenance فقط. المرجع عقود Timer من Exp16 وعقود اللعبتين من Exp15.

## تشغيل جديد بنفس Worker و28 خطوة

| المهمة | أول تعديل قانوني | Child verifier started | Child verified | Root verified | Grounding terminal |
|---|---:|---:|---:|---:|---:|
| timer_pause | 3/3 (100%) | 2/3 (66.67%) | 0/3 (0%) | 0/3 (0%) | 3/3 (100%) |
| arena_arrow | 3/3 (100%) | 3/3 (100%) | 3/3 (100%) | 3/3 (100%) | 0/3 (0%) |
| arena_q_restart | 3/3 (100%) | 3/3 (100%) | 3/3 (100%) | 3/3 (100%) | 0/3 (0%) |

Child browser profiles الصحيحة: timer_pause=3/3 (100%), arena_arrow=3/3 (100%), arena_q_restart=3/3 (100%)
Child browser behavior PASS: timer_pause=3/3 (100%), arena_arrow=3/3 (100%), arena_q_restart=3/3 (100%)
أول blocker معلن في Timer: {'CHILD_RECEIPT_INVALID': 2, 'MUTATION_TARGET_UNRESOLVED': 1}
Grounding terminal يشمل محاولات recovery اللاحقة؛ ليس بالضرورة أول blocker.
Scope/preservation counters: 0. Protected tests unchanged: yes.
أي فشل بعد اختيار profile صحيح يُسجل منفصلًا، ولا ينسب إلى classifier.

## الحدود

العقود معتمدة مسبقًا؛ التخطيط الحر غير مقاس. 3 محاولات لكل مهمة لا تقدّر reliability العامة.
[Raw results](C:/Users/A-plus/.codex/worktrees/experiment17-18/mini_hivo/reports/experiment17/experiment17-results.json)
[Frozen suite](D:/projects/Ai/mini_hivo_experiment17/isolated-v2)
