"""Tests for the headless HTTP server (`python -m Nexus serve`)."""

import contextlib
import json
import threading
import urllib.error
import urllib.request

import pytest

from Nexus.core.router import Intent
from Nexus.web.server import NexusWebApp, make_server


class _StubEngine:
    """Stands in for NexusEngine so the HTTP layer can be tested without a GGUF."""

    def __init__(self):
        self.messages = []

    def process_message(self, message):
        self.messages.append(message)
        return {
            "response": f"echo: {message}",
            "intent": Intent.CHAT,
            "memory_results": None,
            "cloud_approved": False,
        }


@contextlib.contextmanager
def running_server(app, token=None):
    """Run the server on a free port for the duration of the block."""
    httpd = make_server("127.0.0.1", 0, app=app, token=token)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{httpd.server_address[1]}"
    finally:
        httpd.shutdown()
        httpd.server_close()
        thread.join(timeout=5)


def request(base, path, method="GET", payload=None, token=None):
    """Return (status, content_type, body) without raising on 4xx/5xx."""
    data = json.dumps(payload).encode() if payload is not None else None
    headers = {"Content-Type": "application/json"} if data else {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(
        base + path,
        data=data,
        method=method,
        headers=headers,
    )
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, resp.headers.get("Content-Type", ""), resp.read().decode()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.headers.get("Content-Type", ""), exc.read().decode()


def test_index_page_is_served(isolated_settings):
    with running_server(NexusWebApp(settings=isolated_settings)) as base:
        status, content_type, body = request(base, "/")

    assert status == 200
    assert "text/html" in content_type
    assert "<title>Nexus" in body
    assert 'id="prompt"' in body


def test_status_reports_missing_model(isolated_settings):
    with running_server(NexusWebApp(settings=isolated_settings)) as base:
        status, content_type, body = request(base, "/api/status")

    assert status == 200
    assert "application/json" in content_type
    payload = json.loads(body)
    assert payload["status"] == "model_missing"
    assert payload["model"]["present"] is False
    assert payload["model"]["loaded"] is False
    assert payload["local_only"] is True
    assert payload["skills"] == 0
    assert payload["episodes"] == 0


def test_chat_returns_503_without_a_model(isolated_settings):
    with running_server(NexusWebApp(settings=isolated_settings)) as base:
        status, _, body = request(base, "/api/chat", "POST", {"message": "hello"})

    assert status == 503
    payload = json.loads(body)
    assert payload["status"] == "unavailable"
    assert "No local model" in payload["error"]
    assert "huggingface-cli download" in payload["error"]


def test_chat_routes_through_the_engine(isolated_settings):
    engine = _StubEngine()
    with running_server(NexusWebApp(settings=isolated_settings, engine=engine)) as base:
        status, _, body = request(base, "/api/chat", "POST", {"message": "hello"})

        _, _, status_body = request(base, "/api/status")

    assert status == 200
    payload = json.loads(body)
    assert payload["response"] == "echo: hello"
    assert payload["intent"] == "CHAT"
    assert payload["cloud_approved"] is False
    assert engine.messages == ["hello"]
    assert json.loads(status_body)["status"] == "ready"


def test_chat_endpoint_uses_the_real_engine(isolated_settings):
    """The endpoint must serialize a real NexusEngine result, not just a stub."""
    from Nexus.core.engine import NexusEngine
    from Nexus.core.privacy_gate import PrivacyGate

    class _LLM:
        def chat(self, messages, temperature=0.7):
            return "engine reply"

    # Built on the server thread, like production: the stores reject cross-thread use.
    def build_engine():
        return NexusEngine(
            settings=isolated_settings,
            privacy_gate=PrivacyGate(isolated_settings),
            llm=_LLM(),
        )

    app = NexusWebApp(settings=isolated_settings, engine_factory=build_engine)
    with running_server(app) as base:
        status, _, body = request(base, "/api/chat", "POST", {"message": "hello"})
        # A second request must reuse the same engine and its SQLite connections.
        second_status, _, _ = request(base, "/api/chat", "POST", {"message": "again"})
        _, _, status_body = request(base, "/api/status")

    assert status == 200
    assert second_status == 200
    assert json.loads(body) == {
        "response": "engine reply",
        "intent": "CHAT",
        "cloud_approved": False,
    }
    assert json.loads(status_body)["episodes"] == 4  # user + assistant per turn


def test_chat_rejects_a_missing_message(isolated_settings):
    with running_server(NexusWebApp(settings=isolated_settings)) as base:
        status, _, body = request(base, "/api/chat", "POST", {"message": "   "})

    assert status == 400
    assert "message" in json.loads(body)["error"]


def test_chat_rejects_a_non_json_body(isolated_settings):
    with running_server(NexusWebApp(settings=isolated_settings)) as base:
        req = urllib.request.Request(
            base + "/api/chat",
            data=b"not json",
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        with pytest.raises(urllib.error.HTTPError) as excinfo:
            urllib.request.urlopen(req, timeout=10)
        body = excinfo.value.read().decode()

    assert excinfo.value.code == 400
    assert "invalid JSON" in json.loads(body)["error"]


def test_unknown_route_returns_404(isolated_settings):
    with running_server(NexusWebApp(settings=isolated_settings)) as base:
        status, _, body = request(base, "/api/nope")

    assert status == 404
    assert "no route" in json.loads(body)["error"]


def test_api_requires_bearer_token_when_set(isolated_settings):
    """With a token configured, every /api/ route 401s without it."""
    app = NexusWebApp(settings=isolated_settings)
    with running_server(app, token="sekret") as base:
        denied_status, _, denied_body = request(base, "/api/status")
        wrong_status, _, _ = request(base, "/api/status", token="wrong")
        granted_status, _, _ = request(base, "/api/status", token="sekret")
        chat_denied, _, _ = request(base, "/api/chat", "POST", {"message": "hi"})
        chat_granted, _, _ = request(
            base, "/api/chat", "POST", {"message": "hi"}, token="sekret"
        )
        page_status, _, _ = request(base, "/")  # the UI shell is not gated

    assert denied_status == 401
    assert wrong_status == 401
    assert "unauthorized" in json.loads(denied_body)["error"]
    assert granted_status == 200
    assert chat_denied == 401
    # Auth passes; the missing GGUF then yields the usual 503, not a 401.
    assert chat_granted == 503
    assert page_status == 200


def test_api_without_token_stays_open_on_loopback(isolated_settings):
    """No token set: loopback-only server keeps working as before."""
    with running_server(NexusWebApp(settings=isolated_settings)) as base:
        status, _, _ = request(base, "/api/status")

    assert status == 200


def test_serve_refuses_non_loopback_without_token():
    """`python -m Nexus serve --host 0.0.0.0` must refuse without --token."""
    from Nexus.web.server import is_loopback_host, serve

    assert is_loopback_host("127.0.0.1")
    assert is_loopback_host("localhost")
    assert not is_loopback_host("0.0.0.0")
    assert not is_loopback_host("192.168.1.10")

    with pytest.raises(SystemExit) as excinfo:
        serve(host="0.0.0.0", port=0)
    assert excinfo.value.code == 1


def test_audit_and_skill_endpoints(isolated_settings):
    from Nexus.skills.registry import SkillRegistry

    registry = SkillRegistry()
    assert registry.register("noop", "Does nothing", "print('noop')\n")
    registry.conn.close()

    with running_server(NexusWebApp(settings=isolated_settings)) as base:
        _, _, skills_body = request(base, "/api/skills")
        _, _, audit_body = request(base, "/api/audit?limit=5")
        _, _, status_body = request(base, "/api/status")

    skills = json.loads(skills_body)["skills"]
    assert [s["name"] for s in skills] == ["noop"]
    assert json.loads(audit_body)["entries"] == []
    assert json.loads(status_body)["skills"] == 1
