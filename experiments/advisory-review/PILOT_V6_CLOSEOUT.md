# Pilot v6 closeout — advisory-review rubric comparison

Date: 2026-10-18. Status: EXPLORATORY_COMPLETED; NO_REVIEW_QUALITY_LIFT_DEMONSTRATED.

This analysis uses the three owner-supplied execution summaries and the nine-report adjudication worksheet. All nine Codex CLI runs (0.163.0, gpt-6-luna, medium reasoning) exited successfully, produced locally valid reports and did not show tool events.

| Arm | Runs | Findings | Findings consistent with spec and code | Seconds | Input tokens | Output tokens | Total tokens |
|---|---:|---:|---:|---:|---:|---:|---:|
| A baseline | 3 | 2 | 2 | 41.361 | 47247 | 957 | 48204 |
| B gstack-inspired | 3 | 2 | 2 | 32.256 | 43831 | 663 | 44494 |
| C Superpowers-inspired | 3 | 2 | 2 | 33.240 | 43787 | 723 | 44510 |
| Total | 9 | 6 | 6 | 106.857 | 134865 | 2343 | 137208 |

Case-01: all three identified string-prefix path containment accepting sibling directories. Case-04: all three identified insufficient verification and digest conditions before integration. Case-05: none reported a defect and the implementation meets the visible example specification. Direct local reproductions corroborated the case-01 and case-04 claims. Six reported detections therefore correspond to two distinct issues, not six issues.

B consumed 22.0% less wall time and 7.7% fewer observed tokens than A in this small sample; C consumed 19.6% less wall time and 7.7% fewer tokens. These differences are descriptive only; different prompt sizes, token caching, execution order, and model variance are not controlled. No measurable detection advantage was seen in these cases.

Limitations: three synthetic cases, one execution per arm per case; inspired rubrics are not original gstack or Superpowers skill executions. This was a source/spec verification, not a private-keyed formal adjudication. Historical commits on this public branch revealed reproduction information, so the cases are unsuitable for strong blind benchmark claims. Operator-reported 12 runner tests and six fixture tests passed after the earlier syntax correction.

Recommendation: close the v6 pilot. Do not integrate new review agents or skill dispatch into ProjectCTL based on these results. Design a more difficult independently held private evaluation and separately measure real-task ProjectCTL dogfooding against direct Codex. Continue to leave M6.0 and all runtime and accepted architecture decisions untouched.
