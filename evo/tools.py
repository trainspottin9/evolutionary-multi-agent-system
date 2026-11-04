"""Bounded tools. Only run_python executes agent-authored code, inside Docker."""
import base64
import html
import ipaddress
import json
import os
import re
import shutil
import socket
import subprocess
import urllib.parse
import urllib.request
import uuid
from html.parser import HTMLParser
from pathlib import Path

from .store import _terms


MAX_FILE = 200_000
MAX_OUTPUT = 12_000
ALLOWED_SUFFIXES = {".py", ".md", ".txt", ".json", ".toml", ".yaml", ".yml", ".csv", ".tsv"}


class ToolError(RuntimeError):
    pass


class _Text(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []
        self.skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self.skip += 1
        if tag in ("p", "br", "div", "li", "h1", "h2", "h3"):
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self.skip -= 1

    def handle_data(self, data):
        if not self.skip:
            self.parts.append(data)


class _SearchResults(HTMLParser):
    def __init__(self):
        super().__init__()
        self.results = []
        self.capture = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        classes = attrs.get("class", "").split()
        if tag == "a" and "result-link" in classes:
            href = html.unescape(attrs.get("href", ""))
            parsed = urllib.parse.urlparse(urllib.parse.urljoin("https://duckduckgo.com", href))
            url = urllib.parse.parse_qs(parsed.query).get("uddg", [""])[0]
            if url:
                self.results.append({"title": "", "url": url, "snippet": ""})
                self.capture = "title"
        elif tag == "td" and "result-snippet" in classes and self.results:
            self.capture = "snippet"

    def handle_endtag(self, tag):
        if (tag == "a" and self.capture == "title") or (tag == "td" and self.capture == "snippet"):
            self.capture = None

    def handle_data(self, data):
        if self.capture and self.results:
            self.results[-1][self.capture] += data


def _public_url(url):
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ToolError("Only public HTTPS URLs are allowed")
    if parsed.port not in (None, 443):
        raise ToolError("Nonstandard ports are blocked")
    host = parsed.hostname.lower()
    if host in ("localhost",) or host.endswith((".local", ".internal")):
        raise ToolError("Private hosts are blocked")
    try:
        addresses = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ToolError("Host lookup failed") from exc
    if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
        raise ToolError("Private addresses are blocked")
    return url


class _SafeRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, msg, headers, newurl):
        _public_url(newurl)
        return super().redirect_request(request, fp, code, msg, headers, newurl)


def fetch_url(url):
    _public_url(url)
    opener = urllib.request.build_opener(_SafeRedirect())
    request = urllib.request.Request(url, headers={"User-Agent": "EvoCollab/0.1 (academic research)"})
    with opener.open(request, timeout=15) as response:
        content_type = response.headers.get_content_type()
        if content_type not in ("text/html", "text/plain", "application/json", "application/xml", "text/xml"):
            raise ToolError("Unsupported remote content type")
        raw = response.read(150_001)
        if len(raw) > 150_000:
            raise ToolError("Remote response exceeds 150 KB")
        charset = response.headers.get_content_charset() or "utf-8"
    value = raw.decode(charset, "replace")
    if content_type == "text/html":
        parser = _Text()
        parser.feed(value)
        value = " ".join(" ".join(parser.parts).split())
    return value[:MAX_OUTPUT]


def web_search(query):
    if not isinstance(query, str) or not query.strip() or len(query) > 300:
        raise ToolError("Search query must be 1–300 characters")
    url = "https://lite.duckduckgo.com/lite/?q=" + urllib.parse.quote(query.strip())
    _public_url(url)
    opener = urllib.request.build_opener(_SafeRedirect())
    with opener.open(urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"}), timeout=15) as r:
        raw = r.read(150_001)
    if len(raw) > 150_000:
        raise ToolError("Search response too large")
    parser = _SearchResults()
    parser.feed(raw.decode("utf-8", "replace"))
    results = []
    seen = set()
    query_terms = _terms(query)
    for item in parser.results:
        try:
            _public_url(item["url"])
        except (ToolError, ValueError):
            continue
        overlap = len(query_terms & _terms(item["title"] + " " + item["snippet"]))
        if overlap < min(2, len(query_terms)) or item["url"] in seen:
            continue
        seen.add(item["url"])
        item["title"] = " ".join(item["title"].split())[:200]
        item["snippet"] = " ".join(item["snippet"].split())[:500]
        item["relevance"] = overlap
        results.append(item)
    results.sort(key=lambda item: item["relevance"], reverse=True)
    if not results:
        raise ToolError("No relevant public HTTPS results; refine the search query")
    return [{k: v for k, v in item.items() if k != "relevance"} for item in results[:5]]


class AgentTools:
    def __init__(self, root, image="python:3.11-slim", exchange_root=None):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True)
        self.image = image
        self.exchange = Path(exchange_root).resolve() if exchange_root else None
        if self.exchange:
            self.exchange.mkdir(parents=True, exist_ok=True)

    def _path(self, name, must_exist=False):
        if not isinstance(name, str) or not name or name.startswith("/") or "\x00" in name:
            raise ToolError("Path must be relative to the private workspace")
        if any(p in (".git", "..") for p in Path(name).parts):
            raise ToolError("Protected or parent path")
        path = (self.root / name).resolve()
        if path == self.root or self.root not in path.parents:
            raise ToolError("Path escapes private workspace")
        if ".git" in path.relative_to(self.root).parts:
            raise ToolError("Git internals are protected")
        if must_exist and not path.is_file():
            raise ToolError("File does not exist")
        if path.suffix.lower() not in ALLOWED_SUFFIXES:
            raise ToolError("Unsupported file suffix")
        return path

    def read_file(self, path):
        target = self._path(path, True)
        if target.stat().st_size > MAX_FILE:
            raise ToolError("File too large")
        return target.read_text(encoding="utf-8")

    def write_file(self, path, content):
        target = self._path(path)
        if not isinstance(content, str) or len(content.encode("utf-8")) > MAX_FILE:
            raise ToolError("Content exceeds file limit")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding="utf-8")
        return "Wrote %s" % path

    def delete_file(self, path):
        target = self._path(path, True)
        target.unlink()
        return "Deleted %s" % path

    def list_files(self):
        return [str(p.relative_to(self.root)) for p in self.root.rglob("*")
                if p.is_file() and ".git" not in p.parts and p.suffix.lower() in ALLOWED_SUFFIXES][:200]

    def publish_file(self, path):
        if not self.exchange:
            raise ToolError("Artifact exchange is not configured")
        source = self._path(path, True)
        if source.stat().st_size > MAX_FILE:
            raise ToolError("Artifact exceeds file limit")
        artifact_id = uuid.uuid4().hex[:12] + source.suffix.lower()
        shutil.copyfile(source, self.exchange / artifact_id)
        return {"artifact_id": artifact_id, "source": path}

    def list_artifacts(self):
        if not self.exchange:
            raise ToolError("Artifact exchange is not configured")
        return sorted(p.name for p in self.exchange.iterdir() if p.is_file())[:200]

    def import_file(self, artifact_id, path):
        if not self.exchange or not isinstance(artifact_id, str) or not re.fullmatch(r"[0-9a-f]{12}\.[a-z0-9]+", artifact_id):
            raise ToolError("Invalid artifact ID")
        source = self.exchange / artifact_id
        if not source.is_file() or source.stat().st_size > MAX_FILE:
            raise ToolError("Artifact not found or too large")
        target = self._path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        return "Imported %s to %s" % (artifact_id, path)

    def run_python(self, script, args=None, timeout=20):
        target = self._path(script, True)
        if target.suffix != ".py":
            raise ToolError("Only Python scripts can be executed")
        if not shutil.which("docker"):
            raise ToolError("Docker is required for code execution")
        args = args or []
        if not isinstance(args, list) or len(args) > 20 or any(not isinstance(a, str) or len(a) > 200 for a in args):
            raise ToolError("Invalid script arguments")
        timeout = min(max(int(timeout), 1), 60)
        uid, gid = os.getuid(), os.getgid()
        cmd = ["docker", "run", "--rm", "--network", "none", "--read-only",
               "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
               "--memory", "256m", "--cpus", "1", "--pids-limit", "64",
               "--user", "%s:%s" % (uid, gid), "--tmpfs", "/tmp:rw,noexec,nosuid,size=32m",
               "--mount", "type=bind,source=%s,target=/workspace" % self.root,
               "--workdir", "/workspace", "--env", "PYTHONDONTWRITEBYTECODE=1",
               self.image, "python", "-I", "/workspace/" + str(target.relative_to(self.root))] + args
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout + 10, check=False)
        except subprocess.TimeoutExpired as exc:
            raise ToolError("Execution timed out") from exc
        return {"exit_code": result.returncode, "stdout": result.stdout[:MAX_OUTPUT],
                "stderr": result.stderr[:MAX_OUTPUT]}

    def _git(self, *args, auth_scope=None):
        if not shutil.which("docker"):
            raise ToolError("Docker is required for Git operations")
        env = dict(os.environ, GIT_TERMINAL_PROMPT="0", GIT_CONFIG_NOSYSTEM="1",
                   GIT_CONFIG_GLOBAL=os.devnull)
        if auth_scope:
            token = os.getenv("GITHUB_TOKEN")
            if not token:
                raise ToolError("GITHUB_TOKEN is required for HTTPS push")
            credential = base64.b64encode(("x-access-token:" + token).encode()).decode()
            env.update(GIT_CONFIG_COUNT="1", GIT_CONFIG_KEY_0="http.%s.extraHeader" % auth_scope,
                       GIT_CONFIG_VALUE_0="Authorization: Basic " + credential)
        uid, gid = os.getuid(), os.getgid()
        cmd = ["docker", "run", "--rm", "--network", "bridge" if auth_scope else "none",
               "--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
               "--memory", "256m", "--cpus", "1", "--pids-limit", "64",
               "--user", "%s:%s" % (uid, gid), "--tmpfs", "/tmp:rw,noexec,nosuid,size=32m",
               "--mount", "type=bind,source=%s,target=/workspace" % self.root,
               "--workdir", "/workspace", "--env", "GIT_TERMINAL_PROMPT",
               "--env", "GIT_CONFIG_NOSYSTEM", "--env", "GIT_CONFIG_GLOBAL"]
        if auth_scope:
            cmd += ["--env", "GIT_CONFIG_COUNT", "--env", "GIT_CONFIG_KEY_0",
                    "--env", "GIT_CONFIG_VALUE_0"]
        cmd += ["--entrypoint", "git", "alpine/git:2.49.1", "-C", "/workspace",
                "-c", "core.hooksPath=/dev/null", "-c", "protocol.ext.allow=never",
                "-c", "protocol.file.allow=never", "-c", "credential.helper=",
                "-c", "core.sshCommand=false"] + list(args)
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=90, env=env, check=False)
        except subprocess.TimeoutExpired as exc:
            raise ToolError("Git timed out") from exc
        if result.returncode:
            raise ToolError(result.stderr[:1000] or "Git failed")
        return result.stdout[:MAX_OUTPUT]

    def git_init(self):
        return self._git("init")

    def git_status(self):
        return self._git("status", "--short")

    def git_commit(self, message):
        if not isinstance(message, str) or not 1 <= len(message) <= 200:
            raise ToolError("Invalid commit message")
        self._git("add", "--", ".")
        return self._git("-c", "user.name=Evo Agent", "-c", "user.email=evo-agent@localhost",
                         "commit", "-m", message)

    def git_push(self, repository, branch="main"):
        if not re.fullmatch(r"https://github\.com/[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+(?:\.git)?", repository):
            raise ToolError("Only HTTPS GitHub repository URLs are allowed")
        if not re.fullmatch(r"[A-Za-z0-9._/-]{1,100}", branch) or ".." in branch:
            raise ToolError("Invalid branch")
        config = self._git("config", "--list", "--null")
        keys = [entry.split("\n", 1)[0].lower() for entry in config.split("\x00") if entry]
        if any(key.startswith("url.") and key.endswith((".insteadof", ".pushinsteadof"))
               for key in keys):
            raise ToolError("URL rewrite rules are not allowed for push")
        return self._git("push", repository, "HEAD:refs/heads/" + branch, auth_scope=repository)

    def call(self, name, args):
        if not isinstance(args, dict):
            raise ToolError("Tool arguments must be an object")
        methods = {
            "read_file": self.read_file, "write_file": self.write_file,
            "delete_file": self.delete_file, "list_files": self.list_files,
            "publish_file": self.publish_file, "list_artifacts": self.list_artifacts,
            "import_file": self.import_file,
            "run_python": self.run_python, "web_search": web_search,
            "fetch_url": fetch_url, "git_init": self.git_init,
            "git_status": self.git_status, "git_commit": self.git_commit,
            "git_push": self.git_push,
        }
        if name not in methods:
            raise ToolError("Unknown tool")
        try:
            return methods[name](**args)
        except TypeError as exc:
            raise ToolError("Invalid tool arguments") from exc
