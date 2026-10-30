# Nexus

Private Desktop Brain

Nexus is a privacy-first local AI assistant designed for desktop and headless environments. It keeps personal data on-device by default, remembers important context, and supports optional cloud reasoning only when the user explicitly approves it. Built around a local model workflow, Nexus helps users chat, search memory, and automate routine work without compromising privacy.

## About

Nexus was created for people who want an AI assistant that feels personal, useful, and trustworthy. Rather than depending entirely on cloud services, Nexus emphasizes local-first intelligence: conversations, memories, and generated automation remain under the user’s control.

The project combines:

- a local language model for private, responsive everyday interaction
- persistent episodic and semantic memory
- sandboxed skill generation and execution
- privacy-aware routing for cloud inference
- both desktop and web-based interfaces

This makes Nexus suitable for knowledge workers, developers, and privacy-conscious users who want an AI companion that can reason locally while still offering optional cloud bursts when necessary.

## Why Nexus?

- Privacy by default: local data storage and explicit approval before cloud access
- Persistent memory: remembers events, context, and useful information over time
- Safe automation: generate and review Python skills in a sandboxed environment
- Flexible access: works in desktop mode and headless web mode
- Offline capable: core workflows remain usable without internet connectivity

## Key Features

- Local-first AI chat with NVIDIA Nemotron-based inference
- Privacy gate that requires approval before sending requests to external services
- Episodic memory for tracking past user activity and context
- Semantic memory search for retrieving relevant information and documents
- Skill Forge to generate and review automation scripts in plain English
- Sandboxed execution with restrictive import and filesystem controls
- Desktop UI with PyQt6 and a lightweight web interface for headless deployment

## Architecture

Nexus follows a modular architecture that separates intent handling, memory, model access, and safe execution:

```text
User Interface
      │
      ▼
Intent Router
      │
      ├── Local LLM (NVIDIA Nemotron Nano)
      │
      ├── Memory Layer (SQLite + ChromaDB)
      │
      ├── Skill Registry + Sandbox
      │
      └── Privacy Gate
              │
              └── Optional cloud burst via Nebius / compatible API providers
```

This layered design allows the application to preserve local context, enforce privacy boundaries, and decide when external reasoning is appropriate.

## Quick Start

### Requirements

- Python 3.11+
- Conda environment recommended (`ml-lab` in the project instructions)
- Local model file for inference
- Optional GPU acceleration, though CPU mode is supported

### 1. Clone the repository

```bash
git clone https://github.com/MwangiMuriuki2003/Nexus.git
cd Nexus
```

### 2. Activate the environment

```bash
conda activate ml-lab
python --version
```

### 3. Install dependencies

```bash
export PIP_REQUIRE_VIRTUALENV=0
python -m pip install -e .
```

### 4. Download the local model

The project expects a local GGUF model in the Nexus data directory. The recommended workflow is:

```bash
mkdir -p ~/.nexus/models
huggingface-cli download nvidia/Llama-3.1-Nemotron-Nano-4B-v1 \
  Llama-3.1-Nemotron-Nano-4B-v1-Q4_K_M.gguf --local-dir ~/.nexus/models
```

### 5. Initialize the app

```bash
python -m Nexus setup
```

### 6. Run Nexus

Desktop mode:

```bash
python -m Nexus
```

Headless web mode:

```bash
python -m Nexus --headless
```

Or use the convenience launcher:

```bash
./run.sh
./run.sh --headless
```

For detailed environment setup, troubleshooting, and model configuration, see [RUN.md](./RUN.md).

## Project Structure

```text
Nexus/
├── Nexus/                  # Core package
│   ├── __main__.py         # CLI entry point
│   ├── config.py          # App configuration and paths
│   ├── core/              # Engine and routing logic
│   ├── memory/            # SQLite + semantic memory
│   ├── models/            # Local LLM and API integrations
│   ├── skills/            # Skill generation and registry
│   ├── sandbox/           # Safe execution and validation
│   ├── ui/                # PyQt6 user interface
│   └── web/               # Headless web interface
├── tests/                 # Automated test suite
├── documents/             # Project documentation
├── PRD.md                 # Product requirements document
├── RUN.md                 # Setup and execution guide
├── pyproject.toml         # Packaging and dependency configuration
├── run.sh                 # One-command launcher
├── test_nexus_run.py      # Run verification script
└── README.MD              # Project overview
```

## How Nexus Works

Nexus is designed around a simple but powerful workflow:

1. The user interacts with the desktop or web interface.
2. The intent router classifies the request.
3. Relevant context is retrieved from local memory.
4. The local model responds or plans an action.
5. If the task requires deeper reasoning or external processing, the privacy gate prompts for approval.
6. Approved actions may trigger cloud inference while keeping the system transparent and auditable.

## Security and Privacy

Security is one of the foundational principles of Nexus.

- Local-first data storage keeps user information on-device by default
- Cloud access is gated behind explicit user approval
- Generated automation runs inside a restricted sandbox
- Import and filesystem access are tightly controlled
- Privacy dashboard and audit logs help users understand what was processed locally versus remotely

These safeguards are designed to make the platform more suitable for sensitive work and private knowledge management.

## Development and Testing

The project includes a test suite for core behavior, memory management, skill execution, and web interactions.

Run the tests with:

```bash
python -m pytest tests/ -q
```

## Documentation

The repository includes supporting documentation for setup and product direction:

- [RUN.md](./RUN.md) — local setup, installation, run instructions, and troubleshooting
- [PRD.md](./PRD.md) — product goals and functional requirements
- [documents/](./documents) — additional project planning materials

## Future Direction

Nexus is positioned as a practical local AI agent for everyday work: personal assistance, memory-aware reasoning, safe automation, and transparent privacy controls. The project continues to evolve toward a more complete personal AI workflow while keeping the user in control of their data.

## Summary

Nexus bridges the gap between private local intelligence and practical AI assistance. It combines memory, automation, privacy safeguards, and flexible deployment into a single platform built for users who care about control, trust, and usefulness.

For installation guidance and hands-on execution notes, start with [RUN.md](./RUN.md).
