# Freshness verifier replaces valid answers to local, time-independent tasks (also breaks `output_type`)

## Summary
On a small local model, the freshness classifier sometimes marks a purely local task (reading source files that
tools return) as time-sensitive with `needs_live_data`. The closure step then replaces the model's correct answer
with "I couldn't provide a grounded current general answer because Missing live-data evidence for a
freshness-sensitive answer.. Please retry with live data available ...". With `output_type=...` this replacement
text is what gets validated, so the turn raises `AgentOutputValidationError` even though the model returned
valid JSON.

## Environment
- openminion 0.1.20 (PyPI), Python 3.12, Windows 11; Ollama 0.40.15, `qwen2.5:7b`

## Steps to reproduce
Our DriftCheck agent sends prompts like "doc says: `openminion skill learning-observation-list`; static checker
evidence: ...; Investigate". In our first run over 11 such prompts, 3 investigator turns and 1 reporter turn
ended with the message above. The prompts contain no request for news, prices or dates. After we added "This is a
static code-reading task ... does not depend on dates, news or live data" to every prompt, the next two runs
(22 findings, ~60 turns) had no freshness refusals.

## Expected
- A way for an application to declare an agent or turn as local-only (for example `freshness="off"` on the agent
  profile or a turn option), so the classifier is not consulted for tasks that only use local tools.
- When the verifier blocks, the original answer should be kept in metadata, and `output_type` validation should
  report that the freshness verifier replaced the answer instead of a generic JSON error.

## Actual
No opt-out; the answer is replaced; `AgentOutputValidationError` with the refusal text as `raw_text`.

## Cosmetic
`build_freshness_failure_message` joins reasons that already end with "." and then appends ". ", producing
"answer.." (`src/openminion/modules/brain/runtime/verification/policy.py`).

## Related
#635 (extra classifier call per turn), #720 (closure step replacing a valid `output_type` answer).
