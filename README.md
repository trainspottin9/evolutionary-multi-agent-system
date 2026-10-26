# Evolutionary Multi-Agent Collaboration System

Python 3.11+ backend prototype for the HKUST final project. The live model backend is **DeepSeek**. No OpenAI or Anthropic API is used. The UI is a command line interface; generated documents are Markdown or plain text.

## Run

```powershell
python -m pip install -e .
$env:DEEPSEEK_API_KEY = "<team key>"
python -m evoagents.cli run "Research a topic, implement a Python summary script, and review it"
python -m evoagents.cli chat group
python -m evoagents.cli chat dm:coder
python -m evoagents.cli metrics
```

Agent code execution requires Docker with the `python:3.11-alpine` image available. If Docker is unavailable, the `python` tool fails closed. Each agent writes under `.evoagents/agents/<agent>/`. All state and secrets stay outside version control. Search requires outbound HTTPS.

For Git commits, configure each contributor's authentic `user.name` and `user.email` in their own Git environment. Agent private repositories can be connected to team-owned GitHub remotes; Git push requires an explicit human confirmation.

## Verify

```powershell
python -m unittest discover -v
python benchmark.py
```

The benchmark uses a deterministic protocol fixture. It is **not** an LLM evaluation or the course test set. See [architecture](ARCHITECTURE.md) and [performance report](REPORT.md).

When the course releases a task set, format it as JSONL with `{"id":"task-1","goal":"...","expected_contains":"optional rubric marker"}` per line and run:

```powershell
python -m evoagents.evaluate course_tasks.jsonl --output evidence/run-01.json
```

The evaluator preserves per-task outputs, timing and memory counts. `expected_contains` is only a simple optional check; use the course rubric to grade substantive correctness.

## Delivery status

The repository URL, team roster, real contribution history, Git screenshots and course-set metrics require team-owned evidence. See [submission checklist](SUBMISSION.md). Do not present fixture results as final evaluation scores.
