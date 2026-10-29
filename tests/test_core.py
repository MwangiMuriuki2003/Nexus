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
    assert "open" in BANNED_BUILTINS


def test_memory_manager_exposes_both_stores():
    """Test MemoryManager is importable and wires up episodic + semantic memory."""
    from Nexus.core.memory_manager import MemoryManager

    assert hasattr(MemoryManager, "query")
    assert hasattr(MemoryManager, "add_chat_message")
    assert hasattr(MemoryManager, "add_document")
