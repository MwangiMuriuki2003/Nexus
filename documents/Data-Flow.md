# Nexus â€” Data Flow Architecture
**Version:** 1.0  
**Date:** 2026-10-22

---

## 1. System Boundaries
Nexus maintains a strict boundary between the **Local Enclave** (user device) and the **Nebius Cloud** (Token Factory). Data crosses this boundary only through the Privacy Gate and only with explicit user approval.

---

## 2. Data Sources

| Source | Data Type | Local | Cloud |
|---|---|---|---|
| Chat Input | Plain text | âœ“ | Only if approved |
| Clipboard | Text / URLs | âœ“ (opt-in) | Never |
| File System | Path, content hash | âœ“ (opt-in) | Never |
| Uploaded Documents | PDF, TXT, MD | âœ“ | Never |
| Generated Skills | Python source code | âœ“ | Never |
| Audit Logs | Timestamps, actions | âœ“ | Never |

---

## 3. Ingestion Pipeline

```
User Input / File Drop / Clipboard Change
        â†“
  [Source Permission Check]
        â†“
  Episodic Store (SQLite timeline)
        â†“
  If document â†’ Text Extractor â†’ Chunker
        â†“
  Embedder (all-MiniLM-L6-v2) â†’ ChromaDB
```

- **Clipboard:** Monitored via platform hooks (pynput / pyperclip), written only if user enabled "Clipboard Memory" in settings.
- **Documents:** Parsed with `pymupdf` or `unstructured`, chunked by 512 tokens with 64-token overlap, embedded locally.
- **Chat:** Every turn is written to the timeline and embedded for future semantic retrieval.

---

## 4. Processing Flows

### 4.1 Chat Response (Local Default)
```
User Message
   â†“
Intent Router
   â†“
Memory Manager (retrieves top-k semantic + recent episodic context)
   â†“
System Prompt + Context + User Message
   â†“
Local LLM (llama-cpp Nemotron Nano 4B)
   â†“
Assistant Message â†’ UI + Episodic Store
```

### 4.2 Memory Query
```
"What did I copy yesterday?"
   â†“
Embed query locally â†’ Semantic Search (ChromaDB)
   â†“
Episodic filter: `timestamp >= yesterday`
   â†“
Local LLM synthesizes answer from retrieved chunks
```

### 4.3 Skill Generation
```
User Request: "Archive old logs every Friday"
   â†“
Router â†’ Skill Generator
   â†“
Prompt Local LLM with structured template
   â†“
Receive JSON: {name, description, python_code}
   â†“
AST Validator (`sandbox/policy.py`)
   â†“
UI Preview â†’ User Approval
   â†“
Save to `~/.nexus/skills/` + Register in SQLite
```

### 4.4 Cloud Burst (Controlled Offload)
```
User Request or Router detects heavy reasoning need
   â†“
Privacy Gate intercepts
   â†“
UI Modal: "Send to Nebius Token Factory?"
   â†“
If Approved:
   - Encrypt API key from OS keyring
   - Send request to Nebius (Nemotron 3 Ultra)
   - Log token count, latency, and reason to Audit DB
   â†“
Response returns through same pipeline
```

---

## 5. Storage Layers

| Layer | Technology | Path | Retention |
|---|---|---|---|
| Episodic Memory | SQLite | `~/.nexus/episodic.db` | Until user deletes |
| Semantic Memory | ChromaDB (persistent) | `~/.nexus/chroma/` | Until user deletes |
| Skill Registry | SQLite | `~/.nexus/skills.db` | Until user deletes |
| Audit Log | SQLite (append-only) | `~/.nexus/audit.db` | Immutable |
| Sandbox Workspace | Filesystem | `~/.nexus/sandbox/` | Cleared after each run |
| Model Weights | GGUF file | `~/.nexus/models/` | Manual |

---

## 6. Retrieval Paths

1. **Semantic Retrieval:** Query embedding â†’ ChromaDB cosine similarity â†’ top-k chunks.
2. **Episodic Retrieval:** SQL `SELECT` with `timestamp`, `source`, or `content LIKE` filters.
3. **Skill Retrieval:** SQL `SELECT` from registry by name, tag, or trigger phrase.
4. **Audit Retrieval:** Read-only SQL view for Privacy Dashboard.

---

## 7. Data Lifecycle
- **Creation:** All data originates from user action or local inference.
- **Transformation:** Documents are chunked and embedded; chat context is summarized when exceeding token limits.
- **Archival:** Not implemented in MVP; future versions may compress old episodic records.
- **Destruction:** User-triggered "Clear Memory" wipes SQLite + ChromaDB. Uninstall removes `~/.nexus/`.