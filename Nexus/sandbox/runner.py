"""Sandboxed runner for generated skills.

Isolation here is *process-level*, not a security boundary: the child runs
with a scrubbed environment (no API key, no HOME), a 1 GiB address-space cap
(RLIMIT_AS, Linux), a throwaway script directory and a hard timeout. That
raises the bar considerably but does not stop a determined payload from
exploiting the interpreter or the OS. Treat the AST policy as the real gate,
and deploy untrusted skills inside a container (or stronger) in addition to
these measures.
"""
import os
import shutil
import subprocess
import sys
import tempfile
import time
from pathlib import Path

from Nexus.sandbox.policy import validate_code

MAX_EXECUTION_SEC = 30
MAX_MEMORY_BYTES = 1024 * 1024 * 1024  # 1 GiB address-space cap for the child


def _sanitize_env(run_dir: Path) -> dict:
    """Minimal child environment.

    Built from scratch rather than copied from the parent: NEXUS_NEBIUS_API_KEY
    and HOME (and every other inherited secret) are dropped by construction.
    """
    return {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "TMPDIR": str(run_dir),
        "PYTHONIOENCODING": "utf-8",
    }


def _apply_resource_limits() -> None:
    """Cap the child's address space. Runs between fork and exec (Linux only)."""
    try:
        import resource
    except ImportError:  # non-POSIX
        return
    try:
        resource.setrlimit(resource.RLIMIT_AS, (MAX_MEMORY_BYTES, MAX_MEMORY_BYTES))
    except (ValueError, OSError):
        pass  # a limit we cannot set must not prevent execution


def run_skill(source: str, workspace: str) -> dict:
    """Run validated Python source in a subprocess inside `workspace`.

    The script itself lives in a fresh `tempfile.mkdtemp()` directory (removed
    in `finally`); `workspace` stays the cwd so skills can do their file I/O
    in a stable, known location.

    Returns a dict with status ("ok", "error", "timeout" or "rejected"),
    stdout, stderr, exit_code and runtime (seconds).
    """
    valid, error = validate_code(source)
    if not valid:
        return {
            "status": "rejected",
            "error": error,
            "stdout": "",
            "stderr": error,
            "exit_code": 1,
            "runtime": 0.0,
        }

    workspace = Path(workspace)
    workspace.mkdir(parents=True, exist_ok=True)

    run_dir = Path(tempfile.mkdtemp(prefix="nexus_skill_"))
    script_path = run_dir / "skill.py"
    script_path.write_text(source, encoding="utf-8")

    kwargs = {
        "cwd": workspace,
        "env": _sanitize_env(run_dir),
        "capture_output": True,
        "text": True,
        "timeout": MAX_EXECUTION_SEC,
    }
    if sys.platform == "linux":
        kwargs["preexec_fn"] = _apply_resource_limits

    started = time.monotonic()
    try:
        proc = subprocess.run([sys.executable, str(script_path)], **kwargs)
    except subprocess.TimeoutExpired:
        return {
            "status": "timeout",
            "stdout": "",
            "stderr": f"Execution exceeded {MAX_EXECUTION_SEC}s",
            "exit_code": 1,
            "runtime": MAX_EXECUTION_SEC,
        }
    finally:
        shutil.rmtree(run_dir, ignore_errors=True)

    runtime = time.monotonic() - started
    return {
        "status": "ok" if proc.returncode == 0 else "error",
        "stdout": proc.stdout,
        "stderr": proc.stderr,
        "exit_code": proc.returncode,
        "runtime": runtime,
    }
