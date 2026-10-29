# Nexus â€” Technology Stack Specification
**Version:** 1.0  
**Date:** 2026-10-22

---

## 1. Runtime & Language

| Component | Technology | Version | Rationale |
|---|---|---|---|
| Language | Python | 3.11+ | Native ecosystem for ML; hackathon judges can run it easily |
| Package Manager | pip / setuptools | Latest | Universal compatibility; no conda lock-in |
| Virtual Env | venv | Built-in | Isolation without extra tooling |

---

## 2. User Interface

| Component | Technology | Role |
|---|---|---|
| Desktop UI | PyQt6 | Primary cross-platform GUI (Windows, macOS, Linux) |
| Web UI (Headless) | FastAPI + Jinja2 | Fallback when PyQt6 is unavailable; mobile viewport |
| Threading | QThread (PyQt), asyncio (web) | Non-blocking inference and I/O |

---

## 3. AI / ML Layer

| Component | Technology | Role |
|---|---|---|
| Local LLM Engine | `llama-cpp-python` | Loads Nemotron Nano 4B GGUF; supports CPU and CUDA |
| Cloud LLM Client | `openai` (OpenAI-compatible) | Talks to Nebius Token Factory endpoints |
| Embeddings | `sentence-transformers` | `all-MiniLM-L6-v2` for local semantic search (~80 MB) |
| Prompt Management | Python f-strings + Jinja2 | Structured generation templates for skills |

### Model Inventory

| Model | Source | Quantization | Use Case |
|---|---|---|---|
| NVIDIA Nemotron Nano 4B | Hugging Face (GGUF) | Q4_K_M (2.5 GB) | Default chat, memory synthesis, skill generation |
| NVIDIA Nemotron 3 Ultra | Nebius Token Factory | BF16 (cloud) | Complex reasoning, advanced coding, long-context analysis |

---

## 4. Data & Storage

| Component | Technology | Role |
|---|---|---|
| Episodic Store | SQLite3 | Timeline of user events, chat history, audit logs |
| Semantic Store | ChromaDB (persistent client) | Vector search over documents and chat embeddings |
| Skill Registry | SQLite3 | Metadata and scheduling config for user skills |
| File Storage | Python `pathlib` | Organizes `~/.nexus/models/`, `skills/`, `sandbox/` |

---

## 5. Agent & Workflow

| Component | Technology | Role |
|---|---|---|
| Orchestration | Pure Python (`core/engine.py`) | Main event loop; routes intent to handler |
| Intent Routing | Rule-based + LLM classifier | Fast path for chat; LLM path for ambiguous queries |
| Scheduling | APScheduler | Runs approved skills on cron or interval triggers |
| Sandbox | `ast` module + `subprocess` | Validates and executes generated Python safely |

---

## 6. Security & Privacy

| Component | Technology | Role |
|---|---|---|
| Key Storage | `keyring` | OS-native secure storage for Nebius API key |
| At-Rest Encryption | `cryptography` (Fernet) | Optional AES-128 encryption for user data directory |
| AST Validation | Python `ast` | Static analysis of generated skills before execution |
| Audit Logging | SQLite (append-only) | Immutable record of agent actions |

---

## 7. Utilities

| Component | Technology | Role |
|---|---|---|
| HTTP Client | `httpx` | Async API calls to Nebius Token Factory |
| Configuration | `pydantic-settings` | Type-safe config with environment variable fallback |
| Document Parsing | `pymupdf`, `markdown`, `unstructured` | Extract text from PDFs and markdown uploads |
| Packaging | PyInstaller (optional), Docker | One-file executable or containerized headless mode |

---

## 8. Development & Testing

| Component | Technology | Role |
|---|---|---|
| Testing | `pytest` | Unit tests for sandbox, memory, and routing layers |
| Linting | `ruff` / `black` | Code quality |
| Type Checking | `mypy` | Static type safety |

---

## 9. Deployment Targets

| Target | Method | Notes |
|---|---|---|
| Local Developer | `pip install -e .` | Editable install, auto-reload |
| End User Desktop | `pip install nexus-desktop` | Standard PyPI distribution |
| Docker (Judges) | `docker run -p 8080:8080 nexus` | Headless mode with web UI |
| CI/CD | GitHub Actions | Runs pytest on Python 3.11, 3.12 |

---

## 10. Nebius & NVIDIA Integration Summary

| Platform / Tool | Where It Appears in Code |
|---|---|
| **Nebius Token Factory** | `nexus/models/nebius_client.py` â€” cloud LLM burst endpoint |
| **NVIDIA Nemotron Nano 4B** | `nexus/models/local_llm.py` â€” local GGUF inference |
| **NVIDIA Nemotron 3 Ultra** | Routed via Nebius Token Factory for heavy reasoning |
| **NVIDIA NemoClaw** | Architectural reference for agent loop (memory + tool + LLM) |
| **NVIDIA OpenShell** | Design inspiration for sandboxed skill execution policy |

---

## 11. Constraints & Trade-offs

- **PyQt6 vs. Tauri / Electron:** PyQt6 is heavier than web wrappers but gives native Python event loops and avoids Node.js complexity.
- **ChromaDB vs. pgvector / Qdrant:** ChromaDB is chosen for zero-config local persistence; no Docker or external services needed.
- **SQLite vs. PostgreSQL:** SQLite keeps the stack fully serverless and embedded.
- **llama-cpp vs. vLLM / Ollama:** llama-cpp offers the simplest pip-installable Python binding with GGUF support; Ollama requires a separate daemon.