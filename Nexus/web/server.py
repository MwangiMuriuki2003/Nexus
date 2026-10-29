"""Headless HTTP server for Nexus.

`python -m Nexus --headless` serves a single-page chat UI plus a small JSON API,
so the assistant can run where there is no Qt display: a server, a container, or
an SSH session. It is the same engine the desktop app uses, so memory, skills and
the privacy gate behave identically.

Routes
------
GET  /             single-page UI
GET  /api/status   model and runtime status
GET  /api/skills   registered skills
GET  /api/audit    audit log entries (?limit=N, max 500)
POST /api/chat     {"message": "..."} -> {"response", "intent", "cloud_approved"}

Auth
----
`--host` defaults to 127.0.0.1. Binding a non-loopback address requires
`--token <secret>` (the server refuses to start otherwise), and when a token
is set every `/api/*` route requires `Authorization: Bearer <token>`.
"""

from __future__ import annotations

import hmac
import ipaddress
import json
import sqlite3
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from Nexus.config import ensure_dirs, settings as default_settings
from Nexus.web.page import INDEX_HTML

MAX_BODY_BYTES = 1024 * 1024  # 1 MiB
MAX_AUDIT_LIMIT = 500


def is_loopback_host(host: str) -> bool:
    """True only for addresses reachable from this machine alone."""
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False

MODEL_HELP = (
    "Download it with:\n"
    "  huggingface-cli download {model} {file} --local-dir {dir}"
)


class NexusWebApp:
    """Request handling for the headless server, independent of the HTTP layer.

    The engine is built lazily: starting the server must not wait for a multi-GB
    GGUF to load, and must still work when no model is installed at all.

    `engine_factory` exists because the engine must be constructed on the thread
    that will use it: the SQLite stores it opens reject cross-thread use, so a
    lazily built engine belongs on the server's request thread.
    """

    def __init__(self, settings=None, engine=None, engine_factory=None):
        self.settings = settings or default_settings
        self._engine = engine
        self._engine_factory = engine_factory or self._build_engine
        self._lock = threading.Lock()

    def _build_engine(self):
        if not self.model_path.exists():
            raise RuntimeError(
                f"No local model at {self.model_path}. "
                + MODEL_HELP.format(
                    model=self.settings.model_name,
                    file=self.settings.gguf_filename,
                    dir=self.settings.model_dir,
                )
            )
        from Nexus.core.engine import NexusEngine

        return NexusEngine(settings=self.settings)

    @property
    def model_path(self) -> Path:
        return Path(self.settings.model_dir) / self.settings.gguf_filename

    def engine(self):
        """Return the shared engine, building it on first use."""
        with self._lock:
            if self._engine is None:
                self._engine = self._engine_factory()
            return self._engine

    def chat(self, message: str) -> dict:
        """Route one message through the engine and return JSON-safe data."""
        result = self.engine().process_message(message)
        return {
            "response": result.get("response", ""),
            "intent": result["intent"].name,
            "cloud_approved": bool(result.get("cloud_approved")),
        }

    def status(self) -> dict:
        path = self.model_path
        present = path.exists()
        loaded = self._engine is not None
        if loaded:
            state = "ready"
        elif present:
            state = "idle"  # model on disk, not loaded yet
        else:
            state = "model_missing"
        return {
            "status": state,
            "model": {
                "name": self.settings.model_name,
                "path": str(path),
                "present": present,
                "loaded": loaded,
            },
            "data_dir": str(self.settings.data_dir),
            "local_only": not bool(self.settings.nebius_api_key.get_secret_value()),
            "skills": len(self.skills()),
            "episodes": self._episode_count(),
        }

    def skills(self) -> list[dict]:
        from Nexus.skills.registry import SkillRegistry

        db_path = Path(self.settings.skills_dir) / "skills.db"
        registry = None
        try:
            registry = SkillRegistry(db_path=db_path)
            return registry.list_all()
        except Exception:
            return []
        finally:
            if registry is not None:
                registry.conn.close()

    def audit(self, limit: int = 50) -> list[dict]:
        from Nexus.audit.logger import AuditLogger

        logger = None
        try:
            logger = AuditLogger(Path(self.settings.audit_path))
            rows = logger.get_logs(limit=limit)
        except Exception:
            return []
        finally:
            if logger is not None:
                logger.conn.close()
        keys = ("timestamp", "action", "detail", "risk_level")
        return [dict(zip(keys, row)) for row in rows]

    def _episode_count(self) -> int:
        path = Path(self.settings.db_path)
        if not path.exists():
            return 0
        try:
            conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
            try:
                return conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
            finally:
                conn.close()
        except sqlite3.Error:
            return 0


class NexusRequestHandler(BaseHTTPRequestHandler):
    """Routes requests to a `NexusWebApp`; `app`/`token` are bound by `make_server`."""

    server_version = "Nexus/0.1"
    app: NexusWebApp | None = None
    token: str | None = None

    def _authorized(self) -> bool:
        """`/api/*` requires `Authorization: Bearer <token>` when a token is set."""
        if not self.token:
            return True
        header = self.headers.get("Authorization", "")
        expected = f"Bearer {self.token}"
        return hmac.compare_digest(header.encode(), expected.encode())

    def _check_api_auth(self, path: str) -> bool:
        """Send 401 and return False when an /api/ request lacks the token."""
        if not path.startswith("/api/") or self._authorized():
            return True
        self._send_json(401, {"error": "unauthorized: missing or invalid bearer token"})
        return False

    def do_GET(self):
        url = urlparse(self.path)
        if not self._check_api_auth(url.path):
            return
        try:
            if url.path in ("/", "/index.html"):
                self._send(200, INDEX_HTML.encode("utf-8"), "text/html; charset=utf-8")
            elif url.path == "/api/status":
                self._send_json(200, self.app.status())
            elif url.path == "/api/skills":
                self._send_json(200, {"skills": self.app.skills()})
            elif url.path == "/api/audit":
                limit = self._int_param(url.query, "limit", default=50)
                self._send_json(200, {"entries": self.app.audit(limit)})
            else:
                self._send_json(404, {"error": f"no route for {url.path}"})
        except Exception as exc:  # never drop the connection on an unexpected error
            self._send_json(500, {"error": str(exc)})

    def do_POST(self):
        url = urlparse(self.path)
        if not self._check_api_auth(url.path):
            return
        if url.path != "/api/chat":
            self._send_json(404, {"error": f"no route for {url.path}"})
            return

        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if length <= 0 or length > MAX_BODY_BYTES:
            self._send_json(400, {"error": "expected a JSON body under 1 MiB"})
            return

        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            self._send_json(400, {"error": f"invalid JSON: {exc}"})
            return

        message = payload.get("message") if isinstance(payload, dict) else None
        if not isinstance(message, str) or not message.strip():
            self._send_json(400, {"error": "field 'message' is required"})
            return

        try:
            self._send_json(200, self.app.chat(message.strip()))
        except RuntimeError as exc:
            # Missing model, or the model failed to load: 503 with the real reason.
            self._send_json(503, {"error": str(exc), "status": "unavailable"})
        except Exception as exc:
            self._send_json(500, {"error": str(exc)})

    # -- helpers ---------------------------------------------------------------

    def _int_param(self, query: str, name: str, default: int) -> int:
        raw = parse_qs(query).get(name, [""])[0]
        try:
            value = int(raw)
        except (TypeError, ValueError):
            return default
        return max(1, min(value, MAX_AUDIT_LIMIT))

    def _send_json(self, code: int, payload: dict):
        self._send(code, json.dumps(payload).encode("utf-8"), "application/json")

    def _send(self, code: int, body: bytes, content_type: str):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)


def make_server(host: str = "127.0.0.1", port: int = 8080, app: NexusWebApp | None = None,
                token: str | None = None):
    """Build (but do not start) the HTTP server. Port 0 picks a free port.

    Requests are handled one at a time (plain `HTTPServer`, not the threading
    variant). That suits a single-user local app, and it keeps the engine — and
    the SQLite connections and llama.cpp context it owns — on one thread.

    When `token` is set, every /api/ route demands `Authorization: Bearer`.
    """
    app = app or NexusWebApp()
    handler = type("BoundNexusHandler", (NexusRequestHandler,), {"app": app, "token": token})
    return HTTPServer((host, port), handler)


def serve(host: str = "127.0.0.1", port: int = 8080, token: str | None = None):
    """Blocking entry point for `python -m Nexus serve`."""
    if not is_loopback_host(host) and not token:
        print(
            f"error: refusing to bind non-loopback host {host} without a token; "
            "pass --token <secret> (clients then send Authorization: Bearer <secret>)",
            file=sys.stderr,
            flush=True,
        )
        raise SystemExit(1)
    ensure_dirs()
    try:
        httpd = make_server(host, port, token=token)
    except OSError as exc:
        print(f"error: cannot bind {host}:{port} — {exc}", file=sys.stderr, flush=True)
        raise SystemExit(1)
    app = httpd.RequestHandlerClass.app
    bound_host = httpd.server_address[0]
    shown = "localhost" if bound_host in ("127.0.0.1", "0.0.0.0", "::") else bound_host

    # flush=True: the banner must show up when stdout is a pipe (Docker, logs).
    print(f"Nexus headless server: http://{shown}:{httpd.server_address[1]}/", flush=True)
    if not app.model_path.exists():
        print(f"  ! no local model at {app.model_path}", flush=True)
        print(
            "    run `python -m Nexus setup` for the download command; the UI still starts",
            flush=True,
        )
    print("  Press Ctrl+C to stop.", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down.", flush=True)
    finally:
        httpd.server_close()
