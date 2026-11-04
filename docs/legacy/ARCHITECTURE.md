# System architecture

## Components and routing

`evoagents/core.py` contains the `Orchestrator`, SQLite `Store`, role roster and JSON protocol. A human supplies a goal to the `group` room. Each specialist first bids on the goal with a fit score and proposed contribution. The DeepSeek planner receives these bids and specialties, then returns 1–5 sequential subtasks. The router validates agent names and task shape, logs assignments, then invokes each specialist. Specialists may request a tool, ask the human, delegate a child goal, or finalize. Delegation is capped at depth two; each agent turn is capped at eight decisions to bound runaway loops.

Specialties are researcher (search), coder (files and Python), and reviewer (verification and synthesis). Routing is model based, so poor plans remain possible. The full group transcript is persistent in SQLite. `dm:<agent>` rooms hold private human–agent clarification. The current CLI allows only these three DM names. Private messages are excluded from other agents' context. Group messages are intentionally shared.

## Memory and evolution

Every completed subtask writes an agent-scoped success lesson; failures write an agent-scoped avoidance lesson. Retrieval takes up to four recent lessons with lexical overlap with the next goal. Only records with the same agent name are queried. This is a simple, inspectable form of experiential evolution, not model weight training. The lesson appears in the next prompt. The benchmark documents entry counts, while a live evaluation should additionally compare outcomes before and after learned lessons using the same task family.

## Tools and isolation

`ToolBox` resolves all file paths under `.evoagents/agents/<agent>/` and rejects absolute paths, traversal, symlink escapes and unsupported file suffixes. It supports read, write, delete, search, Python execution, Git commit and Git push. Delete and push require explicit `yes` through the CLI. HTTPS search runs in the trusted host process and returns a bounded text excerpt with source URL.

Python scripts execute only through Docker. The container gets that agent's directory mounted read only at `/work`; network is disabled, capabilities are dropped, privilege escalation is disabled, root filesystem is read only, and CPU, memory, process and time limits apply. The process runs as UID 65534. Docker is a prerequisite; there is no unsafe host fallback. Each agent's Git operations are scoped to its private directory. A team release repository can incorporate reviewed artifacts after human review.

This is a prototype security boundary. The host orchestrator and its credentials are trusted. Search results and model responses are untrusted input and should be treated as data; the current JSON tool protocol limits action names but does not solve all prompt injection risks. For production deployment, add an egress proxy with URL allowlists, stronger audit logs, and a tested container runtime policy.

## Metrics

Every task stores start/end timestamps, status and output. A run reports successful subtasks divided by total subtasks and end-to-end wall-clock seconds. `metrics` reports aggregate completed tasks and per-task durations. At present “completed” means the agent reached a final response without a fatal exception; semantic correctness requires external task-specific grading. The course test set should supply that grader before reporting final completion rate.

`evoagents/evaluate.py` accepts JSONL cases and writes a new evidence JSON file with each result, elapsed time and memory counts before/after. An optional `expected_contains` marker provides a narrow automatic check; its score must not be substituted for a course rubric score.
