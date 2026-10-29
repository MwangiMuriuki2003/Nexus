# Nexus â€” Private Desktop Brain
## Product Requirements Document (PRD)
**Version:** 1.0  
**Date:** 2026-10-22  
**Track:** Personal AI â€” Nebius Ã— NVIDIA Global AI Hackathon

---

## 1. Overview
Nexus is an always-on, local-first personal AI assistant for desktop operating systems. It runs entirely on the userâ€™s machine by default, keeps all data local, and provides optional cloud-burst reasoning via Nebius Token Factory only after explicit user approval.

---

## 2. Goals
- Provide a privacy-first alternative to cloud-only assistants.
- Maintain persistent episodic and semantic memory that the user fully owns.
- Generate and execute reusable automation "skills" sandboxed on-device.
- Demonstrate practical use of NVIDIA Nemotron models (local Nano + cloud Ultra via Nebius).

---

## 3. Non-Goals
- Multi-user collaboration or server-side orchestration.
- Replacing full IDE functionality (this is an assistant, not an IDE).
- Automatic cloud fallback without explicit user consent.
- Mobile-native deployment (mobile access is via local web UI only).

---

## 4. Target Users
- Privacy-conscious knowledge workers.
- Developers who want an assistant that can write small scripts without leaking source code.
- Researchers managing local document corpora.

---

## 5. Functional Requirements

| ID | Requirement | Priority |
|---|---|---|
| FR-01 | Local chat interface using NVIDIA Nemotron Nano 4B | P0 |
| FR-02 | Episodic memory timeline (clipboard, file access, chat history) with user opt-in per source | P0 |
| FR-03 | Semantic memory search over uploaded documents and chat history via local embeddings | P0 |
| FR-04 | Privacy Gate requiring explicit UI approval before any cloud API call to Nebius Token Factory | P0 |
| FR-05 | Skill Forge: generate Python automation scripts from natural language, with AST validation | P1 |
| FR-06 | Sandboxed skill execution with filesystem and import restrictions | P1 |
| FR-07 | Skill scheduling via APScheduler (triggered workflows) | P1 |
| FR-08 | Privacy Dashboard displaying local vs. cloud usage, data sources, and audit log | P1 |
| FR-09 | Optional at-rest encryption for the `~/.nexus/` data directory | P2 |
| FR-10 | Headless mode with local web UI for Docker / remote testing | P2 |

---

## 6. Non-Functional Requirements

| ID | Requirement | Target |
|---|---|---|
| NFR-01 | Local inference latency (Nano 4B) | < 2s for 256-token outputs on GPU; < 5s on CPU |
| NFR-02 | Memory search latency | < 500ms for top-5 semantic results |
| NFR-03 | Disk footprint (base + model) | < 4 GB installed |
| NFR-04 | RAM usage at idle | < 800 MB |
| NFR-05 | CI / reproducible install | `pip install -e .` succeeds on Python 3.11+ within 3 minutes |
| NFR-06 | Offline capability | Core chat, memory, and skill execution work without internet |

---

## 7. Milestones

| Phase | Deliverable | Criteria |
|---|---|---|
| MVP | Chat + Episodic Memory + Privacy Gate | User can chat locally, query past activity, and approve cloud bursts |
| v1.0 | + Skill Forge + Sandbox + Dashboard | User can create, approve, and run automation skills |
| Final | + Semantic Uploads + Docker Headless + Polish | Judges can install via pip or Docker; video demonstrates all tracks |

---

## 8. Success Criteria for Hackathon
- Repository includes Apache 2.0 license and working README.
- Demo video shows local inference, memory query, skill creation, and a cloud-burst request.
- Feedback on Nebius Token Factory and NVIDIA models is documented in `FEEDBACK.md`.