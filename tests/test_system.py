import json
import io
import os
import tempfile
import unittest
import threading
import urllib.request
import urllib.error
import time
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

from evo.credentials import load_key, save_key
from evo.engine import Approval, Engine
from evo.evaluate import _check, evaluate
from evo.llm import ChatProvider
from evo.store import Memory, Store
from evo.tools import AgentTools, ToolError, _public_url, web_search
from evo.web import WebApp, handler_class


class ScriptedProvider:
    def __init__(self, replies):
        self.replies = list(replies)
        self.calls = []

    def complete_json(self, system, user, max_tokens=2000):
        self.calls.append((system, user))
        if not self.replies:
            raise AssertionError("Unexpected provider call")
        return self.replies.pop(0)


class SystemTests(unittest.TestCase):
    def test_review_request_changes_links_a_revision_and_prevents_double_decision(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(tmp)
            store.review_start("original")
            with self.assertRaises(ValueError):
                store.review_decide("original", "changes_requested", "")
            review = store.review_decide("original", "changes_requested", "Add sources")
            self.assertEqual(review["feedback"], "Add sources")
            with self.assertRaises(ValueError):
                store.review_decide("original", "accepted")
            store.review_begin_revision("original")
            store.review_start("revision", revision_of="original")
            self.assertEqual(store.review("original")["status"], "revising")
            self.assertEqual(store.review("revision")["revision_of"], "original")
            self.assertEqual([e["status"] for e in store.review_events("original")],
                             ["pending", "changes_requested", "revising"])
            store.review_start("failed-revision", revision_of="original", status="execution_failed")
            store.review_reset_revision("original")
            self.assertEqual(store.review("original")["status"], "changes_requested")
            self.assertEqual(store.review("failed-revision")["revision_of"], "original")

    def test_group_chat_excludes_task_bids_and_execution_log(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(tmp)
            store.message("group", "researcher", "Bid for s1: 1/5", task_id="task-1")
            store.message("group", "human", "Hello team")
            provider = ScriptedProvider([{"reply": "Research"}, {"reply": "Build"}, {"reply": "Review"}])
            Engine(provider, state_dir=tmp).group_message("How shall we work?")
            self.assertNotIn("Bid for s1", provider.calls[0][1])
            self.assertTrue(all(m["task_id"] is None for m in store.history("group", chat_only=True)))
            self.assertEqual(len(store.history("group", chat_only=True)), 5)

    def test_search_filters_irrelevant_duplicate_and_insecure_results(self):
        html = b'''<a class="result-link" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fdocs.python.org%2F3.11">Python 3.11 notes</a>
        <td class="result-snippet">Python release notes</td>
        <a class="result-link" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fdocs.python.org%2F3.11">Python 3.11 notes</a>
        <td class="result-snippet">Python release notes</td>
        <a class="result-link" href="//duckduckgo.com/l/?uddg=http%3A%2F%2Fexample.com">Python 3.11 notes</a>
        <td class="result-snippet">Python release notes</td>
        <a class="result-link" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.com">Holiday photos</a>
        <td class="result-snippet">Beach pictures</td>'''
        fake = type("Opener", (), {"open": lambda self, *a, **k: io.BytesIO(html)})()
        def safe(url):
            if not url.startswith("https://"):
                raise ToolError("Insecure")
            return url
        with patch("evo.tools.urllib.request.build_opener", return_value=fake), \
             patch("evo.tools._public_url", side_effect=safe):
            results = web_search("Python 3.11 release notes")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["url"], "https://docs.python.org/3.11")

    def test_memory_retrieval_and_bid_adjustment_are_task_specific(self):
        with tempfile.TemporaryDirectory() as tmp:
            builder = Memory(tmp, "builder")
            reviewer = Memory(tmp, "reviewer")
            builder.add("Summarize climate data in report.md", "success", "Check the source table")
            reviewer.add("Debug Python imports", "success", "Inspect the traceback")
            self.assertGreater(builder.bid_adjustment("Summarize climate data in report.md"), 0)
            self.assertEqual(reviewer.bid_adjustment("Summarize climate data in report.md"), 0)
            self.assertEqual(reviewer.recall("Summarize climate data in report.md"), [])
            builder.add("写一份代理记忆说明", "failed", "先核对已有文档")
            self.assertTrue(builder.recall("解释代理记忆如何工作"))
            provider = ScriptedProvider([
                {"subtasks": [{"id": "s1", "description": "Summarize climate data in report.md", "depends_on": []}]},
                {"score": 3}, {"score": 3}, {"score": 3},
                {"action": "final", "success": True, "result": "Done", "evidence": "Checked"},
            ])
            run = Engine(provider, state_dir=tmp, approval=Approval(interactive=False)).run("Summarize climate data")
            self.assertEqual(run["subtasks"][0]["owner"], "builder")

    def test_local_web_serves_ui_and_runs_task_without_exposing_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            replies = ScriptedProvider([
                {"subtasks": [{"id": "s1", "description": "Create hello.md", "depends_on": []}]},
                {"score": 1}, {"score": 5}, {"score": 1},
                {"action": "write_file", "path": "hello.md", "content": "Hello web"},
                {"action": "final", "success": True, "result": "Done", "evidence": "Wrote hello.md"},
                {"subtasks": [{"id": "s1", "description": "Revise hello.md", "depends_on": []}]},
                {"score": 1}, {"score": 5}, {"score": 1},
                {"action": "final", "success": True, "result": "Revised", "evidence": "Checked"},
            ])
            with patch("evo.web.ChatProvider", return_value=replies):
                app = WebApp(tmp)
            server = ThreadingHTTPServer(("127.0.0.1", 0), handler_class(app))
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            base = "http://127.0.0.1:%d" % server.server_port
            try:
                html = urllib.request.urlopen(base + "/").read().decode()
                self.assertIn("EvoCollab", html)
                self.assertIn(app.token, html)
                payload = json.dumps({"text": "Create hello.md"}).encode()
                request = urllib.request.Request(base + "/api/tasks", data=payload,
                                                 headers={"Content-Type": "application/json"}, method="POST")
                with self.assertRaises(urllib.error.HTTPError) as denied:
                    urllib.request.urlopen(request)
                self.assertEqual(denied.exception.code, 403)
                request.add_header("X-Evo-Token", app.token)
                job_id = json.load(urllib.request.urlopen(request))["job_id"]
                for _ in range(100):
                    result = json.load(urllib.request.urlopen(base + "/api/jobs/" + job_id))
                    if result["status"] == "done":
                        break
                    time.sleep(0.01)
                self.assertEqual(result["status"], "done")
                self.assertEqual(result["result"]["status"], "success")
                self.assertTrue((Path(tmp) / "agents/builder/workspace/hello.md").exists())
                root_id = result["result"]["id"]
                trace = json.load(urllib.request.urlopen(base + "/api/trace/" + root_id))
                self.assertEqual(trace["review"]["status"], "pending")
                inbox = json.load(urllib.request.urlopen(base + "/api/inbox"))
                self.assertEqual(inbox["reviews"][0]["root_id"], root_id)
                decision = urllib.request.Request(base + "/api/reviews/" + root_id,
                    data=json.dumps({"decision": "changes_requested", "feedback": "Add an example"}).encode(),
                    headers={"Content-Type": "application/json", "X-Evo-Token": app.token}, method="POST")
                self.assertEqual(json.load(urllib.request.urlopen(decision))["status"], "changes_requested")
                revision = urllib.request.Request(base + "/api/revisions",
                    data=json.dumps({"root_id": root_id}).encode(),
                    headers={"Content-Type": "application/json", "X-Evo-Token": app.token}, method="POST")
                new_job = json.load(urllib.request.urlopen(revision))["job_id"]
                for _ in range(100):
                    revised = json.load(urllib.request.urlopen(base + "/api/jobs/" + new_job))
                    if revised["status"] == "done":
                        break
                    time.sleep(0.01)
                self.assertEqual(revised["result"]["status"], "success")
                new_root = revised["result"]["id"]
                self.assertEqual(app.store.review(new_root)["revision_of"], root_id)
                self.assertEqual(app.store.review(root_id)["status"], "revising")
                accept = urllib.request.Request(base + "/api/reviews/" + new_root,
                    data=json.dumps({"decision": "accepted"}).encode(),
                    headers={"Content-Type": "application/json", "X-Evo-Token": app.token}, method="POST")
                self.assertEqual(json.load(urllib.request.urlopen(accept))["status"], "accepted")
                self.assertEqual(json.load(urllib.request.urlopen(base + "/api/inbox"))["reviews"], [])
            finally:
                server.shutdown()
                server.server_close()
    def test_end_to_end_plan_bidding_file_memory_and_metrics(self):
        with tempfile.TemporaryDirectory() as tmp:
            provider = ScriptedProvider([
                {"question": None, "subtasks": [{"id": "s1", "description": "Create hello.md",
                                                  "skills": ["writing"], "depends_on": []}]},
                {"score": 1, "reason": "Can research"},
                {"score": 5, "reason": "Can create the file"},
                {"score": 2, "reason": "Can review"},
                {"action": "write_file", "path": "hello.md", "content": "Hello agents"},
                {"action": "final", "success": True, "result": "Created hello.md",
                 "evidence": "write_file returned Wrote hello.md", "lesson": "Write the artifact before concluding."},
            ])
            engine = Engine(provider, state_dir=tmp, approval=Approval(interactive=False))
            run = engine.run("Create a note")
            self.assertEqual(run["status"], "success")
            self.assertEqual(run["subtasks"][0]["owner"], "builder")
            self.assertTrue((Path(tmp) / "agents/builder/workspace/hello.md").is_file())
            self.assertEqual(run["metrics"]["task_completion_rate"], 1.0)
            self.assertTrue(run["metrics"]["goal_completed"])
            self.assertEqual(Memory(tmp, "builder").stats()["success"], 1)
            self.assertEqual(Memory(tmp, "builder").recent()[0]["lesson"],
                             "Write the artifact before concluding.")
            self.assertTrue(Store(tmp).trace(run["id"])["messages"])
            passed, basis, checks = _check(run, {"expected_files": ["hello.md"]}, tmp)
            self.assertTrue(passed)
            self.assertEqual(basis, "objective")
            self.assertTrue(checks[0]["passed"])
            passed, _, checks = _check(run, {"expected_file_contains": {"hello.md": ["Hello agents"]}}, tmp)
            self.assertTrue(passed)
            self.assertTrue(checks[0]["passed"])
            passed, _, _ = _check(run, {"expected_file_contains": {"hello.md": ["missing phrase"]}}, tmp)
            self.assertFalse(passed)
            self.assertEqual(provider.replies, [])

    def test_agent_to_agent_delegation_is_recorded(self):
        with tempfile.TemporaryDirectory() as tmp:
            provider = ScriptedProvider([
                {"subtasks": [{"id": "s1", "description": "Review code", "depends_on": []}]},
                {"score": 0}, {"score": 1}, {"score": 5},
                {"action": "delegate", "agent": "builder", "description": "Check implementation"},
                {"action": "final", "success": True, "result": "Implementation checked",
                 "evidence": "Reviewed generated code", "lesson": "Check first"},
                {"action": "final", "success": True, "result": "Review done",
                 "evidence": "Builder reported check", "lesson": "Delegation helped"},
            ])
            engine = Engine(provider, state_dir=tmp, approval=Approval(interactive=False))
            run = engine.run("Review code")
            self.assertEqual(run["status"], "success")
            self.assertEqual(run["metrics"]["total_subtasks"], 2)
            self.assertEqual(Memory(tmp, "builder").stats()["success"], 1)
            self.assertTrue(any(m["recipient"] == "builder" for m in Store(tmp).history("agent")))

    def test_private_paths_block_escape_and_protected_git(self):
        with tempfile.TemporaryDirectory() as tmp:
            tools = AgentTools(Path(tmp) / "agent")
            outside = Path(tmp) / "secret.txt"
            outside.write_text("private")
            (tools.root / "link.txt").symlink_to(outside)
            (tools.root / ".git").mkdir()
            (tools.root / "git_alias").symlink_to(tools.root / ".git", target_is_directory=True)
            for name in ("../secret.txt", "link.txt", ".git/config", "/tmp/x.txt", "payload.exe"):
                with self.subTest(name=name), self.assertRaises(ToolError):
                    tools.read_file(name) if name == "link.txt" else tools.write_file(name, "x")
            with self.assertRaises(ToolError):
                tools.write_file("git_alias/config.py", "x")
            tools.write_file("safe/notes.md", "ok")
            self.assertEqual(tools.read_file("safe/notes.md"), "ok")

    def test_private_network_targets_are_rejected(self):
        for url in ("http://example.com", "https://localhost/", "https://127.0.0.1/",
                    "https://example.local/", "https://user:pass@example.com/"):
            with self.subTest(url=url), self.assertRaises(ToolError):
                _public_url(url)

    def test_explicit_artifact_exchange_preserves_private_workspaces(self):
        with tempfile.TemporaryDirectory() as tmp:
            exchange = Path(tmp) / "exchange"
            builder = AgentTools(Path(tmp) / "builder", exchange_root=exchange)
            reviewer = AgentTools(Path(tmp) / "reviewer", exchange_root=exchange)
            builder.write_file("draft.md", "Draft for review")
            with self.assertRaises(ToolError):
                reviewer.read_file("draft.md")
            artifact = builder.publish_file("draft.md")["artifact_id"]
            self.assertIn(artifact, reviewer.list_artifacts())
            reviewer.import_file(artifact, "received.md")
            self.assertEqual(reviewer.read_file("received.md"), "Draft for review")
            self.assertFalse((reviewer.root / "draft.md").exists())

    def test_eval_does_not_count_stale_file_from_prior_case(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "agents/builder/workspace/hello.md"
            path.parent.mkdir(parents=True)
            path.write_text("old")
            run = {"result": "done", "status": "success"}
            passed, basis, _ = _check(run, {"expected_files": ["hello.md"]}, tmp,
                                      started_ns=path.stat().st_mtime_ns + 1)
            self.assertFalse(passed)
            self.assertEqual(basis, "objective")

    def test_objective_file_does_not_pass_when_run_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "agents/builder/workspace/hello.md"
            path.parent.mkdir(parents=True)
            path.write_text("memory helps repeated tasks")
            passed, basis, checks = _check(
                {"result": "Step limit reached", "status": "failed"},
                {"expected_files": ["hello.md"],
                 "expected_file_contains": {"hello.md": ["memory"]}}, tmp)
            self.assertFalse(passed)
            self.assertEqual(basis, "objective")
            self.assertFalse(checks[-1]["passed"])

    def test_repeated_denied_tool_stops_early(self):
        with tempfile.TemporaryDirectory() as tmp:
            provider = ScriptedProvider([
                {"subtasks": [{"id": "s1", "description": "Check hello.md", "depends_on": []}]},
                {"score": 0}, {"score": 5}, {"score": 0},
                {"action": "tool", "name": "run_python", "args": {"script": "check.py"}},
                {"action": "tool", "name": "run_python", "args": {"script": "check.py"}},
            ])
            run = Engine(provider, state_dir=tmp, approval=Approval(interactive=False)).run("Check hello.md")
            self.assertEqual(run["status"], "blocked")
            self.assertIn("Repeated denied", run["result"])
            self.assertEqual(provider.replies, [])

    def test_critical_tool_needs_approval(self):
        with tempfile.TemporaryDirectory() as tmp:
            provider = ScriptedProvider([
                {"subtasks": [{"id": "s1", "description": "Execute Python", "depends_on": []}]},
                {"score": 0}, {"score": 5}, {"score": 0},
                {"action": "tool", "name": "run_python", "args": {"script": "x.py"}},
                {"action": "final", "success": False, "result": "Approval unavailable", "lesson": "Ask first"},
            ])
            engine = Engine(provider, state_dir=tmp, approval=Approval(interactive=False))
            run = engine.run("Execute Python")
            self.assertEqual(run["status"], "failed")
            import sqlite3
            with sqlite3.connect(str(Path(tmp) / "events.sqlite3")) as db:
                self.assertEqual(db.execute("SELECT decision FROM approvals").fetchone()[0], "denied")

    def test_evaluation_report_uses_objective_checks(self):
        with tempfile.TemporaryDirectory() as tmp:
            dataset = Path(tmp) / "cases.jsonl"
            dataset.write_text(json.dumps({"id": "case-a", "prompt": "Create hello.md",
                                           "expected_files": ["hello.md"]}) + "\n")
            provider = ScriptedProvider([
                {"subtasks": [{"id": "s1", "description": "Create hello.md", "depends_on": []}]},
                {"score": 1}, {"score": 5}, {"score": 1},
                {"action": "write_file", "arguments": {"path": "hello.md", "content": "ok"}},
                {"action": "final", "success": True, "result": "Created hello.md",
                 "evidence": "Wrote hello.md", "lesson": "Write before reporting"},
            ])
            output = Path(tmp) / "report.json"
            report = evaluate(provider, dataset, Path(tmp) / "state", Approval(interactive=False), output)
            self.assertEqual(report["task_completion_rate"], 1.0)
            self.assertTrue(report["memory_enabled"])
            self.assertEqual(report["objective_completion_rate"], 1.0)
            self.assertEqual(report["subtask_completion_rate"], 1.0)
            self.assertEqual(report["cases"][0]["basis"], "objective")
            self.assertTrue(output.is_file())

    def test_no_memory_mode_excludes_prior_experience_and_does_not_record(self):
        with tempfile.TemporaryDirectory() as tmp:
            Memory(tmp, "builder").add("Create hello.md", "success", "Prior lesson")
            provider = ScriptedProvider([
                {"subtasks": [{"id": "s1", "description": "Create hello.md", "depends_on": []}]},
                {"score": 1}, {"score": 5}, {"score": 1},
                {"action": "final", "success": True, "result": "Done", "evidence": "Checked",
                 "lesson": "New lesson"},
            ])
            run = Engine(provider, state_dir=tmp, approval=Approval(interactive=False),
                         memory_enabled=False).run("Create hello.md")
            self.assertEqual(run["status"], "success")
            for _, user in provider.calls[1:4]:
                self.assertEqual(json.loads(user)["relevant_experience"], [])
            self.assertEqual(json.loads(provider.calls[4][1])["memory"], [])
            self.assertEqual(Memory(tmp, "builder").stats()["success"], 1)

    def test_local_hkgai_key_and_course_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "private" / "hkgai.key"
            save_key("hkgai", "test-placeholder", path)
            self.assertEqual(path.stat().st_mode & 0o777, 0o600)
            with patch.dict(os.environ, {"HKGAI_API_KEY": "", "HKGAI_API_KEY_FILE": str(path)}):
                self.assertEqual(load_key("hkgai"), "test-placeholder")
                provider = ChatProvider("hkgai")
                self.assertEqual(provider.base_url, "https://api1.hkgai.net/v1")
                self.assertEqual(provider.model, "t2_hkgai-v3_fp8_1m_e7")
            other = Path(tmp) / "other.key"
            other.write_text("unsafe")
            other.chmod(0o644)
            with self.assertRaises(ValueError):
                load_key("hkgai", other)

    def test_hkgai_chat_request_uses_v1_bearer_and_json(self):
        observed = {}

        def fake_urlopen(request, timeout):
            observed["url"] = request.full_url
            observed["auth"] = request.get_header("Authorization")
            observed["payload"] = json.loads(request.data)
            return io.BytesIO(json.dumps({"choices": [{"finish_reason": "stop",
                                                      "message": {"content": '{"reply":"ok"}'}}]}).encode())

        with patch.dict(os.environ, {"HKGAI_API_KEY": "test-placeholder"}):
            with patch("urllib.request.urlopen", side_effect=fake_urlopen):
                response = ChatProvider("hkgai").complete_json("Return JSON", "hello")
        self.assertEqual(response, {"reply": "ok"})
        self.assertEqual(observed["url"], "https://api1.hkgai.net/v1/chat/completions")
        self.assertEqual(observed["auth"], "Bearer test-placeholder")
        self.assertEqual(observed["payload"]["model"], "t2_hkgai-v3_fp8_1m_e7")


if __name__ == "__main__":
    unittest.main()
