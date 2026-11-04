# System architecture

## Goal and boundaries

EvoCollab translates a human's high-level text request into bounded tasks carried out by specialized agents. The backend is intentionally small and auditable: a CLI, a localhost Web interface, a provider interface, an orchestrator, SQLite stores, and a fixed set of tools. Only DeepSeek or HKGAI may be configured as the LLM provider. Documents generated for users are `.md` or `.txt`; `.py` and simple data/config formats are permitted as executable artifacts.

## Components and data flow

```text
Human CLI ──> Engine ──> LLM planner ──> validated DAG of 1–5 subtasks
                 │                          │
                 │                          └─> agent bids ─> assignment
                 │                                            │
                 ├─> event SQLite <────────── messages/actions/results
                 └─> agent executor ──> private memory + workspace
                                      ├─> bounded file/web/Git tools
                                      └─> Docker Python sandbox
```

`Engine.run` records the user request, obtains a structured plan, rejects malformed IDs or backward dependencies, and asks each agent to bid on each ready task. Bid scores are adjusted by the agent's prior success/failure balance. The chosen agent receives the task, dependencies' text results, and only its own relevant memories. It can call a tool, ask a human, post to the group, delegate to another specialist, or finish with a result and evidence. Delegation is capped at depth two and twelve total tasks; task execution is capped at twenty model steps per task. Dependency failures produce blocked records. Every finished task updates only its owner's memory.

## Communication

The v3 browser workflow retains durable review decisions and revision lineage on top of this execution architecture. See `docs/WORKFLOW.md` for state transitions and API routes.

`messages` stores human-agent DMs, group chat, task events, and directed agent-agent messages. A DM query filters to exactly one agent and the human. The CLI's `group` command invites each configured agent to reply in turn using direct chat history; task bids and results are kept in the task trace and excluded from the visible chat history. Delegation messages are addressed to the recipient agent. The orchestrator is the trusted broker and can see all messages; agents do not receive each other's private memories or workspace paths.

## Memory and evolution

Each agent has its own SQLite file at `agents/NAME/memory.sqlite3`, separate from its `workspace/`. Each experience stores task text, outcome, lesson, and time. Recall ranks up to 200 recent memories by English word and Chinese bigram overlap with the current task, discards weak matches and duplicates, and adds at most three relevant lessons to a prompt. Only matching outcomes adjust a later role bid, with a bounded weight that grows gradually with evidence. Failed attempts are marked as cautions. This is a simple, transparent online adaptation mechanism. A stronger semantic retrieval or learned policy could replace it later. No performance gain is claimed without an ablation on the released dataset.

`--no-memory` disables recall, bid adjustment, and new experience recording. The evaluator records `memory_enabled` in each report so a fresh-state control can be compared with an enabled run under the same prompts, model, and approval policy.

## Isolation and trust

File tools resolve paths against one agent's workspace, reject traversal, symlink escape, `.git` access, oversized content, and unsupported suffixes. Agents share selected files only through an explicit publish/import exchange; the receiving agent cannot read the source workspace directly. Python scripts run in an official Python Docker image with only that workspace mounted, nonroot UID, read-only container root, no network, no Linux capabilities, no new privileges, memory/CPU/PID limits, and a timeout. Docker is mandatory; execution fails closed if it is absent. The container may modify its own workspace, including `.git`, but cannot mount another agent's workspace or its memory database. The trusted host process runs web and Git tools with validated parameters. HTTPS retrieval rejects private/local addresses and checks redirect targets; this is a prototype-level SSRF boundary, not a hardened enterprise network proxy. Docker itself and the host OS remain part of the trusted computing base.

The LLM receives tool outputs as untrusted data. It can request actions, but the fixed dispatcher validates the action name and arguments. Python execution, deletion, and pushing to GitHub require a recorded human approval. In noninteractive evaluation, these actions are denied unless the operator explicitly preapproves their class. Git operations also run in Docker, with the same private workspace mount and fixed arguments; hooks and credential helpers are disabled. Push rejects repository URL rewrite rules. A GitHub token is scoped to the requested GitHub URL and passed through a container environment variable only for the approved push. API and GitHub tokens are never written into project files by the application.

## Provider and failure handling

`ChatProvider` calls a JSON-compatible `/chat/completions` endpoint with JSON mode, bounded output, a 90-second timeout, and limited retries on transient failures. The provider name is allowlisted to DeepSeek or HKGAI. The course-provided HKGAI address (`https://api1.hkgai.net/v1`) and model (`t2_hkgai-v3_fp8_1m_e7`) are defaults. The key comes from an environment variable or a local mode-600 credential file, never from repository source. Malformed planning outputs are rejected. Tool errors return to the executor for a possible correction. A provider failure or step limit records a failed task rather than silently claiming completion.

## Metrics and evaluation

The event database stores start/end times and status for the goal and each descendant, including delegated tasks. Subtask completion rate is successful descendants divided by all descendants. Overall goal completion requires all planned subtasks to succeed. Wall-clock seconds run from goal assignment to final output. The JSONL harness adds per-case elapsed time and optional objective checks for result text and generated files; the report labels cases without objective checks `self_reported`. A full evaluation should repeat the official dataset under fixed model/settings, report denominator and approval policy, inspect failures, and compare memory enabled versus reset-memory runs with the same tasks. The sample dataset is for wiring verification only.

## Known limits and next improvements

- Agent final evidence is model-authored. For course results, use objective test cases or independent review before calling a task successful.
- Lexical memory recall is deliberately simple and can miss paraphrases. Record a before/after ablation to establish whether it helps.
- The CLI invokes model calls serially. Parallel task execution and stronger role negotiation are possible after correctness is established.
- Search parses DuckDuckGo Lite public results and filters duplicate, insecure, and weakly matching links. Service availability and ranking may change. A course-approved search API can replace this adapter.
- The current system does not create team members, a GitHub repository, a genuine semester-long history, or official dataset results.
