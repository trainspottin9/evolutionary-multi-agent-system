"""Host-side tools with strict per-agent file roots and Docker code execution."""
from __future__ import annotations

import html
import json
import re
import shutil
import subprocess
import urllib.parse
import urllib.request
from pathlib import Path


ALLOWED_SUFFIXES = {".md", ".txt", ".py", ".json", ".toml"}


class ToolBox:
    def __init__(self, workspace: Path):
        self.workspace = workspace.resolve()
        self.workspace.mkdir(parents=True, exist_ok=True)

    def agent_root(self, agent: str) -> Path:
        if agent not in {"researcher", "coder", "reviewer"}:
            raise ValueError("unknown agent")
        root = self.workspace / agent
        root.mkdir(parents=True, exist_ok=True)
        return root

    def safe_path(self, agent: str, name: str) -> Path:
        root = self.agent_root(agent)
        if not name or Path(name).is_absolute():
            raise ValueError("path must be relative")
        target = (root / name).resolve()
        if not target.is_relative_to(root) or target.suffix.lower() not in ALLOWED_SUFFIXES:
            raise PermissionError("path escapes sandbox or has unsupported format")
        return target

    def call(self, agent: str, name: str, args: dict, approval) -> str:
        if name == "read":
            return self.safe_path(agent, str(args["path"])).read_text(encoding="utf-8")[:20000]
        if name == "write":
            target = self.safe_path(agent, str(args["path"]))
            target.parent.mkdir(parents=True, exist_ok=True)
            content = str(args["content"])
            if len(content) > 200000:
                raise ValueError("file too large")
            target.write_text(content, encoding="utf-8")
            return f"wrote {target.relative_to(self.agent_root(agent))}"
        if name == "delete":
            target = self.safe_path(agent, str(args["path"]))
            if approval(f"Delete {agent}/{args['path']}? Type yes to approve: ").strip().lower() != "yes":
                raise PermissionError("delete rejected")
            target.unlink()
            return "deleted"
        if name == "search":
            query = str(args["query"])[:200]
            url = "https://www.google.com/search?" + urllib.parse.urlencode({"q": query})
            req = urllib.request.Request(url, headers={"User-Agent": "EvoAgents/0.1 (research project)"})
            with urllib.request.urlopen(req, timeout=8) as response:
                page = response.read(150000).decode("utf-8", errors="replace")
            cleaned = re.sub(r"<script\b.*?</script>|<style\b.*?</style>", " ", page, flags=re.I | re.S)
            cleaned = re.sub(r"<[^>]+>", " ", cleaned)
            return json.dumps({"url": url, "excerpt": html.unescape(re.sub(r"\s+", " ", cleaned))[:4000]})
        if name == "python":
            script = self.safe_path(agent, str(args["path"]))
            if script.suffix != ".py" or not script.is_file():
                raise ValueError("Python script missing")
            if not shutil.which("docker"):
                raise RuntimeError("Docker is required for isolated code execution")
            cmd = ["docker", "run", "--rm", "--network", "none", "--cpus", "1", "--memory", "256m",
                   "--pids-limit", "64", "--read-only", "--security-opt", "no-new-privileges",
                   "--cap-drop", "ALL", "--user", "65534:65534", "--tmpfs", "/tmp:rw,noexec,nosuid,size=16m",
                   "-v", f"{self.agent_root(agent)}:/work:ro", "-w", "/work", "python:3.11-alpine",
                   "python", str(script.relative_to(self.agent_root(agent)))]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=20, check=False)
            return json.dumps({"exit_code": result.returncode, "stdout": result.stdout[:8000], "stderr": result.stderr[:8000]})
        if name in {"git_commit", "git_push"}:
            root = self.agent_root(agent)
            if not (root / ".git").exists():
                subprocess.run(["git", "init"], cwd=root, check=True, capture_output=True)
            if name == "git_commit":
                subprocess.run(["git", "add", "-A"], cwd=root, check=True, capture_output=True)
                result = subprocess.run(["git", "commit", "-m", str(args["message"])[:120]], cwd=root, capture_output=True, text=True, timeout=15)
                return json.dumps({"exit_code": result.returncode, "stdout": result.stdout[:1000], "stderr": result.stderr[:1000]})
            if approval(f"Push {agent} workspace to its configured Git remote? Type yes to approve: ").strip().lower() != "yes":
                raise PermissionError("push rejected")
            result = subprocess.run(["git", "push"], cwd=root, capture_output=True, text=True, timeout=30)
            return json.dumps({"exit_code": result.returncode, "stdout": result.stdout[:1000], "stderr": result.stderr[:1000]})
        raise ValueError("unknown tool")
