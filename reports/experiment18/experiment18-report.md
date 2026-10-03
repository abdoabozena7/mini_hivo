# Experiment 18 — No-Tool Worker Exit Guard

نفس العقود المجمدة، model و28 خطوة والسياسات الأخرى. الاختلاف الوحيد في مقارنة Python هو worker_no_tool_policy.

| الدفعة | أول tool call | context decision | أول legal mutation | verification executed/PASS | Child verified | Root verified | no-progress exits |
|---|---:|---:|---:|---:|---:|---:|---:|
| Python current | 0/3 | 0/3 | 0/3 | 0/3 / 0/3 | 0/3 | 0/3 | 0 |
| Python reanchor | 3/3 | 0/3 | 0/3 | 0/3 / 0/3 | 0/3 | 0/3 | 0 |
| Python fresh | 3/3 | 0/3 | 0/3 | 0/3 / 0/3 | 0/3 | 0/3 | 0 |
| Timer fresh | 3/3 | 3/3 | 3/3 | 1/3 / 1/3 | 0/3 | 0/3 | 0 |

## أول عائق معلن

- Python current: {'CONTEXT_INSUFFICIENT': 3}
- Python reanchor: {'CONTEXT_INSUFFICIENT': 3}
- Python fresh: {'CONTEXT_INSUFFICIENT': 3}
- Timer fresh: {'MUTATION_TARGET_UNRESOLVED': 2, 'CHILD_RECEIPT_INVALID': 1}

## أول حد فعلي في trace

- Python current: {'NO_TOOL_EXIT': 3}
- Python reanchor: {'POST_INSPECTION_PRE_CONTEXT_DECISION': 3}
- Python fresh: {'POST_INSPECTION_PRE_CONTEXT_DECISION': 3}
- Timer fresh: {'MUTATION_TARGET_UNRESOLVED': 2, 'CHILD_RECEIPT_INVALID': 1}

Scope/preservation counters: 0. Protected tests unchanged: yes.
في Python مع reanchor: كل التشغيلات الستة قرأت المصدر والاختبارات، ثم خرجت قبل context_sufficiency_check. رسالة controller هي CONTEXT_INSUFFICIENT مع تفصيل أن pre-mutation impact contract لم يُقبل؛ لا نعدّها failure في verification المنفذة.
الأعمدة تخص كل تشغيل من الثلاثة، وأول عائق معلن لا يعاد تفسيره من إخفاقات recovery اللاحقة.
العقود معتمدة مسبقًا؛ التخطيط الحر غير مقاس. 3 محاولات لكل مهمة لا تقدر reliability العامة.

[Raw results](C:/Users/A-plus/.codex/worktrees/experiment17-18/mini_hivo/reports/experiment18/experiment18-results.json)
