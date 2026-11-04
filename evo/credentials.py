"""Local credential file for CLI use; never put secrets in a repository."""
import os
import stat
import tempfile
from pathlib import Path


def key_path(provider):
    if provider not in ("hkgai", "deepseek"):
        raise ValueError("Unsupported provider")
    override = os.getenv(provider.upper() + "_API_KEY_FILE")
    return Path(override).expanduser() if override else Path.home() / ".config" / "evo-collab" / (provider + ".key")


def load_key(provider, path=None):
    env_key = os.getenv(provider.upper() + "_API_KEY")
    if env_key:
        return env_key.strip()
    target = Path(path) if path else key_path(provider)
    if target.is_symlink():
        raise ValueError("Credential file must not be a symlink")
    if not target.exists():
        return None
    info = target.stat()
    if not stat.S_ISREG(info.st_mode) or info.st_mode & 0o077:
        raise ValueError("Credential file must be a private regular file (mode 600)")
    if hasattr(os, "getuid") and info.st_uid != os.getuid():
        raise ValueError("Credential file must belong to the current user")
    return target.read_text(encoding="utf-8").strip() or None


def save_key(provider, key, path=None):
    if not isinstance(key, str) or not key.strip() or "\n" in key or "\r" in key:
        raise ValueError("Invalid API key")
    target = Path(path) if path else key_path(provider)
    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(str(target.parent), 0o700)
    fd, temporary = tempfile.mkstemp(prefix=".key-", dir=str(target.parent))
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(key.strip() + "\n")
        os.replace(temporary, target)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return target
