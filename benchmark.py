"""Offline protocol benchmark. Replace fixture with released course tasks for final metrics."""
import json
import statistics
import tempfile
from pathlib import Path

from evoagents.core import Orchestrator, Store
from evoagents.tools import ToolBox
from tests.test_system import FixtureModel


def main():
    with tempfile.TemporaryDirectory() as folder:
        root = Path(folder)
        store = Store(root / "state.sqlite3")
        system = Orchestrator(FixtureModel(), store, ToolBox(root / "agents"), lambda _: "yes")
        runs = [system.run("create and review a note") for _ in range(5)]
        times = [r["elapsed_seconds"] for r in runs]
        report = {"dataset": "local deterministic protocol fixture (not course test set)",
                  "goals_completed": sum(r["goal_completed"] for r in runs), "goals_total": len(runs),
                  "goal_completion_rate": sum(r["goal_completed"] for r in runs) / len(runs),
                  "subtask_completion_rate": sum(sum(x["status"] == "completed" for x in r["results"]) for r in runs) /
                                             sum(len(r["results"]) for r in runs),
                  "mean_execution_seconds": statistics.mean(times),
                  "median_execution_seconds": statistics.median(times),
                  "individual_execution_seconds": times,
                  "memory_entries": {a: store.db.execute("SELECT count(*) FROM memory WHERE agent=?", (a,)).fetchone()[0]
                                     for a in ("researcher", "coder", "reviewer")}}
        print(json.dumps(report, indent=2))
        store.db.close()


if __name__ == "__main__":
    main()
