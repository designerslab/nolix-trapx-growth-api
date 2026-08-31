AGENT-FIRST ACTION RULE

For every weekly action:
1. Detect the anomaly/opportunity.
2. Use available Growth API tools to investigate it automatically.
3. Report `Agent inspected: Yes/No`.
4. Provide an `Inspection score` (0-100) appropriate to the issue.
5. State verified evidence, not just a task for a human.
6. State an `Agent conclusion`.
7. Set `Human action required: Yes/No`.
8. Escalate only when the evidence is insufficient, the required tool/data is unavailable, or a destructive/business-sensitive change needs approval.

Example:
Action 1 — Referral traffic anomaly
Agent inspected: Yes
Change: 11 -> 102 sessions
Inspection score: 15/100 bot-risk
Finding: Low evidence of bot traffic
Evidence: 102 sessions, 94 active users, 55 engaged sessions, 53.9% engagement
Agent conclusion: No strong bot-like pattern from engagement/user evidence. Inspect top source domains automatically.
Human action required: No, unless an unfamiliar/high-risk source is found.
