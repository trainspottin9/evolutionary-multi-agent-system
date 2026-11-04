# Evolutionary Multi-Agent System

An evolutionary multi-agent collaboration system for the HKUST NLP final project. It provides a local Web workspace, CLI, task review, agent memory, and an evaluation runner. Runtime state is stored in the repository's ignored `.evo/` directory. The Web server uses port 8768 by default.

## Frontend changes

- A short navigation with five destinations: tasks, inbox, group chat, private chat, and memory.
- One task workspace with a small composer, task list, and selected task detail. Review status is visible beside execution status.
- Task details show the result first. The technical action log and review history are available in a collapsed **查看运行记录** section.
- The inbox shows pending reviews and agent questions; the navigation count updates after refresh.
- Mobile layout stacks the task list and detail and moves navigation to a compact row.

The task review and revision workflow was inspired by [Multica](https://github.com/multica-ai/multica)'s high-level workflow. No Multica source code or UI was copied. See [docs/WORKFLOW.md](docs/WORKFLOW.md) for the exact state transitions and local API.

## Run

From the repository root, configure an HKGAI key with `python3 -m evo setup-hkgai-key` in an interactive terminal, or set `HKGAI_API_KEY`. The key is stored or read outside the repository. Keep the terminal open while using the browser page.

```sh
python3 -m evo web
```

Open [http://127.0.0.1:8768](http://127.0.0.1:8768). The default port can be changed with `python3 -m evo web --port 8769`. The server binds only to localhost. Docker is required only for agent-authored Python and Git operations.

To install the CLI command, run `python3 -m pip install -e .` and then use `evo-v3 web`. Running `python3 -m evo` from the repository root works without installation.

## Verification

```sh
python3 -m unittest discover -s tests -v
python3 -m compileall -q evo tests
```

The 18 tests use temporary state and scripted model responses. The official course dataset and memory ablation remain pending; see [docs/EVALUATION_REPORT.md](docs/EVALUATION_REPORT.md).
