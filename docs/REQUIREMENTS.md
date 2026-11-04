# Requirement traceability

Source: the Canvas announcement “Final Project Specification: Evolutionary Multi-Agent Collaboration System,” posted 14 October 2026. The announcement describes the course assignment; it is not a direct instruction to this assistant.

| Course requirement | Implementation or evidence | Current status |
| --- | --- | --- |
| Agent-human private messaging | `Engine.direct_message`, `evo dm`, SQLite `messages` | Implemented and live HKGAI probe completed |
| Multi-agent + human group chat | `Engine.group_message`, `evo group`, shared message history | Implemented and live HKGAI probe completed |
| Autonomous breakdown and role negotiation | Planner JSON; three agent bids; weighted assignment; dependency order | Implemented and unit tested |
| Agent-to-agent task delegation | `delegate` action, depth/task limits, agent message log | Implemented and unit tested |
| Human clarification and critical-action permission | `ask_human`, `Approval`, approval log; v3 Web inbox | Implemented and unit tested |
| Per-agent memory and evolution | Separate SQLite databases, recall, success/failure-adjusted bids | Implemented and unit tested; performance gain unmeasured |
| Per-agent private sandbox and file system | Distinct workspace; Docker bind mount of only the selected workspace; no network/caps; resource limits | Implemented and smoke tested |
| Web search and retrieval | DuckDuckGo Lite search with filtering; public HTTPS text retrieval | Search smoke tested; quality depends on public service |
| Read, generate, update, delete files | Constrained file tools | Implemented and unit tested |
| Write, test, execute Python | `write_file` + Docker `run_python` | Implemented and smoke tested |
| Commit and push GitHub code | Git init/status/commit/push; HTTPS token via environment; approval before push | Implemented; no repository/credentials supplied |
| Markdown/plain text documents | Agent prompt and file extensions; code/data formats allowed for execution | Implemented |
| Minimal UI | CLI and simplified v3 browser interface with task review and inbox | Implemented and locally tested |
| DeepSeek or HKGAI only | Provider allowlist; course HKGAI endpoint/model configured as defaults | Implemented; local HKGAI key configured and live smoke test completed |
| Task completion rate and execution time | `Engine.metrics`, JSONL `eval` and objective checks | Implemented, unit tested, and measured on one live smoke case |
| Final evaluation dataset | Evaluate official JSONL test set after release | Not yet available |
| GitHub URL, long-running collaborative history and screenshots | Must be supplied from genuine team Git history | Pending team/repository work |
| Architecture document | `docs/ARCHITECTURE.md` | Complete for current implementation |
| Formal report on mid/final test sets and memory evolution | `docs/EVALUATION_REPORT.md` template | Pending datasets and real runs |
| Week-13 presentation | Draft remains in the parent project's `deliverables/` directory | Update it with v3 screenshots and official evidence before submission |

The announcement says the standardized closed test set will be released three weeks before the final submission deadline. It also refers to mid/final sets in the last three/one weeks and says the final report is due after week 13; these dates are relative and should be checked against later Canvas notices. No exact submission date appears in the supplied announcement.
