"""Local-only browser interface for the existing collaboration engine."""
import json
import secrets
import threading
import uuid
from dataclasses import dataclass, field
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote

from .engine import Approval, Engine
from .llm import ChatProvider
from .store import Memory, Store

ASSETS = Path(__file__).with_name("web_assets")
AGENTS = {"researcher", "builder", "reviewer"}


@dataclass
class Job:
    kind: str
    status: str = "running"
    result: object = None
    error: str = ""
    question: dict = None
    event: threading.Event = field(default_factory=threading.Event)
    answer: object = None

    def snapshot(self, job_id):
        return {"id": job_id, "kind": self.kind, "status": self.status,
                "result": self.result, "error": self.error, "question": self.question}


class WebApproval(Approval):
    def __init__(self, job, lock):
        super().__init__(interactive=False)
        self.job, self.lock = job, lock

    def _wait(self, kind, prompt):
        with self.lock:
            self.job.question = {"kind": kind, "prompt": prompt}
            self.job.status = "waiting"
            self.job.event.clear()
        self.job.event.wait(600)
        with self.lock:
            answer = self.job.answer
            self.job.answer = None
            self.job.question = None
            self.job.status = "running"
        return answer

    def ask(self, action, detail):
        return self._wait("approval", "%s: %s" % (action, detail)) is True

    def clarify(self, question):
        answer = self._wait("clarification", question)
        return answer.strip()[:2000] if isinstance(answer, str) and answer.strip() else None


class WebApp:
    def __init__(self, state_dir, provider="hkgai", base_url=None, model=None, memory_enabled=True):
        self.state_dir = state_dir
        self.provider = ChatProvider(provider, base_url=base_url, model=model)
        self.memory_enabled = memory_enabled
        self.store = Store(state_dir)
        self.jobs = {}
        self.lock = threading.RLock()
        self.token = secrets.token_urlsafe(32)

    def start(self, kind, value, agent=None, revision_of=None):
        job_id = uuid.uuid4().hex[:12]
        job = Job(kind)
        with self.lock:
            self.jobs[job_id] = job

        def work():
            try:
                engine = Engine(self.provider, state_dir=self.state_dir,
                                approval=WebApproval(job, self.lock),
                                memory_enabled=self.memory_enabled)
                if kind == "task":
                    result = engine.run(value)
                    if result["status"] == "success":
                        self.store.review_start(result["id"], revision_of)
                        result["review_status"] = "pending"
                    elif revision_of:
                        self.store.review_start(result["id"], revision_of, status="execution_failed")
                        self.store.review_reset_revision(revision_of)
                        result["review_status"] = "execution_failed"
                elif kind == "dm":
                    result = {agent: engine.direct_message(agent, value)}
                else:
                    result = engine.group_message(value)
                with self.lock:
                    job.result, job.status = result, "done"
            except Exception as exc:
                if revision_of:
                    try:
                        self.store.review_reset_revision(revision_of)
                    except ValueError:
                        pass
                with self.lock:
                    job.error, job.status = str(exc)[:1000], "error"
        threading.Thread(target=work, daemon=True).start()
        return job_id


def handler_class(app):
    class Handler(BaseHTTPRequestHandler):
        def _host_ok(self):
            return self.headers.get("Host") in ("127.0.0.1:%d" % self.server.server_port,
                                                "localhost:%d" % self.server.server_port)

        def _json(self, status, data):
            body = json.dumps(data, ensure_ascii=False).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _asset(self, name, content_type):
            data = (ASSETS / name).read_bytes()
            if name == "index.html":
                data = data.replace(b"__TOKEN__", app.token.encode())
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if not self._host_ok():
                return self._json(403, {"error": "Invalid host"})
            path = unquote(self.path.split("?", 1)[0])
            if path == "/":
                return self._asset("index.html", "text/html; charset=utf-8")
            if path == "/app.css":
                return self._asset("app.css", "text/css; charset=utf-8")
            if path == "/app.js":
                return self._asset("app.js", "application/javascript; charset=utf-8")
            if path == "/api/overview":
                roots = [t for t in app.store.tasks() if t["parent_id"] is None]
                return self._json(200, {"tasks": list(reversed(roots[-30:])),
                                        "reviews": app.store.reviews(),
                                        "group": app.store.history("group", limit=50, chat_only=True),
                                        "memory_enabled": app.memory_enabled})
            if path == "/api/inbox":
                with app.lock:
                    waiting = [job.snapshot(job_id) for job_id, job in app.jobs.items()
                               if job.status == "waiting"]
                return self._json(200, {"reviews": app.store.reviews("pending"),
                                        "waiting": waiting})
            if path.startswith("/api/jobs/"):
                job_id = path.rsplit("/", 1)[-1]
                with app.lock:
                    job = app.jobs.get(job_id)
                    return self._json(200, job.snapshot(job_id)) if job else self._json(404, {"error": "Job not found"})
            if path.startswith("/api/trace/"):
                task_id = path.rsplit("/", 1)[-1]
                trace = app.store.trace(task_id)
                if trace:
                    trace["review"] = app.store.review(task_id)
                    trace["review_events"] = app.store.review_events(task_id)
                return self._json(200, trace) if trace else self._json(404, {"error": "Task not found"})
            if path.startswith("/api/dm/"):
                agent = path.rsplit("/", 1)[-1]
                return self._json(200, app.store.history("dm", agent, limit=50)) if agent in AGENTS else self._json(404, {"error": "Unknown agent"})
            if path.startswith("/api/memory/"):
                agent = path.rsplit("/", 1)[-1]
                if agent in AGENTS:
                    memory = Memory(app.state_dir, agent)
                    return self._json(200, {"stats": memory.stats(), "recent": memory.recent()})
            return self._json(404, {"error": "Not found"})

        def do_POST(self):
            if not self._host_ok():
                return self._json(403, {"error": "Invalid host"})
            origin = self.headers.get("Origin")
            host = self.headers.get("Host", "")
            if (self.headers.get("X-Evo-Token") != app.token or
                    self.headers.get("Content-Type", "").split(";", 1)[0] != "application/json" or
                    (origin and origin not in ("http://" + host, "https://" + host))):
                return self._json(403, {"error": "Request rejected"})
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= 16000:
                    raise ValueError("Invalid request size")
                data = json.loads(self.rfile.read(size))
                if not isinstance(data, dict):
                    raise ValueError("Expected a JSON object")
                path = self.path.split("?", 1)[0]
                if path in ("/api/tasks", "/api/dm", "/api/group"):
                    value = data.get("text")
                    if not isinstance(value, str) or not value.strip() or len(value) > 8000:
                        raise ValueError("Enter a message of at most 8000 characters")
                    agent = data.get("agent")
                    if path == "/api/dm" and agent not in AGENTS:
                        raise ValueError("Choose a valid agent")
                    kind = {"/api/tasks": "task", "/api/dm": "dm", "/api/group": "group"}[path]
                    return self._json(202, {"job_id": app.start(kind, value.strip(), agent)})
                if path.startswith("/api/reviews/"):
                    root_id = path.rsplit("/", 1)[-1]
                    review = app.store.review_decide(root_id, data.get("decision"), data.get("feedback", ""))
                    return self._json(200, review)
                if path == "/api/revisions":
                    root_id = data.get("root_id")
                    review = app.store.review(root_id)
                    if not review or review["status"] != "changes_requested":
                        raise ValueError("Review has no requested changes")
                    roots = app.store.tasks(root_id)
                    if not roots or roots[0]["id"] != root_id or roots[0]["parent_id"] is not None:
                        raise ValueError("Original task not found")
                    app.store.review_begin_revision(root_id)
                    goal = roots[0]["description"] + "\nReviewer feedback: " + review["feedback"]
                    return self._json(202, {"job_id": app.start("task", goal, revision_of=root_id)})
                if path.startswith("/api/jobs/") and path.endswith("/answer"):
                    job_id = path.split("/")[3]
                    with app.lock:
                        job = app.jobs.get(job_id)
                        if not job or job.status != "waiting":
                            return self._json(409, {"error": "No pending question"})
                        answer = data.get("answer")
                        if job.question["kind"] == "approval" and not isinstance(answer, bool):
                            raise ValueError("Approval answer must be boolean")
                        if job.question["kind"] == "clarification" and not isinstance(answer, str):
                            raise ValueError("Clarification answer must be text")
                        job.answer = answer
                        job.event.set()
                    return self._json(200, {"ok": True})
                return self._json(404, {"error": "Not found"})
            except (ValueError, json.JSONDecodeError) as exc:
                return self._json(400, {"error": str(exc)})

        def log_message(self, format, *args):
            pass

    return Handler


def serve(state_dir=".evo", host="127.0.0.1", port=8768, provider="hkgai",
          base_url=None, model=None, memory_enabled=True):
    if host not in ("127.0.0.1", "localhost", "::1"):
        raise ValueError("Web UI must bind to localhost")
    app = WebApp(state_dir, provider, base_url, model, memory_enabled)
    server = ThreadingHTTPServer((host, port), handler_class(app))
    print("EvoCollab Web: http://%s:%d" % (host, server.server_port), flush=True)
    try:
        server.serve_forever()
    finally:
        server.server_close()
