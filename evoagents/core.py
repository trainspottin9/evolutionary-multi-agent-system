"""Persistent conversations, planning, routing and per-agent learning."""
from __future__ import annotations

import json
import re
import sqlite3
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Protocol


def parse_json(text: str) -> dict:
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    value = json.loads(text)
    if not isinstance(value, dict):
        raise ValueError("model output must be a JSON object")
    return value


class Model(Protocol):
    def complete(self, system: str, user: str) -> str: ...


@dataclass(frozen=True)
class Agent:
    name: str
    specialty: str


AGENTS = (
    Agent("researcher", "web research, fact gathering and citations"),
    Agent("coder", "plain-text files, Python code and tests"),
    Agent("reviewer", "verification, failure analysis and synthesis"),
)


class Store:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(path)
        self.db.row_factory = sqlite3.Row
        self.db.executescript("""
          CREATE TABLE IF NOT EXISTS messages(id TEXT PRIMARY KEY, room TEXT NOT NULL,
            sender TEXT NOT NULL, recipient TEXT, body TEXT NOT NULL, ts REAL NOT NULL);
          CREATE TABLE IF NOT EXISTS tasks(id TEXT PRIMARY KEY, parent TEXT, goal TEXT NOT NULL,
            agent TEXT NOT NULL, status TEXT NOT NULL, output TEXT NOT NULL DEFAULT '',
            started REAL NOT NULL, ended REAL);
          CREATE TABLE IF NOT EXISTS memory(id TEXT PRIMARY KEY, agent TEXT NOT NULL,
            lesson TEXT NOT NULL, outcome TEXT NOT NULL, ts REAL NOT NULL);
        """)
        self.db.commit()

    def message(self, room: str, sender: str, body: str, recipient: str | None = None) -> str:
        if recipient and room != f"dm:{recipient}":
            raise ValueError("private messages must use the recipient DM room")
        mid = uuid.uuid4().hex
        self.db.execute("INSERT INTO messages VALUES(?,?,?,?,?,?)", (mid, room, sender, recipient, body, time.time()))
        self.db.commit()
        return mid

    def messages(self, room: str) -> list[dict]:
        return [dict(x) for x in self.db.execute("SELECT * FROM messages WHERE room=? ORDER BY ts,id", (room,))]

    def begin_task(self, goal: str, agent: str, parent: str | None = None) -> str:
        tid = uuid.uuid4().hex
        self.db.execute("INSERT INTO tasks(id,parent,goal,agent,status,started) VALUES(?,?,?,?,?,?)",
                        (tid, parent, goal, agent, "running", time.time()))
        self.db.commit()
        return tid

    def finish_task(self, tid: str, status: str, output: str) -> None:
        self.db.execute("UPDATE tasks SET status=?,output=?,ended=? WHERE id=?",
                        (status, output, time.time(), tid))
        self.db.commit()

    def remember(self, agent: str, lesson: str, outcome: str) -> None:
        self.db.execute("INSERT INTO memory VALUES(?,?,?,?,?)",
                        (uuid.uuid4().hex, agent, lesson[:1000], outcome, time.time()))
        self.db.commit()

    def recall(self, agent: str, goal: str, limit: int = 4) -> list[str]:
        # Agent-specific lexical retrieval; no other agent's memory enters this query.
        words = set(re.findall(r"\w+", goal.lower()))
        rows = self.db.execute("SELECT lesson FROM memory WHERE agent=? ORDER BY ts DESC LIMIT 100", (agent,))
        scored = [(len(words & set(re.findall(r"\w+", r[0].lower()))), r[0]) for r in rows]
        return [v for score, v in sorted(scored, reverse=True) if score][:limit]

    def task_rows(self) -> list[dict]:
        return [dict(x) for x in self.db.execute("SELECT * FROM tasks ORDER BY started,id")]


class Orchestrator:
    def __init__(self, model: Model, store: Store, tools, approval):
        self.model, self.store, self.tools, self.approval = model, store, tools, approval

    def plan(self, goal: str) -> list[dict]:
        roster = [asdict(a) for a in AGENTS]
        bids = []
        for agent in AGENTS:
            bid_prompt = (f"You are {agent.name}, specialist in {agent.specialty}. "
                          "Assess whether you should take part in this goal. Return JSON only: "
                          '{"fit":0-5,"proposed_subtask":"short description or empty string"}.')
            try:
                bid = parse_json(self.model.complete(bid_prompt, goal))
                fit = int(bid.get("fit", 0))
                bids.append({"agent": agent.name, "fit": min(5, max(0, fit)),
                             "proposed_subtask": str(bid.get("proposed_subtask", ""))[:300]})
            except (ValueError, TypeError, KeyError):
                bids.append({"agent": agent.name, "fit": 0, "proposed_subtask": ""})
        prompt = ("Decompose the goal into 1-5 sequential, concrete subtasks. Negotiate roles by matching "
                  "specialties and agent bids. Return JSON only: {\"tasks\":[{\"agent\":\"researcher|coder|reviewer\","
                  "\"goal\":\"...\"}]}. A specialist may delegate later. No proprietary document formats.")
        data = parse_json(self.model.complete(prompt, json.dumps({"goal": goal, "agents": roster, "bids": bids})))
        tasks = data.get("tasks")
        if not isinstance(tasks, list) or not 1 <= len(tasks) <= 5:
            raise ValueError("invalid plan length")
        for task in tasks:
            if not isinstance(task, dict) or task.get("agent") not in {a.name for a in AGENTS} or not isinstance(task.get("goal"), str) or not task["goal"].strip():
                raise ValueError("invalid plan task")
        return tasks

    def run(self, goal: str, room: str = "group", depth: int = 0, parent: str | None = None) -> dict:
        if depth > 2:
            raise ValueError("delegation depth exceeded")
        if room.startswith("dm:"):
            raise ValueError("multi-agent runs require a group room")
        started = time.perf_counter()
        self.store.message(room, "human" if depth == 0 else "agent", goal)
        plan = self.plan(goal)
        outputs = []
        for item in plan:
            agent, subgoal = item["agent"], item["goal"]
            tid = self.store.begin_task(subgoal, agent, parent)
            self.store.message(room, "router", f"Assigned {agent}: {subgoal}")
            try:
                result = self._execute(agent, subgoal, room, tid, depth)
                self.store.finish_task(tid, "completed", result)
                self.store.remember(agent, f"For {subgoal[:200]}, successful approach: {result[:500]}", "success")
                outputs.append({"task": tid, "agent": agent, "status": "completed", "output": result})
            except Exception as exc:
                message = f"{type(exc).__name__}: {exc}"
                self.store.finish_task(tid, "failed", message)
                self.store.remember(agent, f"For {subgoal[:200]}, avoid: {message[:500]}", "failure")
                outputs.append({"task": tid, "agent": agent, "status": "failed", "output": message})
            self.store.message(room, agent, outputs[-1]["output"])
        completed = sum(x["status"] == "completed" for x in outputs)
        return {"goal": goal, "results": outputs, "subtask_completion_rate": completed / len(outputs),
                "goal_completed": completed == len(outputs), "elapsed_seconds": time.perf_counter() - started}

    def _execute(self, agent: str, goal: str, room: str, tid: str, depth: int) -> str:
        context = {"goal": goal, "memory": self.store.recall(agent, goal),
                   "group_messages": self.store.messages(room)[-8:],
                   "private_messages": self.store.messages(f"dm:{agent}")[-8:]}
        system = (f"You are {agent}. Return one JSON object only. Choose one of: "
                  '{"action":"final","text":"..."}, '
                  '{"action":"tool","name":"read|write|delete|search|python|git_commit|git_push","args":{...}}, '
                  '{"action":"ask","question":"..."}, '
                  '{"action":"delegate","goal":"..."}. '
                  "Use only .md, .txt, .py and code-support files. Provide factual results; never claim unverified execution.")
        for _ in range(8):
            decision = parse_json(self.model.complete(system, json.dumps(context, ensure_ascii=False)))
            action = decision.get("action")
            if action == "final":
                final = str(decision.get("text", "")).strip()
                if not final:
                    raise ValueError("empty final response")
                return final
            if action == "ask":
                question = str(decision.get("question", "Clarification needed"))
                self.store.message(f"dm:{agent}", agent, question, agent)
                answer = self.approval(question)
                if not answer:
                    raise PermissionError("human did not answer")
                self.store.message(f"dm:{agent}", "human", answer, agent)
                context["human_answer"] = answer
            elif action == "delegate":
                if depth >= 2:
                    raise ValueError("delegation depth exceeded")
                child = self.run(str(decision["goal"]), room, depth + 1, tid)
                context["delegated_result"] = child
            elif action == "tool":
                name = str(decision.get("name", ""))
                args = decision.get("args", {})
                if not isinstance(args, dict):
                    raise ValueError("tool args must be an object")
                result = self.tools.call(agent, name, args, self.approval)
                context["tool_result"] = result
                self.store.message(room, agent, f"tool {name}: {str(result)[:300]}")
            else:
                raise ValueError("invalid agent action")
        raise TimeoutError("agent step budget exhausted")
