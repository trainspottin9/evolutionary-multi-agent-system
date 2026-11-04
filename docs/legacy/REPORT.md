# Test and performance report

## Scope and method

The course mid/final test sets were not supplied with the saved specification. This report covers local protocol verification only. `python -m unittest discover -v` tests routing, persistent task metrics, agent-specific memory, private chat separation, path isolation and approval of deletion. `python benchmark.py` runs five deterministic fixture goals, each producing two subtasks. The fixture uses scripted JSON decisions rather than a live DeepSeek model.

## Observed local results (2026-10-26, Windows/Python 3.11)

| Measure | Result |
|---|---:|
| Unit tests | 3 passed / 3 run |
| Fixture goal completion | 5 / 5 (100%) |
| Fixture subtask completion | 10 / 10 (100%) |
| Mean end-to-end run time | 0.035 s |
| Median end-to-end run time | 0.035 s |
| Per-run times | 0.037, 0.035, 0.035, 0.037, 0.033 s |

These figures measure protocol plumbing and local SQLite/file operations. They do not measure model quality, web search quality, Docker execution speed, or success on unseen course tasks. Run times vary between machines and runs.

## Failure analysis and limitations

- Docker is not installed on this machine. The Python execution tool fails with a clear error; isolated code execution has not been exercised here.
- No DeepSeek team API key was available, so live planning, clarification behavior and tool choice were not measured.
- No course dataset or grading rubric was available. The current status metric counts fatal-free completion and can overestimate true task success. Final reporting must grade the actual outputs against course criteria.
- An agent can produce an incorrect final answer after a tool result. A future evaluator should require assertions or reviewer checks before counting semantic success.
- Search quality and prompt-injection resilience are not established by the offline fixture.

## Memory evolution analysis

Across five fixture runs, the coder accumulated five success lessons and the reviewer five; researcher accumulated zero because the fixture never routed work to it. Repeated runs showed the same successful scripted behavior. The fixture cannot establish that memory improved performance. For the released test set, record memory snapshots before/after each run, compare outcomes on matched tasks with memory enabled and disabled, and report whether lessons changed a subsequent agent decision. Keep the test set partition fixed and avoid using final-test answers as training data.

## Course-set result table (to fill from real runs)

| Dataset | Goals | Semantic completion | Subtask completion | Mean time | Failure categories | Memory effect |
|---|---:|---:|---:|---:|---|---|
| Mid test set | pending release/access | pending | pending | pending | pending | pending |
| Final test set | pending release/access | pending | pending | pending | pending | pending |
