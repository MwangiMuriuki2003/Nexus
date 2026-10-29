"""Core module tests for Nexus."""

import inspect
from types import SimpleNamespace

from Nexus.config import settings
from Nexus.core.router import IntentRouter, Intent
from Nexus.core.privacy_gate import PrivacyGate
from Nexus.sandbox.policy import validate_code, ALLOWED_IMPORTS, BANNED_BUILTINS


def test_intent_router():
    """Test intent routing logic."""
    router = IntentRouter()

    assert router.route("hello") == Intent.CHAT
    assert router.route("what did i copy yesterday") == Intent.MEMORY_QUERY
    assert router.route("create a skill to archive logs") == Intent.SKILL_CREATION
    assert router.route("!ultra complex question") == Intent.CLOUD_BURST
    assert router.route("/skill some_skill") == Intent.SKILL_EXEC


def test_privacy_gate_denies_by_default(tmp_path, monkeypatch):
    """The gate must reject cloud requests unless a UI approval arrives."""
    monkeypatch.setattr(settings, "audit_path", tmp_path / "audit.db")
    gate = PrivacyGate(settings)

    result = gate.cloud_request(
        [{"role": "user", "content": "test"}],
        reason="test reason",
    )

    assert isinstance(result, dict)
    assert result.get("role") == "assistant"
    assert "denied" in result["content"].lower()

    # The denial is written to the append-only audit log.
    logs = gate.audit.get_logs()
    assert logs and logs[0][1] == "cloud_request"


def test_nebius_client_chat_is_a_bound_method():
    """`chat` must be a NebiusClient method (it used to sit at module level)."""
    from Nexus.models.nebius_client import NebiusClient

    client = NebiusClient("test-key", "https://example.invalid/v1/")
    assert inspect.ismethod(client.chat) and client.chat.__self__ is client

    captured = {}

    class _Completions:
        def create(self, **kwargs):
            captured.update(kwargs)
            return SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="nebius reply"))]
            )

    client.client = SimpleNamespace(chat=SimpleNamespace(completions=_Completions()))

    reply = client.chat([{"role": "user", "content": "hi"}])

    assert reply == "nebius reply"
    assert captured["messages"] == [{"role": "user", "content": "hi"}]
    assert captured["model"] == "nvidia/Nemotron-3-Ultra-550B"


def test_privacy_gate_uses_injected_approval_callback(tmp_path, monkeypatch):
    """An injected callback drives approval; Session scope short-circuits later asks."""
    monkeypatch.setattr(settings, "audit_path", tmp_path / "audit.db")
    seen = []

    def approve(reason: str, tokens: int) -> bool:
        seen.append((reason, tokens))
        return True

    gate = PrivacyGate(settings, approval_callback=approve)

    assert gate.request_approval("big reasoning job", 1234) is True
    assert seen == [("big reasoning job", 1234)]

    # A session-wide approval skips the modal entirely.
    gate.approved = True
    assert gate.request_approval("another job", 10) is True
    assert seen == [("big reasoning job", 1234)]


def test_privacy_gate_callback_failure_fails_closed(tmp_path, monkeypatch):
    """A raising approval modal must deny, never approve."""
    monkeypatch.setattr(settings, "audit_path", tmp_path / "audit.db")

    def broken(reason: str, tokens: int) -> bool:
        raise RuntimeError("modal exploded")

    gate = PrivacyGate(settings, approval_callback=broken)

    assert gate.request_approval("job", 10) is False


def test_validate_code():
    """Test AST code validation."""
    valid_code = '''
import os
import json
def hello():
    return "world"
'''
    valid, error = validate_code(valid_code)
    assert valid is True, f"Valid code rejected: {error}"

    invalid_code = '''
import requests
'''
    valid, error = validate_code(invalid_code)
    assert valid is False, "Invalid code should be rejected"
    assert "requests" in error.lower()

    invalid_code2 = '''
x = eval("1+1")
'''
    valid, error = validate_code(invalid_code2)
    assert valid is False, "eval should be rejected"
    assert "eval" in error.lower()


def test_allowed_imports():
    """Test allowed imports list."""
    assert "os" in ALLOWED_IMPORTS
    assert "sys" in ALLOWED_IMPORTS
    assert "json" in ALLOWED_IMPORTS
    assert "pathlib" in ALLOWED_IMPORTS


def test_banned_builtins():
    """Test banned builtins list."""
    assert "exec" in BANNED_BUILTINS
    assert "eval" in BANNED_BUILTINS
    assert "compile" in BANNED_BUILTINS
    assert "__import__" in BANNED_BUILTINS
    # `open` is deliberately allowed: skills need file I/O.
    assert "open" not in BANNED_BUILTINS


def test_validate_code_rejects_evil_payloads():
    """The deny-list must reject every known-evil payload."""
    evil_payloads = {
        "network socket": "import socket\ns = socket.socket()\n",
        "network urllib": "import urllib.request\nurllib.request.urlopen('http://evil')\n",
        "network http": "import http.client\n",
        "network requests": "import requests\nrequests.get('http://evil')\n",
        "process subprocess": "import subprocess\nsubprocess.call(['id'])\n",
        "process multiprocessing": "import multiprocessing\n",
        "native ctypes": "import ctypes\nctypes.CDLL('libc.so.6')\n",
        "deserialize pickle": "import pickle\npickle.loads(b'...')\n",
        "os.system": "import os\nos.system('rm -rf /')\n",
        "os.popen": "import os\nos.popen('cat /etc/passwd')\n",
        "os.remove alias": "import os as o\no.remove('/tmp/x')\n",
        "os exec pattern": "import os\nos.execv('/bin/sh', ['sh'])\n",
        "os spawn pattern": "import os\nos.spawnlp(os.P_NOWAIT, 'ls', 'ls')\n",
        "from os import system": "from os import system\nsystem('id')\n",
        "builtin eval": "eval('1+1')\n",
        "builtin __import__": "__import__('os').system('id')\n",
        "dynamic exec": "exec('print(1)')\n",
    }
    for label, payload in evil_payloads.items():
        valid, error = validate_code(payload)
        assert valid is False, f"{label} must be rejected, got: {error}"


def test_validate_code_allows_file_io():
    """Skills must still be able to import os/json and use open()."""
    valid, error = validate_code(
        "import os\nimport json\n"
        "with open('out.txt', 'w') as f:\n    f.write(json.dumps({'ok': True}))\n"
        "print(os.path.join('a', 'b'))\n"
    )
    assert valid is True, f"legit file-I/O skill rejected: {error}"


def test_settings_derive_all_paths_from_data_dir(tmp_path, monkeypatch):
    """NEXUS_DATA_DIR must move every derived subpath with it."""
    from Nexus.config import Settings

    data_dir = tmp_path / "nexus-data"
    monkeypatch.setenv("NEXUS_DATA_DIR", str(data_dir))

    cfg = Settings()
    resolved = data_dir.resolve()

    assert cfg.data_dir == resolved
    assert cfg.model_dir == resolved / "models"
    assert cfg.skills_dir == resolved / "skills"
    assert cfg.sandbox_dir == resolved / "sandbox"
    assert cfg.db_path == resolved / "episodic.db"
    assert cfg.audit_path == resolved / "audit.db"
    assert cfg.chroma_path == resolved / "chroma"


def test_settings_api_key_is_secret(monkeypatch):
    """The Nebius key must be wrapped so it never leaks through repr/str."""
    from pydantic import SecretStr

    from Nexus.config import Settings

    monkeypatch.setenv("NEXUS_NEBIUS_API_KEY", "super-secret-key")
    cfg = Settings()

    assert isinstance(cfg.nebius_api_key, SecretStr)
    assert "super-secret-key" not in repr(cfg)
    assert "super-secret-key" not in str(cfg)
    assert cfg.nebius_api_key.get_secret_value() == "super-secret-key"


def test_memory_manager_exposes_both_stores():
    """Test MemoryManager is importable and wires up episodic + semantic memory."""
    from Nexus.core.memory_manager import MemoryManager

    assert hasattr(MemoryManager, "query")
    assert hasattr(MemoryManager, "add_chat_message")
    assert hasattr(MemoryManager, "add_document")
