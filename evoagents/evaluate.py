"""Run a released JSONL task set and preserve raw per-goal evidence."""
from __future__ import annotations

import argparse
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from .core import Orchestrator, Store
from .provider import DeepSeek
from .tools import ToolBox


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate a course task set")
    parser.add_argument("dataset", type=Path, help="JSONL records: id, goal, optional expected_contains")
    parser.add_argument("--state", type=Path, default=Path(".evoagents"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("output already exists; choose a new evidence file")
    cases = [json.loads(line) for line in args.dataset.read_text(encoding="utf-8").splitlines() if line.strip()]
    if not cases or any(not isinstance(x, dict) or not isinstance(x.get("goal"), str) for x in cases):
        parser.error("dataset requires nonempty JSONL objects with goal strings")
    store = Store(args.state / "state.sqlite3")
    system = Orchestrator(DeepSeek(), store, ToolBox(args.state / "agents"), input)
    records = []
    try:
        for index, case in enumerate(cases):
            before = {a: store.db.execute("SELECT count(*) FROM memory WHERE agent=?", (a,)).fetchone()[0]
                      for a in ("researcher", "coder", "reviewer")}
            started = time.perf_counter()
            try:
                result = system.run(case["goal"], room=f"evaluation:{index}")
                error = None
            except Exception as exc:
                result = {"goal": case["goal"], "results": [], "goal_completed": False,
                          "subtask_completion_rate": 0.0, "elapsed_seconds": time.perf_counter() - started}
                error = f"{type(exc).__name__}: {exc}"
            combined = "\n".join(x["output"] for x in result["results"])
            expected = case.get("expected_contains")
            semantic = expected.lower() in combined.lower() if isinstance(expected, str) else None
            after = {a: store.db.execute("SELECT count(*) FROM memory WHERE agent=?", (a,)).fetchone()[0]
                     for a in before}
            records.append({"id": case.get("id", index), "result": result, "error": error,
                            "semantic_success": semantic, "memory_before": before, "memory_after": after})
    finally:
        store.db.close()
    graded = [r for r in records if r["semantic_success"] is not None]
    summary = {"timestamp_utc": datetime.now(timezone.utc).isoformat(), "dataset": str(args.dataset.resolve()),
               "goals": len(records), "fatal_free_rate": sum(r["result"]["goal_completed"] for r in records) / len(records),
               "semantic_completion_rate": sum(r["semantic_success"] for r in graded) / len(graded) if graded else None,
               "mean_elapsed_seconds": sum(r["result"]["elapsed_seconds"] for r in records) / len(records)}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps({"summary": summary, "records": records}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
