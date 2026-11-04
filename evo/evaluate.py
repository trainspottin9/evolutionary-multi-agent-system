"""Dataset runner with explicit objective checks and honest score labels."""
import json
import time
from pathlib import Path

from .engine import Engine


def _check(result, case, state_dir, started_ns=None):
    checks = []
    text = result["result"].casefold()
    for expected in case.get("expected_contains", []):
        checks.append({"check": "result contains %s" % expected,
                       "passed": expected.casefold() in text})
    def matching_files(expected):
        path = Path(expected)
        if path.is_absolute() or ".." in path.parts or any(c in str(path) for c in "*?[]"):
            raise ValueError("expected_files must be relative paths")
        return [p for p in (Path(state_dir) / "agents").glob("*/workspace/" + str(path))
                if p.is_file() and (started_ns is None or p.stat().st_mtime_ns >= started_ns)]

    for expected in case.get("expected_files", []):
        matches = matching_files(expected)
        checks.append({"check": "file exists: %s" % expected,
                       "passed": bool(matches)})
    for expected, required_texts in case.get("expected_file_contains", {}).items():
        matches = matching_files(expected)
        for required in required_texts:
            checks.append({"check": "%s contains %s" % (expected, required),
                           "passed": any(p.stat().st_size <= 200_000 and
                                         required.casefold() in p.read_text(encoding="utf-8", errors="replace").casefold()
                                         for p in matches)})
    if checks:
        checks.append({"check": "run completed", "passed": result["status"] == "success"})
        return all(c["passed"] for c in checks), "objective", checks
    return result["status"] == "success", "self_reported", []


def evaluate(provider, dataset_path, state_dir, approval, output_path, memory_enabled=True):
    cases = []
    for line_number, line in enumerate(Path(dataset_path).read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        case = json.loads(line)
        if not isinstance(case.get("id"), str) or not isinstance(case.get("prompt"), str):
            raise ValueError("Invalid case at line %d" % line_number)
        cases.append(case)
    if not cases:
        raise ValueError("Dataset is empty")
    engine = Engine(provider, state_dir=state_dir, approval=approval, memory_enabled=memory_enabled)
    results = []
    for case in cases:
        started = time.monotonic()
        started_ns = time.time_ns()
        run = engine.run(case["prompt"])
        passed, basis, checks = _check(run, case, state_dir, started_ns)
        results.append({"case_id": case["id"], "passed": passed, "basis": basis,
                        "checks": checks, "seconds": time.monotonic() - started,
                        "run": run})
    objective = [r for r in results if r["basis"] == "objective"]
    total_subtasks = sum(r["run"]["metrics"]["total_subtasks"] for r in results)
    completed_subtasks = sum(r["run"]["metrics"]["completed_subtasks"] for r in results)
    report = {"dataset": str(dataset_path), "memory_enabled": memory_enabled,
              "case_count": len(results),
              "objective_case_count": len(objective),
              "task_completion_rate": sum(r["passed"] for r in results) / len(results),
              "goal_completion_rate": sum(r["run"]["metrics"]["goal_completed"] for r in results) / len(results),
              "subtask_completion_rate": completed_subtasks / total_subtasks if total_subtasks else 0.0,
              "objective_completion_rate": (sum(r["passed"] for r in objective) / len(objective)) if objective else None,
              "total_execution_seconds": sum(r["seconds"] for r in results),
              "mean_execution_seconds": sum(r["seconds"] for r in results) / len(results),
              "cases": results}
    output = Path(output_path)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report
