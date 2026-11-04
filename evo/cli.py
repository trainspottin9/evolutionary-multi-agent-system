"""Minimal text interface."""
import argparse
import getpass
import json
import os
import sys
import unittest

from .engine import Approval, Engine
from .credentials import save_key
from .evaluate import evaluate
from .llm import ChatProvider, LLMError
from .store import Memory, Store


def _provider(args):
    provider = args.provider
    base = args.base_url or os.getenv("HKGAI_BASE_URL" if provider == "hkgai" else "DEEPSEEK_BASE_URL")
    model = args.model or os.getenv("HKGAI_MODEL" if provider == "hkgai" else "DEEPSEEK_MODEL")
    return ChatProvider(provider, base_url=base, model=model)


def main(argv=None):
    parser = argparse.ArgumentParser(prog="evo", description="Evolutionary multi-agent collaboration CLI")
    parser.add_argument("--state", default=".evo", help="Local state directory")
    parser.add_argument("--provider", choices=["deepseek", "hkgai"], default="hkgai")
    parser.add_argument("--base-url", help="HTTPS endpoint for selected provider")
    parser.add_argument("--model", help="Provider model ID")
    parser.add_argument("--approve-code", action="store_true", help="Preapprove sandboxed Python execution")
    parser.add_argument("--approve-delete", action="store_true", help="Preapprove file deletion")
    parser.add_argument("--approve-push", action="store_true", help="Preapprove GitHub push")
    parser.add_argument("--no-memory", action="store_true", help="Disable memory recall, bid adjustment, and recording")
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run", help="Plan and execute a collective task")
    run.add_argument("goal")
    dm = sub.add_parser("dm", help="Human-to-agent private message")
    dm.add_argument("agent", choices=["researcher", "builder", "reviewer"])
    dm.add_argument("message")
    group = sub.add_parser("group", help="Human + multi-agent group chat")
    group.add_argument("message")
    ev = sub.add_parser("eval", help="Run a JSONL test set")
    ev.add_argument("dataset")
    ev.add_argument("--output", default="results/evaluation.json")
    metrics = sub.add_parser("metrics", help="Show recorded task metrics")
    metrics.add_argument("task_id")
    trace = sub.add_parser("trace", help="Show a task's messages and approvals")
    trace.add_argument("task_id")
    memory = sub.add_parser("memory", help="Show one agent's recorded experience")
    memory.add_argument("agent", choices=["researcher", "builder", "reviewer"])
    sub.add_parser("self-test", help="Run repository tests")
    sub.add_parser("setup-hkgai-key", help="Save HKGAI key locally without echoing it")
    web = sub.add_parser("web", help="Start the local browser interface")
    web.add_argument("--port", type=int, default=8768)
    args = parser.parse_args(argv)
    if args.command == "web":
        from .web import serve
        try:
            serve(state_dir=args.state, port=args.port, provider=args.provider,
                  base_url=args.base_url, model=args.model, memory_enabled=not args.no_memory)
        except (ValueError, LLMError, OSError) as exc:
            print("Error: %s" % exc, file=sys.stderr)
            return 1
        return 0
    if args.command == "setup-hkgai-key":
        if not sys.stdin.isatty():
            print("Run this command in an interactive terminal", file=sys.stderr)
            return 1
        key = getpass.getpass("HKGAI API key (input hidden): ")
        try:
            path = save_key("hkgai", key)
        except (ValueError, OSError) as exc:
            print("Error: %s" % exc, file=sys.stderr)
            return 1
        print("Saved private key at %s" % path)
        return 0
    if args.command == "self-test":
        suite = unittest.defaultTestLoader.discover("tests")
        return 0 if unittest.TextTestRunner(verbosity=2).run(suite).wasSuccessful() else 1
    if args.command == "metrics":
        store = Store(args.state)
        rows = store.tasks(args.task_id)
        if not rows:
            print("No such task", file=sys.stderr)
            return 1
        print(json.dumps(rows, ensure_ascii=False, indent=2))
        return 0
    if args.command == "trace":
        trace_data = Store(args.state).trace(args.task_id)
        if trace_data is None:
            print("No such task", file=sys.stderr)
            return 1
        print(json.dumps(trace_data, ensure_ascii=False, indent=2))
        return 0
    if args.command == "memory":
        agent_memory = Memory(args.state, args.agent)
        print(json.dumps({"agent": args.agent, "stats": agent_memory.stats(),
                          "recent": agent_memory.recent()}, ensure_ascii=False, indent=2))
        return 0
    allowed = set()
    if args.approve_code:
        allowed.add("run_python")
    if args.approve_delete:
        allowed.add("delete_file")
    if args.approve_push:
        allowed.add("git_push")
    approval = Approval(interactive=args.command != "eval", allowed=allowed)
    try:
        provider = _provider(args)
        if args.command == "eval":
            output = evaluate(provider, args.dataset, args.state, approval, args.output,
                              memory_enabled=not args.no_memory)
        else:
            engine = Engine(provider, state_dir=args.state, approval=approval,
                            memory_enabled=not args.no_memory)
            if args.command == "run":
                output = engine.run(args.goal)
            elif args.command == "dm":
                output = {args.agent: engine.direct_message(args.agent, args.message)}
            else:
                output = engine.group_message(args.message)
        print(json.dumps(output, ensure_ascii=False, indent=2))
        return 0
    except (ValueError, LLMError, OSError) as exc:
        print("Error: %s" % exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
