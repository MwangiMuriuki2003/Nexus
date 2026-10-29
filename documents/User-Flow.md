# Nexus â€” User Flow & Interaction Design
**Version:** 1.0  
**Date:** 2026-10-22

---

## 1. Onboarding Wizard (First Launch)

### Step 1: Welcome
- One-sentence value prop: "Your data stays on your device. Always."

### Step 2: Data Directory
- Default: `~/.nexus/`
- User can override (e.g., external encrypted drive).

### Step 3: Model Download
- Auto-download Nemotron Nano 4B GGUF (Q4_K_M) from Hugging Face.
- Progress bar with cancel option.
- Fallback notice: "CPU mode will be slower but fully functional."

### Step 4: Privacy Permissions
- Toggle per source:
  - [ ] Clipboard Memory
  - [ ] File Access History
  - [ ] App Usage Timeline
- Default: all OFF. App works regardless.

### Step 5: Optional Cloud Setup
- Input field for Nebius Token Factory API key.
- Stored in OS keyring (`keyring` library).
- Explainer: "Only used when you explicitly approve a cloud request."

### Step 6: Finish
- Prompt: "Ask me anything about your system or documents."

---

## 2. Core Interaction Loop

```
â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”
â”‚  Nexus Main Window                      â”‚
â”‚  â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â” â”Œâ”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”  â”‚
â”‚  â”‚ Timeline â”‚ â”‚ Chat Panel          â”‚  â”‚
â”‚  â”‚ (past    â”‚ â”‚                     â”‚  â”‚
â”‚  â”‚ events)  â”‚ â”‚ [User Message]      â”‚  â”‚
â”‚  â”‚          â”‚ â”‚ [Assistant Response]â”‚  â”‚
â”‚  â”‚          â”‚ â”‚                     â”‚  â”‚
â”‚  â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜ â”‚ [Input Field      ] â”‚  â”‚
â”‚               â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜  â”‚
â”‚  Tabs: [Chat] [Skills] [Privacy]        â”‚
â””â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”€â”˜
```

- **Left Panel:** Scrollable timeline of episodic events (clipboard, files, chat). Clicking an item inserts a summary into the chat context.
- **Right Panel:** Chat interface. Messages show a lock icon (local) or cloud icon (Nebius).
- **Input:** Plain text with `/skill` and `/memory` slash commands.

---

## 3. Memory Query Flow

| Step | System Action | User Perception |
|---|---|---|
| 1 | User types: "What was that article I copied about transformers?" | Normal chat input |
| 2 | Router classifies `memory_query` | Slight loading spinner |
| 3 | Semantic search + episodic filter execute | "Searching memory..." |
| 4 | Local LLM synthesizes answer | Response with citations to timeline entries |
| 5 | User can click citation | Timeline scrolls to exact event |

---

## 4. Skill Creation Flow

| Step | System Action | User Perception |
|---|---|---|
| 1 | User types: "Every Friday, archive my Downloads folder" | Chat input |
| 2 | Router classifies `skill_creation` | "Generating skill..." |
| 3 | Local LLM returns Python code | UI switches to Skill Preview modal |
| 4 | AST validator runs | If unsafe, red banner; if safe, green banner |
| 5 | User reviews code | Syntax-highlighted Python with line numbers |
| 6 | User clicks **Approve & Install** | Skill added to Skill Library tab |
| 7 | User sets schedule or keeps manual trigger | Confirmation toast |

---

## 5. Cloud Burst Flow

| Step | System Action | User Perception |
|---|---|---|
| 1 | User asks complex reasoning question | Normal input |
| 2 | Router or user prefixes `!ultra` | Modal pops: "Send to Nebius Nemotron Ultra?" |
| 3 | Modal shows: estimated tokens, cost indicator, privacy warning | User sees transparent summary |
| 4 | User clicks **Approve Once** or **Always Approve for This Session** | Request sent |
| 5 | Response streams back | Cloud badge appears on message |
| 6 | Audit entry written | User can view in Privacy Dashboard |

---

## 6. Privacy Dashboard Flow

**Tab Layout:**
- **Overview:** Pie chart of local vs. cloud requests this session.
- **Data Sources:** Toggles for clipboard, files, etc., with "Clear History" per source.
- **Audit Log:** Filterable table (timestamp, action, detail, risk level). Read-only.
- **Storage:** Disk usage breakdown (models, memory, skills, logs).

---

## 7. Error & Edge Case Flows

| Scenario | User Flow |
|---|---|
| Model not downloaded | Wizard returns to Step 3 with retry button |
| Out of disk space | Banner: "Nexus needs 500MB more. Choose new data directory?" |
| Skill AST rejection | Preview modal shows error: "Import `requests` is not allowed." |
| Nebius API key missing | Cloud burst modal shows: "Add Nebius key in Settings to enable." |
| CPU-only machine | First-launch notice: "Running in CPU mode. Responses will be slower." |
| Skill runtime timeout | UI shows: "Skill timed out after 30s. Check for infinite loops." |

---

## 8. Keyboard Shortcuts

| Shortcut | Action |
|---|---|
| `Ctrl + Shift + Space` | Focus chat input |
| `Ctrl + /` | Toggle Skill Library |
| `Ctrl + Shift + D` | Open Privacy Dashboard |
| `Esc` | Cancel pending cloud approval or skill generation |

---

## 9. Mobile Web UI Flow (Headless Mode)
- User runs `python -m nexus --headless --port 8080`.
- Connects from phone on same Wi-Fi.
- Simplified single-column layout: Chat + Memory toggle + Settings.
- All data still resides on the host PC; phone is merely a viewport.