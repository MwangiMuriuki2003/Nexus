# Nexus Knowledge Graph

## Overview

This knowledge graph illustrates the entities, data stores, and relationships within the Nexus local-first personal AI assistant system.

```mermaid
graph TD
    %% User & Interface
    User[User] -->|Chats with| Chat[Chat Interface]
    User -->|Generates| SkillRequests[Skill Requests]
    User -->|Approves/Rejects| PrivacyGate[Privacy Gate]
    User -->|Sets Permissions| DataPermissions[Data Permissions]

    %% Core Processing
    Chat -->|Messages| Router[Intent Router]
    Router -->|Routes to| MemoryManager[Memory Manager]
    Router -->|Routes to| SkillForge[Skill Forge]
    Router -->|Routes to| CloudBurst[Cloud Burst]

    %% Memory Systems
    MemoryManager -->|Queries| EpisodicMemory[Episodic Memory]
    MemoryManager -->|Queries| SemanticMemory[Semantic Memory]
    EpisodicMemory -->|Stores| Timeline[User Timeline Events]
    SemanticMemory -->|Contains| Embeddings[Vector Embeddings]
    Embeddings -->|Derived from| Documents[Uploaded Documents]
    Embeddings -->|Derived from| ChatHistory[Chat History]

    %% Skill System
    SkillForge -->|Generates| SkillCode[Python Skill Code]
    SkillCode -->|Validated by| ASTValidator[AST Sanitizer]
    ASTValidator -->|Approved| SkillRegistry[Skill Registry]
    SkillRegistry -->|Executes| SkillExecutor[Skill Executor]
    SkillExecutor -->|Runs in| Sandbox[Sandbox Environment]

    %% LLM Processing
    LocalLLM[Local LLM: Nemotron Nano 4B] -->|Local Inference| Chat
    CloudLLM[Cloud LLM: Nebius/Nemotron 3 Ultra] -->|Cloud Requests| PrivacyGate
    PrivacyGate -->|Approved Requests| CloudLLM
    PrivacyGate -->|Denied Requests| LocalLLM

    %% Data Flow
    Documents -->|Text Extraction| Chunker[Text Chunker]
    Chunker -->|Chunks| Embedder[Embedder: all-MiniLM-L6-v2]
    Embedder -->|Vector Embeddings| SemanticMemory

    %% Audit & Logging
    PrivacyGate -->|Logs to| AuditLog[Audit Log]
    SkillExecutor -->|Logs to| AuditLog
    MemoryManager -->|Logs to| AuditLog

    %% Styling
    classDef user fill:#e3f2fd,stroke:#1976d2,stroke-width:2px;
    classDef local fill:#c8e6c9,stroke:#388e3c,stroke-width:2px;
    classDef cloud fill:#ffcc80,rgba(255,152,0,0.3),stroke:#f57c00,stroke-width:2px;
    classDef storage fill:#ffe0b2,orange,stroke:#e65100,stroke-width:2px;
    classDef processor fill:#e1f5fe,01579b,stroke-width:2px;

    class User user;
    class ChatInterface,LocalLLM local;
    class CloudLLM,PrivacyGate cloud;
    class EpisodicMemory,SemanticMemory,SkillRegistry,Storage,AuditLog storage;
    class Router,MemoryManager,SkillForge,ASTValidator,Embedder,Chunker processor;
```

## Entity Details

| Entity | Technology | Description |
|--------|-----------|-------------|
| **User** | Human | The person interacting with Nexus |
| **Chat Interface** | PyQt6 | Frontend for conversation |
| **Intent Router** | Python `core/router.py` | Classifies user intent (chat, memory, skill, cloud) |
| **Memory Manager** | Python `core/engine.py` | Coordinates episodic + semantic retrieval |
| **Episodic Memory** | SQLite `~/.nexus/episodic.db` | Timeline of user events (chat, clipboard, files) |
| **Semantic Memory** | ChromaDB `~/.nexus/chroma/` | Vector search over embeddings |
| **Local LLM** | `llama-cpp-python` | Nemotron Nano 4B GGUF, runs on CPU/CUDA |
| **Cloud LLM** | OpenAI-compatible | Nemotron 3 Ultra via Nebius Token Factory |
| **Privacy Gate** | `core/privacy_gate.py` | Requires explicit user consent for cloud calls |
| **Skill Forge** | `skills/generator.py` | Generates Python scripts from natural language |
| **AST Sanitizer** | `sandbox/policy.py` | Validates skill imports and builtins |
| **Skill Registry** | SQLite `~/.nexus/skills.db` | Metadata for registered skills |
| **Skill Executor** | `skills/executor.py` | Runs approved skills in sandbox |
| **Sandbox** | `~/.nexus/sandbox/` | Isolated workspace for skill execution |
| **Embedder** | `sentence-transformers` | all-MiniLM-L6-v2 for embeddings |
| **Text Chunker** | Custom | 512 tokens with 64-token overlap |
| **Uploaded Documents** | PDF, TXT, MD | Parsed and indexed for semantic search |
| **Audit Log** | SQLite `~/.nexus/audit.db` | Immutable record of all actions |
| **Data Permissions** | Settings UI | Per-source toggles (clipboard, files, etc.) |

## Relationship Highlights

- **User ↔ Privacy Gate**: All cloud requests require explicit user approval
- **Memory Manager ↔ Both Memory Stores**: Semantic search + episodic filtering for queries
- **Skill Forge → AST Sanitizer → Skill Registry**: Safety pipeline before skill execution
- **Privacy Gate → Cloud LLM**: Conditional offload based on user consent
- **Embedder → Semantic Memory**: All documents and chat become searchable vectors
- **Audit Log**: Append-only record spanning all system actions

## Usage

This graph can be rendered with Mermaid.js in compatible documentation viewers. It reflects the architecture described in the Data-Flow, User-Flow, security, and tech-stack documents, as well as the actual code implementation in the Nexus repository.