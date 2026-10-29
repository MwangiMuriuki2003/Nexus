# Prompt: Fix critical flaws in the Nexus codebase

You are a senior Python engineer. **Nexus** is a private desktop AI brain: PyQt6 desktop app + headless HTTP server, local llama.cpp LLM, SQLite episodic memory, ChromaDB semantic memory, Nebius cloud-burst, AST-sandboxed skill execution. It has multiple critical bugs and security holes. Fix the issues below in priority order. Preserve public APIs where possible; refactor only where noted. Commit each tier separately.

## Tier 1 — Critical (app-breaking)

1. **`models/nebius_client.py`**: `def chat` is at module level, outside `NebiusClient`. Indent it to become a method. Verify `self.nebius.chat(messages)` works.

2. **`core/privacy_gate.py`**: `request_approval()` is a stub that always returns `False`. Implement a real mechanism:
   - Add an `approval_callback: Callable[[str, int], bool] | None` injection point.
   - Headless default: return `False`, log denial explicitly.
   - Qt mode: `MainWindow` injects a callback that opens a modal (reason, token estimate, model name, Once/Session/Always), blocks with 30s timeout, defaults to deny.

3. **`core/engine.py`**: `result["cloud_approved"]` is hardcoded `False`. Set `True` only when `cloud_request` returns an actual Nebius response (string), not the local-denial dict.

4. **`skills/scheduler.py` + `core/engine.py`**: Scheduler is constructed but never started; `atexit` targets the wrong global.
   - Switch `BlockingScheduler` → `BackgroundScheduler`.
   - In `NexusEngine.__init__`, call `self.skill_scheduler.start()`.
   - Register `self.skill_scheduler.shutdown` (not the module global) with `atexit`.

5. **`ui/main_window.py`**: `handle_send()` bypasses `NexusEngine` entirely (no memory, no skills, no audit). Rewrite to lazily construct a single `NexusEngine` and call `engine.process_message(text)`. Render `result["response"]`. Move LLM loading into the engine.

## Tier 2 — Security

6. **`sandbox/policy.py`**: The allow-list (`os`, `shutil`) makes the sandbox trivially escapable. Rewrite as deny-list:
   - Ban imports: `socket`, `urllib`, `http`, `requests`, `subprocess`, `ctypes`, `multiprocessing`, `pickle`.
   - Ban attribute access on `os`: `system`, `popen`, `exec*`, `spawn*`, `remove`, `unlink`, `rmdir` (walk AST for `ast.Attribute`).
   - Allow `open` (skills need file I/O).
   - Add tests with 5+ known-evil payloads; all must be rejected.

7. **`sandbox/runner.py`**: Add real isolation:
   - Pass `env=` with a sanitized dict (drop `NEXUS_NEBIUS_API_KEY`, `HOME`; keep minimal `PATH` + `TMPDIR`).
   - On Linux, set `RLIMIT_AS` via `preexec_fn` for memory cap.
   - Run inside `tempfile.mkdtemp()`; `shutil.rmtree` in `finally`.
   - Document that this is process-level isolation; recommend container deployment for untrusted skills.

8. **`web/server.py`**: Add auth.
   - Keep `--host` default `127.0.0.1`.
   - If `--host` is non-loopback, require `--token <secret>` or refuse to start.
   - When token is set, require `Authorization: Bearer <token>` on every `/api/*` route; return 401 otherwise.
   - Bump `MAX_BODY_BYTES` to 1 MiB.

9. **`ui/privacy_dashboard.py`**: Remove "Clear Log" button, or replace with "Export & Archive" that writes a timestamped snapshot and logs a `log_cleared` event before any deletion. Append-only logs must not be silently wiped.

10. **`config.py`**: Change `nebius_api_key: str` → `pydantic.SecretStr`. Replace inner `class Config` with `model_config = SettingsConfigDict(env_prefix="nexus_")`.

11. **`config.py` derived paths**: Replace `data_dir / "models"` defaults with a `model_post_init` that recomputes `model_dir`, `skills_dir`, `sandbox_dir`, `db_path`, `audit_path`, `chroma_path` from the resolved `data_dir`. Verify `NEXUS_DATA_DIR=/opt/nexus` moves all subpaths.

## Tier 3 — Functional bugs

12. **`memory/document_ingest.py`**: `elif ext in ".docx"` is a substring test. Change to `elif ext == ".docx":`. Add a `.md` branch (treat as plain text). Reject `.doc` with a clear error.

13. **`core/engine.py` `_handle_chat`**: Inject retrieved memory context before calling the LLM:
    ```python
    memory = self.memory.query(message)
    messages = [{"role": "system", "content": self._build_context(memory)},
                {"role": "user", "content": message}]
    response = self.llm.chat(messages)
    self.memory.add_chat_message("user", message)
    self.memory.add_chat_message("assistant", response)
    ```
    Honor the `role` param in `MemoryManager.add_chat_message`.

14. **`core/engine.py` `_handle_cloud_burst`**: Strip the `!ultra` prefix before forwarding.

15. **`skills/generator.py`**: Replace `raw[find:rfind]` JSON extraction with: try `json.loads(raw)`, then strip markdown fences and retry, then validate keys (`skill_name`, `description`, `python_code`). Run `validate_code` before registering; on failure, retry once. On duplicate name, auto-suffix or update.

16. **`ui/privacy_dashboard.py` `_update_usage_stats`**: Count by `action` column, not risk-level substring:
    ```python
    cloud_count = sum(1 for log in all_logs if log[1] == "cloud_request" and "denied" not in log[2])
    local_count = sum(1 for log in all_logs if log[1] != "cloud_request")
    ```

17. **`core/privacy_gate.py` `log_cloud_request`**: Swap risk levels — approved (data leaves device) = `"high"`, denied (local fallback) = `"low"`.

18. **`ui/privacy_dashboard.py` `_count_semantic_entries`**: Call `self.memory_manager.semantic.count()` instead of returning `0`.

19. **`skills/executor.py` `execute_python`**: Drop the bogus `update_last_run("generic", ...)` call. Accept an explicit `skill_name` argument or skip the update.

20. **`core/router.py`**: Tighten `SKILL_CREATION` regex to require explicit verbs:
    ```python
    re.search(r"\b(create|make|build|generate)\s+(a\s+)?skill\b", lower)
    ```
    Move "every day/week/schedule" to a separate `SCHEDULE_SKILL` intent requiring an existing skill name; otherwise fall back to CHAT.

21. **`memory/episodic.py`**: Escape `%` and `_` in `query` before `LIKE` matching. Better: migrate to SQLite FTS5.

22. **`memory/document_ingest.py` `_chunk_text`**: Add `if end <= start: end = start + self.chunk_size` guard against infinite loops. Compute `doc_id` from a content hash (not mtime) so re-ingesting an unchanged file is a no-op; on changed file, delete old chunks by metadata filter before inserting.

23. **`skills/registry.py` `register`**: Add `update_if_exists=False` param; when `True` and name exists, `UPDATE` instead of returning `False`.

## Tier 4 — Design / consistency

24. **Repo hygiene**: Delete all `__pycache__/` and `.pyc` files. Add `.gitignore` (`__pycache__/`, `*.pyc`, `.nexus/`, `*.gguf`, `*.db`, `chroma/`, `models/`). Delete empty placeholders (`Nexus/policy.py`, `Nexus/runner.py`, `Nexus/ui/widget.py`, `Nexus/testing.py`) and `Nexus_Devpost`.

25. **SQLite lifecycle**: Add `close()` + context-manager protocol to `AuditLogger`, `EpisodicMemory`, `SkillRegistry`. In `NexusEngine`, register `atexit` to close all three.

26. **Type hints**: `EpisodicMemory.__init__(db_path: str | Path)`; `Path()`-ify internally. Update `MemoryManager` to pass `Path` objects.

27. **`web/server.py` concurrency**: Switch to `ThreadingHTTPServer`. Move the engine onto a dedicated worker thread with a `queue.Queue`; SQLite/llama.cpp connections stay on that thread. `/api/status` must not block on LLM generation.

28. **`models/local_llm.py`**: Detect CUDA at runtime; fall back to `n_gpu_layers=0` on CPU-only boxes. Make stop tokens configurable via settings.

29. **`core/privacy_gate.py`**: Replace `len(str(messages))` with `tiktoken` count, or document `len(text) / 4` as approximation.

30. **`web/page.py`**: Map intent enums to friendly labels (`chat` → "", `memory_query` → "memory", `cloud_burst` → "cloud", `skill_exec` → "skill") before display.

31. **`__main__.py`**: Convert to subcommands (`setup`, `serve`, `ui`), add `--version`.

32. **`audit/logger.py`**: Populate `actor`/`ip_address` from request context (web) or drop the columns.

## Acceptance criteria

- All existing tests pass; add tests for: `NebiusClient.chat` method, sandbox deny-list (5 evil payloads rejected), web auth (401 without token on non-loopback), config path derivation under `NEXUS_DATA_DIR`, scheduler firing a cron job in a fast-tick test, episodic round-trip preserving `role`.
- Desktop UI stores both user and assistant turns; `MEMORY_QUERY` returns hits from past chats.
- `python -m Nexus serve --host 0.0.0.0` refuses to start without `--token`.
- No `__pycache__`/`.pyc` in the repo after the fix.

Work file-by-file, commit each tier separately, and post a short summary of what changed at each tier.
