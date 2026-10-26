import tempfile
import unittest
from pathlib import Path

from evoagents.core import Orchestrator, Store
from evoagents.tools import ToolBox


class FixtureModel:
    """Deterministic protocol fixture; does not emulate LLM quality."""
    def complete(self, system, user):
        if "Decompose" in system:
            return '{"tasks":[{"agent":"coder","goal":"write a small note"},{"agent":"reviewer","goal":"review the note"}]}'
        if "Assess whether" in system:
            return '{"fit":3,"proposed_subtask":"help with the goal"}'
        if "You are coder" in system:
            if '"tool_result"' in user:
                return '{"action":"final","text":"note created"}'
            return '{"action":"tool","name":"write","args":{"path":"note.md","content":"hello"}}'
        return '{"action":"final","text":"review complete"}'


class SystemTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.store = Store(self.root / "state.sqlite3")
        self.tools = ToolBox(self.root / "agents")

    def tearDown(self):
        self.store.db.close()
        self.tmp.cleanup()

    def test_routing_metrics_and_learning(self):
        run = Orchestrator(FixtureModel(), self.store, self.tools, lambda _: "yes").run("create and review a note")
        self.assertTrue(run["goal_completed"])
        self.assertEqual(run["subtask_completion_rate"], 1.0)
        self.assertGreaterEqual(run["elapsed_seconds"], 0)
        self.assertEqual((self.tools.agent_root("coder") / "note.md").read_text(), "hello")
        self.assertEqual(len(self.store.task_rows()), 2)
        self.assertTrue(self.store.recall("coder", "write a note"))
        self.assertEqual(self.store.db.execute("SELECT count(*) FROM memory WHERE agent='coder'").fetchone()[0], 1)
        self.assertEqual(self.store.db.execute("SELECT count(*) FROM memory WHERE agent='researcher'").fetchone()[0], 0)

    def test_private_room_and_isolation(self):
        self.store.message("dm:coder", "human", "secret", "coder")
        self.assertEqual(len(self.store.messages("dm:coder")), 1)
        self.assertEqual(self.store.messages("dm:reviewer"), [])
        with self.assertRaises(ValueError):
            self.store.message("group", "human", "secret", "coder")
        with self.assertRaises(ValueError):
            Orchestrator(FixtureModel(), self.store, self.tools, lambda _: "yes").run("x", "dm:coder")
        for path in ("../reviewer/secret.md", "C:/Windows/test.md", "bad.pdf"):
            with self.assertRaises((ValueError, PermissionError)):
                self.tools.safe_path("coder", path)

    def test_human_approval_for_delete(self):
        self.tools.call("coder", "write", {"path": "note.txt", "content": "hello"}, lambda _: "")
        with self.assertRaises(PermissionError):
            self.tools.call("coder", "delete", {"path": "note.txt"}, lambda _: "no")
        self.assertTrue((self.tools.agent_root("coder") / "note.txt").exists())
        self.tools.call("coder", "delete", {"path": "note.txt"}, lambda _: "yes")
        self.assertFalse((self.tools.agent_root("coder") / "note.txt").exists())


if __name__ == "__main__":
    unittest.main()
