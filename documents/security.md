# Nexus â€” Security & Privacy Practices
**Version:** 1.0  
**Date:** 2026-10-22  
**Classification:** Local-First / Zero-Trust Cloud Burst

---

## 1. Threat Model

| Threat Actor | Capability | Impact |
|---|---|---|
| Malicious Skill Code | User accidentally approves generated script | Unauthorized file deletion or data exfiltration |
| Prompt Injection | Untrusted document contains instructions | Manipulation of agent behavior or memory |
| Cloud API Key Theft | Malware on host accesses memory | Unauthorized inference charges |
| Local Eavesdropper | Another user on shared machine | Reads memory database files |
| Supply Chain | Compromised PyPI dependency | System-wide compromise |

---

## 2. Data Classification

| Class | Examples | Storage | Encryption |
|---|---|---|---|
| Public | Chat UI strings, skill descriptions | Memory (optional) | None |
| Sensitive | Clipboard history, file paths, chat content | Local SQLite / ChromaDB | Optional at-rest |
| Secret | Nebius API key, encryption passphrase | OS keyring | OS-provided |

---

## 3. Access Controls

### 3.1 Filesystem Isolation
- All application data is confined to `~/.nexus/`.
- Sandbox execution uses a dedicated `~/.nexus/sandbox/` directory; scripts cannot traverse above it via `pathlib` or `os.path` checks enforced at runtime.
- Skill runner validates all file writes are within the sandbox or explicitly user-permitted directories.

### 3.2 Import Sandboxing
- AST traversal (`sandbox/policy.py`) enforces an explicit **ALLOWLIST**.
- Any import not in `ALLOWED_IMPORTS` rejects the skill before execution.
- Banned builtins: `eval`, `exec`, `compile`, `__import__`, `open`.
- Banned modules: `socket`, `urllib`, `http.client`, `requests`, `subprocess`, `ctypes`, `multiprocessing`.

### 3.3 Network Sandboxing
- Generated skills run in a subprocess with no network namespace isolation (MVP limitation), but network-capable imports are blocked at the AST level.
- Future: consider `firejail` or `bubblewrap` for true network isolation on Linux.

---

## 4. Cryptography

### 4.1 API Key Storage
- Nebius Token Factory keys are stored using the OS-native keyring (macOS Keychain, Windows Credential Locker, Linux Secret Service).
- Key is never written to `.env`, `config.json`, or logs.

### 4.2 At-Rest Encryption (Optional)
- If enabled, `~/.nexus/episodic.db`, `chroma/`, and `skills.db` are encrypted using `cryptography.fernet`.
- Encryption key is derived from a user passphrase via PBKDF2 and stored in the OS keyring.
- Without the passphrase, raw database files are unreadable.

---

## 5. Audit & Non-Repudiation

### 5.1 Audit Log Schema (`audit.db`)
```sql
CREATE TABLE audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT DEFAULT (datetime('now')),
    action TEXT CHECK(action IN (
        'local_inference', 'cloud_request', 'skill_exec',
        'memory_access', 'data_export', 'setting_change'
    )),
    actor TEXT DEFAULT 'user',
    detail TEXT,
    risk_level TEXT CHECK(risk_level IN ('low', 'medium', 'high')),
    ip_address TEXT DEFAULT '127.0.0.1'
);
```
- Append-only table. No application API exposes `DELETE` or `UPDATE`.
- WAL mode enabled for crash safety.

### 5.2 What We Log
- Every local inference (model name, token count).
- Every cloud request (reason, tokens sent, latency, model name).
- Every skill execution (skill name, exit code, runtime).
- Every memory access query (top-k topics retrieved, not full content).

---

## 6. Privacy Gate Protocol

1. **Default Deny:** All requests route to the local model.
2. **Explicit Consent:** Any Nebius call requires a UI modal with:
   - Estimated token count
   - Reason for offload (e.g., "Complex reasoning detected")
   - Model name
3. **Scope Limiting:** User may approve **Once**, **Session**, or **Cancel**.
4. **No Silent Fallback:** If the user denies, the request is either handled locally with a capability disclaimer or rejected gracefully.

---

## 7. Dependency Security

- Pin all dependencies in `pyproject.toml` with minimum versions.
- Avoid packages with known CVEs; use `pip-audit` before release.
- Prefer pure-Python or well-audited C extensions over niche wrappers.

---

## 8. Incident Response (User-Facing)

| Incident | Response |
|---|---|
| Skill behaves unexpectedly | User deletes skill from Skill Library; audit log retains trace. |
| Suspicious cloud usage | Dashboard shows all requests with timestamps; user can revoke key. |
| Lost encryption passphrase | Data is unrecoverable by design. No backdoor. |
| Clipboard captures password | User disables Clipboard Memory; clear existing clips. |

---

## 9. Compliance Notes
- GDPR / CCPA aligned: data never leaves device without consent; user can export and delete all stored data.
- No telemetry or crash reporting to external servers in MVP.
- Future versions may offer opt-in anonymous metrics.