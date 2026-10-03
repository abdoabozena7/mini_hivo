# Experiment 2 — experiment2-rkey-01

الخطة المعتمدة في المسارين: `465262cd697d45053c410406edb607373e771ddf06568ef752b11e4646185d43`

| المقياس | strict | contract_fallback |
|---|---:|---:|
| Advice مرفوضة | 1 | 1 |
| Mission fallback مستخدمة | 0 | 1 |
| وصل لأول Worker | لا | نعم |
| Child متحقق | لا | لا |
| Root متحقق | لا | لا |
| خرق للنطاق | 0 | 0 |
| خرق للـpreservation | 0 | 0 |

| النتيجة | strict | contract_fallback |
|---|---|---|
| أول blocker | `MISSION_COMPILATION` / `MISSION_COMPILATION_FAILURE` | `CHILD_VERIFICATION` / `EXECUTION_BUDGET_EXHAUSTED` |
| استدعاءات النموذج | 11 | 39 |
| الزمن بالثواني | 57.89 | 86.22 |

حالة واحدة لا تكفي لتقدير نسبة نجاح عامة؛ الجدول يقارن انتقال البوابة لنفس المهمة.
