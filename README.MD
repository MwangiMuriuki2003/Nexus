# Nexus â€” Private Desktop Brain

**Track:** Personal AI â€” Nebius Ã— NVIDIA Global AI Hackathon

An always-on, local-first personal AI assistant that keeps your data on your device. Chat, remember, automate, and reason â€” powered by **NVIDIA Nemotron** models, with optional cloud-burst reasoning via **Nebius Token Factory** only when you explicitly approve it.

---

## Features

- **Private by Default** â€” All data lives in `~/.nexus/`. No cloud calls without your approval.
- **Persistent Memory** â€” Episodic timeline (what you did when) + semantic search (what you know).
- **Skill Forge** â€” Describe a task in plain English; Nexus generates a sandboxed Python skill you can approve and schedule.
- **Smart Offload** â€” Complex reasoning? A privacy gate asks before sending anything to Nebius Token Factory.
- **Bring Your Own Key** â€” Paste your own OpenAI-compatible API key in *Settings* (desktop: **Edit â†’ Settings**; web: the **Settings** button) and point Nexus at any compatible endpoint. The key lives in the OS keyring and is only ever sent when you approve a cloud request.
- **Offline Capable** â€” Core chat, memory, and skill execution work without internet.

---

## Architecture

```
PyQt6 UI  â†’  Intent Router  â†’  Local LLM (Nemotron Nano 4B)
                   â”‚                â”‚
                   â”œâ”€â”€ Memory Manager (SQLite + ChromaDB)
                   â”œâ”€â”€ Skill Registry (SQLite + Sandbox)
                   â””â”€â”€ Privacy Gate â†’ Nebius Token Factory (Nemotron Ultra)
```

---

## Quick Start

### Requirements
- Python 3.11+
- 8 GB RAM (16 GB recommended)
- 6 GB VRAM optional for GPU acceleration; CPU works fine

### Install
```bash
git clone https://github.com/yourname/nexus.git
cd nexus
./run.sh setup   # activates the env, installs if needed, initializes ~/.nexus
```

### First Run
```bash
./run.sh   # launches the desktop app
```

`./run.sh` activates the conda env, sets the pip flags this machine needs, installs the
package on first use, then hands every argument to `python -m Nexus`. See
[RUN.md](./RUN.md) for the manual steps and the model download.

### Headless (Web UI)
```bash
./run.sh --headless                       # http://localhost:8080
./run.sh --headless --host 0.0.0.0 --port 8080   # reachable from outside a container
```

A single-page chat UI is served at `/`, backed by the same engine as the desktop app
(`POST /api/chat`, plus `/api/status`, `/api/skills`, `/api/audit`, `/api/settings`). The
**Settings** panel on that page is where you add your own API key when running headless. No Dockerfile is
shipped in this repo; the command above is what such an image would run.

---

## Usage

| Action | How |
|---|---|
| Chat | Type in the main panel. Responses use your local model. |
| Search memory | *"What did I copy yesterday?"* |
| Create a skill | *"Every Friday, zip my Downloads folder"* â†’ review code â†’ approve |
| Cloud burst | Prefix with `!ultra` or approve the privacy gate modal for deep reasoning. |
| Check privacy | Open the **Privacy Dashboard** to view local vs. cloud usage and audit logs. |

---

## Nebius & NVIDIA Integration

| Technology | Where It Lives | Purpose |
|---|---|---|
| **Nebius Token Factory** | `nexus/models/nebius_client.py` | Secure, approved cloud bursts to Nemotron 3 Ultra for heavy reasoning |
| **NVIDIA Nemotron Nano 4B** | `nexus/models/local_llm.py` | Fast, private, local chat and skill generation |
| **NVIDIA Nemotron 3 Ultra** | Via Nebius Token Factory | Advanced coding, long-context analysis, complex reasoning |
| **NVIDIA NemoClaw** | Architecture reference | Agent loop design (memory â†’ tools â†’ LLM) |
| **NVIDIA OpenShell** | Design influence | Sandboxed skill execution policy |

---

## Project Structure

```
nexus/
â”œâ”€â”€ __main__.py          # CLI entry point
â”œâ”€â”€ config.py            # Paths and settings
â”œâ”€â”€ ui/                  # PyQt6 interface
â”œâ”€â”€ core/                # Engine and intent router
â”œâ”€â”€ memory/              # Episodic (SQLite) + semantic (ChromaDB)
â”œâ”€â”€ models/              # Local LLM + Nebius client
â”œâ”€â”€ skills/              # Skill generator and registry
â”œâ”€â”€ sandbox/             # AST policy + safe runner
â””â”€â”€ audit/               # Append-only audit logger
```

---

## Security

- **Sandboxed Execution:** Generated skills pass AST validation and run in a restricted subprocess.
- **Import Whitelist:** Only standard-library modules are allowed inside skills.
- **No Silent Cloud Calls:** Every Nebius request requires explicit UI approval.
- **OS Keyring:** Your API key is stored in the platform-native credential store (macOS Keychain, Windows Credential Locker, Linux Secret Service), falling back to a `0600` file under `~/.nexus/` on machines without one. It is never returned by the API and never logged.
- **Optional Encryption:** Enable at-rest encryption for `~/.nexus/` via the setup wizard.

Read the full security model in [04-Security-Practices.md](./04-Security-Practices.md).

---

## Demo Video

Watch the 3-minute walkthrough: [YouTube link placeholder]

---

## License

Apache 2.0 â€” see [LICENSE](./LICENSE).

---

## Feedback

Our experience using Nebius and NVIDIA tools is documented in [FEEDBACK.md](./FEEDBACK.md).