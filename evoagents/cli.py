"""Minimal CLI for live work, conversation inspection and metrics."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from .core import Orchestrator, Store
from .provider import DeepSeek
from .tools import ToolBox


def main() -> None:
    parser = argparse.ArgumentParser(prog="evoagents")
    parser.add_argument("--state", type=Path, default=Path(".evoagents"))
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run")
    run.add_argument("goal")
    run.add_argument("--room", default="group")
    chat = sub.add_parser("chat")
    chat.add_argument("room")
    metrics = sub.add_parser("metrics")
    args = parser.parse_args()
    store = Store(args.state / "state.sqlite3")
    if args.command == "chat":
        if args.room != "group" and args.room not in {"dm:researcher", "dm:coder", "dm:reviewer"}:
            parser.error("unknown room")
        print(json.dumps(store.messages(args.room), ensure_ascii=False, indent=2))
    elif args.command == "metrics":
        rows = store.task_rows()
        finished = [r for r in rows if r["status"] != "running"]
        complete = sum(r["status"] == "completed" for r in finished)
        print(json.dumps({"completed": complete, "total": len(finished),
                          "completion_rate": complete / len(finished) if finished else None,
                          "execution_seconds": [round(r["ended"] - r["started"], 3) for r in finished]}, indent=2))
    else:
        orchestration = Orchestrator(DeepSeek(), store, ToolBox(args.state / "agents"), input)
        print(json.dumps(orchestration.run(args.goal, args.room), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
