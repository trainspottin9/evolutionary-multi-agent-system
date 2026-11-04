"""SQLite event log and physically separate per-agent memory databases."""
import json
import math
import re
import sqlite3
import time
import uuid
from pathlib import Path


_STOP = {"a", "an", "the", "to", "for", "and", "or", "of", "in", "on", "with",
         "is", "are", "be", "this", "that", "task", "agent", "file", "write",
         "create", "make", "please", "using", "use"}


def _terms(value):
    """Small bilingual lexical index without an external model or network service."""
    terms = set()
    for part in re.findall(r"[a-z0-9]+|[\u3400-\u9fff]+", value.casefold()):
        if re.fullmatch(r"[\u3400-\u9fff]+", part):
            terms.update(part[i:i + 2] for i in range(len(part) - 1))
            if len(part) == 1:
                terms.add(part)
        elif len(part) > 1 and part not in _STOP:
            terms.add(part)
    return terms


def _similarity(left, right):
    a, b = _terms(left), _terms(right)
    return len(a & b) / math.sqrt(len(a) * len(b)) if a and b else 0.0


def _connect(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(str(path))
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    return db


class Store:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.db_path = self.root / "events.sqlite3"
        with _connect(self.db_path) as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS messages (
                  id TEXT PRIMARY KEY, ts REAL NOT NULL, channel TEXT NOT NULL,
                  sender TEXT NOT NULL, recipient TEXT, content TEXT NOT NULL,
                  task_id TEXT);
                CREATE TABLE IF NOT EXISTS tasks (
                  id TEXT PRIMARY KEY, parent_id TEXT, owner TEXT, description TEXT NOT NULL,
                  status TEXT NOT NULL, started REAL, ended REAL, result TEXT, error TEXT);
                CREATE TABLE IF NOT EXISTS approvals (
                  id TEXT PRIMARY KEY, ts REAL NOT NULL, agent TEXT NOT NULL,
                  action TEXT NOT NULL, decision TEXT NOT NULL, task_id TEXT);
                CREATE TABLE IF NOT EXISTS actions (
                  id TEXT PRIMARY KEY, ts REAL NOT NULL, task_id TEXT NOT NULL,
                  agent TEXT NOT NULL, payload TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS reviews (
                  root_id TEXT PRIMARY KEY, status TEXT NOT NULL,
                  feedback TEXT NOT NULL DEFAULT '', revision_of TEXT,
                  created REAL NOT NULL, updated REAL NOT NULL);
                CREATE TABLE IF NOT EXISTS review_events (
                  id TEXT PRIMARY KEY, root_id TEXT NOT NULL, ts REAL NOT NULL,
                  status TEXT NOT NULL, feedback TEXT NOT NULL);
            """)

    def message(self, channel, sender, content, recipient=None, task_id=None):
        mid = uuid.uuid4().hex
        with _connect(self.db_path) as db:
            db.execute("INSERT INTO messages VALUES (?,?,?,?,?,?,?)",
                       (mid, time.time(), channel, sender, recipient, content, task_id))
        return mid

    def history(self, channel, recipient=None, limit=20, chat_only=False):
        with _connect(self.db_path) as db:
            if channel == "dm":
                rows = db.execute("""SELECT * FROM messages WHERE channel='dm' AND
                    ((sender='human' AND recipient=?) OR (sender=? AND recipient='human'))
                    ORDER BY ts DESC LIMIT ?""", (recipient, recipient, limit)).fetchall()
            else:
                condition = " AND task_id IS NULL" if chat_only else ""
                rows = db.execute("SELECT * FROM messages WHERE channel=?" + condition +
                                  " ORDER BY ts DESC LIMIT ?", (channel, limit)).fetchall()
        return [dict(r) for r in reversed(rows)]

    def task_start(self, task_id, description, owner, parent_id=None):
        with _connect(self.db_path) as db:
            db.execute("INSERT INTO tasks VALUES (?,?,?,?,?,?,?,?,?)",
                       (task_id, parent_id, owner, description, "running", time.time(), None, None, None))

    def task_end(self, task_id, status, result="", error=""):
        with _connect(self.db_path) as db:
            db.execute("UPDATE tasks SET status=?,ended=?,result=?,error=? WHERE id=?",
                       (status, time.time(), result, error, task_id))

    def tasks(self, root_id=None):
        with _connect(self.db_path) as db:
            if root_id:
                rows = db.execute("""WITH RECURSIVE descendants(id) AS (
                    SELECT id FROM tasks WHERE id=?
                    UNION ALL SELECT t.id FROM tasks t JOIN descendants d ON t.parent_id=d.id)
                    SELECT * FROM tasks WHERE id IN descendants ORDER BY started""",
                                  (root_id,)).fetchall()
            else:
                rows = db.execute("SELECT * FROM tasks ORDER BY started").fetchall()
        return [dict(r) for r in rows]

    def approval(self, agent, action, decision, task_id):
        with _connect(self.db_path) as db:
            db.execute("INSERT INTO approvals VALUES (?,?,?,?,?,?)",
                       (uuid.uuid4().hex, time.time(), agent, action, decision, task_id))

    def action(self, task_id, agent, payload):
        with _connect(self.db_path) as db:
            db.execute("INSERT INTO actions VALUES (?,?,?,?,?)",
                       (uuid.uuid4().hex, time.time(), task_id, agent,
                        json.dumps(payload, ensure_ascii=False)[:4000]))

    def review_start(self, root_id, revision_of=None, status="pending"):
        if status not in ("pending", "execution_failed"):
            raise ValueError("Invalid review status")
        now = time.time()
        with _connect(self.db_path) as db:
            db.execute("INSERT INTO reviews VALUES (?,?,?,?,?,?)",
                       (root_id, status, "", revision_of, now, now))
            db.execute("INSERT INTO review_events VALUES (?,?,?,?,?)",
                       (uuid.uuid4().hex, root_id, now, status, ""))

    def review(self, root_id):
        with _connect(self.db_path) as db:
            row = db.execute("SELECT * FROM reviews WHERE root_id=?", (root_id,)).fetchone()
        return dict(row) if row else None

    def reviews(self, status=None):
        with _connect(self.db_path) as db:
            if status:
                rows = db.execute("SELECT * FROM reviews WHERE status=? ORDER BY created DESC",
                                  (status,)).fetchall()
            else:
                rows = db.execute("SELECT * FROM reviews ORDER BY created DESC").fetchall()
        return [dict(row) for row in rows]

    def review_decide(self, root_id, decision, feedback=""):
        if decision not in ("accepted", "changes_requested"):
            raise ValueError("Invalid review decision")
        if not isinstance(feedback, str) or len(feedback) > 2000:
            raise ValueError("Invalid review feedback")
        if decision == "changes_requested" and not feedback.strip():
            raise ValueError("Revision feedback is required")
        with _connect(self.db_path) as db:
            row = db.execute("UPDATE reviews SET status=?,feedback=?,updated=? "
                             "WHERE root_id=? AND status='pending'",
                             (decision, feedback.strip(), time.time(), root_id))
            if row.rowcount != 1:
                raise ValueError("No pending review for this task")
            db.execute("INSERT INTO review_events VALUES (?,?,?,?,?)",
                       (uuid.uuid4().hex, root_id, time.time(), decision, feedback.strip()))
        return self.review(root_id)

    def review_begin_revision(self, root_id):
        with _connect(self.db_path) as db:
            row = db.execute("UPDATE reviews SET status='revising',updated=? "
                             "WHERE root_id=? AND status='changes_requested'",
                             (time.time(), root_id))
            if row.rowcount != 1:
                raise ValueError("This task is not ready for revision")
            db.execute("INSERT INTO review_events VALUES (?,?,?,?,?)",
                       (uuid.uuid4().hex, root_id, time.time(), "revising", ""))
        return self.review(root_id)

    def review_reset_revision(self, root_id):
        with _connect(self.db_path) as db:
            row = db.execute("UPDATE reviews SET status='changes_requested',updated=? "
                             "WHERE root_id=? AND status='revising'", (time.time(), root_id))
            if row.rowcount != 1:
                raise ValueError("This review is not being revised")
            db.execute("INSERT INTO review_events VALUES (?,?,?,?,?)",
                       (uuid.uuid4().hex, root_id, time.time(), "changes_requested", "Revision run failed"))
        return self.review(root_id)

    def review_events(self, root_id):
        with _connect(self.db_path) as db:
            rows = db.execute("SELECT * FROM review_events WHERE root_id=? ORDER BY ts",
                              (root_id,)).fetchall()
        return [dict(row) for row in rows]

    def trace(self, root_id):
        task_ids = [r["id"] for r in self.tasks(root_id)]
        if not task_ids:
            return None
        placeholders = ",".join("?" for _ in task_ids)
        with _connect(self.db_path) as db:
            messages = [dict(r) for r in db.execute(
                "SELECT * FROM messages WHERE task_id IN (%s) ORDER BY ts" % placeholders, task_ids)]
            approvals = [dict(r) for r in db.execute(
                "SELECT * FROM approvals WHERE task_id IN (%s) ORDER BY ts" % placeholders, task_ids)]
            actions = [dict(r) for r in db.execute(
                "SELECT * FROM actions WHERE task_id IN (%s) ORDER BY ts" % placeholders, task_ids)]
        return {"tasks": self.tasks(root_id), "messages": messages,
                "approvals": approvals, "actions": actions}


class Memory:
    def __init__(self, root, agent):
        if not re.fullmatch(r"[a-z][a-z0-9_-]*", agent):
            raise ValueError("Invalid agent name")
        self.path = Path(root).resolve() / "agents" / agent / "memory.sqlite3"
        with _connect(self.path) as db:
            db.execute("""CREATE TABLE IF NOT EXISTS experiences (
                id TEXT PRIMARY KEY, ts REAL NOT NULL, task TEXT NOT NULL,
                outcome TEXT NOT NULL, lesson TEXT NOT NULL)""")

    def add(self, task, outcome, lesson):
        with _connect(self.path) as db:
            db.execute("INSERT INTO experiences VALUES (?,?,?,?,?)",
                       (uuid.uuid4().hex, time.time(), task[:2000], outcome, lesson[:2000]))

    def recall(self, task, limit=3):
        with _connect(self.path) as db:
            rows = db.execute("SELECT * FROM experiences ORDER BY ts DESC LIMIT 200").fetchall()
        ranked = []
        seen = set()
        for row in rows:
            similarity = _similarity(task, row["task"])
            signature = (row["task"].casefold(), row["outcome"], row["lesson"].casefold())
            if similarity < 0.18 or signature in seen or not row["lesson"].strip():
                continue
            seen.add(signature)
            item = dict(row)
            item["similarity"] = round(similarity, 3)
            ranked.append(item)
        ranked.sort(key=lambda r: (r["similarity"], r["ts"]), reverse=True)
        return ranked[:limit]

    def bid_adjustment(self, task):
        relevant = self.recall(task, limit=5)
        evidence = [(r["similarity"], 1 if r["outcome"] == "success" else -1)
                    for r in relevant if r["outcome"] in ("success", "failed")]
        if not evidence:
            return 0.0
        balance = sum(weight * sign for weight, sign in evidence) / sum(weight for weight, _ in evidence)
        return round(0.9 * len(evidence) / (len(evidence) + 2) * balance, 3)

    def stats(self):
        with _connect(self.path) as db:
            return {r["outcome"]: r["n"] for r in db.execute(
                "SELECT outcome,COUNT(*) n FROM experiences GROUP BY outcome")}

    def recent(self, limit=20):
        with _connect(self.path) as db:
            return [dict(r) for r in db.execute(
                "SELECT * FROM experiences ORDER BY ts DESC LIMIT ?", (limit,))]
