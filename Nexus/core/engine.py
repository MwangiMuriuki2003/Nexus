"""Core engine orchestrates the Nexus event loop: routing, memory, skills, and cloud burst."""
import atexit
import re
from pathlib import Path

from Nexus.core.router import IntentRouter, Intent
from Nexus.core.privacy_gate import PrivacyGate
from Nexus.core.memory_manager import MemoryManager
from Nexus.models.local_llm import LocalLLM
from Nexus.memory.embedder import Embedder
from Nexus.skills.registry import SkillRegistry
from Nexus.skills.executor import SkillExecutor
from Nexus.skills.scheduler import SkillScheduler


def _weekday_number(text: str) -> int:
    """Map a weekday name in `text` to a cron number (Mon=0 … Sun=6)."""
    days = [
        "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
    ]
    for index, name in enumerate(days):
        if name in text or name[:3] in text:
            return index
    return 0  # default: Monday


class NexusEngine:
    """Main event loop that routes user intent and coordinates all subsystem interactions."""

    def __init__(self, settings, privacy_gate=None, llm=None):
        self.settings = settings
        # One registry per engine: routing, generation and execution all share it.
        self.registry = SkillRegistry(db_path=Path(settings.skills_dir) / "skills.db")
        self.router = IntentRouter(
            known_skills=lambda: [s["name"] for s in self.registry.list_all()]
        )
        self.privacy_gate = privacy_gate or PrivacyGate(settings)
        self.llm = llm or LocalLLM(
            model_path=str(settings.model_dir / settings.gguf_filename),
            n_ctx=settings.n_ctx,
        )
        self.embedder = Embedder()

        # Initialize memory manager with paths from settings
        self.memory = MemoryManager(
            episodic_db_path=settings.db_path,
            semantic_persist_dir=settings.chroma_path,
        )

        # Initialize skill scheduler for scheduled automation, sharing the
        # engine's registry so scheduled skills and routes stay in sync.
        self.skill_scheduler = SkillScheduler(registry=self.registry)
        # Start it: constructed-but-never-started jobs would never fire.
        self.skill_scheduler.start()
        # Register shutdown hooks: the scheduler instance (not the module-level
        # global) is what must be shut down, and all SQLite-backed stores.
        atexit.register(self.skill_scheduler.shutdown)
        atexit.register(self.close)

    def process_message(self, message):
        """Process a user message through the full pipeline.

        Returns dict with response, intent, and metadata.
        """
        # 1. Route the intent
        intent = self.router.route(message)

        # 2. Handle based on intent
        result = {
            "response": "",
            "intent": intent,
            "memory_results": None,
            "skill_info": None,
            "cloud_approved": False,
        }

        if intent == Intent.CHAT:
            result["response"] = self._handle_chat(message)

        elif intent == Intent.MEMORY_QUERY:
            memory_results = self.memory.query(message)
            result["memory_results"] = memory_results
            result["response"] = self._format_memory_response(memory_results)

        elif intent == Intent.SKILL_CREATION:
            result["skill_info"] = self._generate_skill(message)
            result["response"] = self._format_skill_generation(result["skill_info"])

        elif intent == Intent.SKILL_EXEC:
            # Extract skill name from message or use default
            result["response"] = self._execute_skill(message)

        elif intent == Intent.SCHEDULE_SKILL:
            result["response"] = self._handle_schedule_skill(message)

        elif intent == Intent.CLOUD_BURST:
            response, cloud_approved = self._handle_cloud_burst(message)
            result["response"] = response
            # True only for a real Nebius reply (a string), never for the
            # local-denial dict returned by the privacy gate.
            result["cloud_approved"] = cloud_approved

        elif intent == Intent.UNKNOWN:
            result["response"] = self._handle_unknown(message)

        return result

    def _handle_chat(self, message):
        """Handle a regular chat message with local LLM.

        Retrieved episodic/semantic memories are injected as a system context so
        the model can answer from what it already knows about the user, and both
        turns are stored back into episodic memory.
        """
        try:
            memory = self.memory.query(message)
            messages = [
                {"role": "system", "content": self._build_context(memory)},
                {"role": "user", "content": message},
            ]
            response = self.llm.chat(messages)
            # Store both turns in episodic memory (role is preserved).
            self.memory.add_chat_message("user", message)
            self.memory.add_chat_message("assistant", response)
            return response
        except Exception as e:
            return f"Error: {e}"

    def _build_context(self, memory: dict) -> str:
        """Render retrieved memories as the system prompt for the local LLM."""
        lines = [
            "You are Nexus, a private desktop assistant running fully locally.",
            "Use the memories below when they are relevant; otherwise ignore them.",
        ]

        episodic = memory.get("episodic") or []
        if episodic:
            lines.append("Relevant memories:")
            for hit in episodic[:5]:
                stamp = hit.get("timestamp", "")
                source = hit.get("source", "")
                role = hit.get("role") or source
                lines.append(f"- [{stamp}] ({role}) {hit['content'][:300]}")

        semantic = memory.get("semantic") or []
        if semantic:
            lines.append("Relevant stored documents:")
            for doc in semantic[:3]:
                lines.append(f"- {str(doc)[:300]}")

        return "\n".join(lines)

    def _format_memory_response(self, memory_results):
        """Format memory query results into a natural language response."""
        intent = memory_results.get("intent")
        episodic = memory_results.get("episodic", [])
        semantic = memory_results.get("semantic", [])

        parts = []

        if episodic:
            parts.append(f"Found {len(episodic)} matching timeline events.")
            # Show most recent match
            latest = episodic[0]
            parts.append(f"Most recent: [{latest['timestamp']}] {latest['content'][:100]}...")

        if semantic:
            parts.append(f"Found {len(semantic)} semantic matches.")

        if not episodic and not semantic:
            return "No matching memories found. Try a different query?"

        return "\n".join(parts)

    def _generate_skill(self, message):
        """Generate a skill from natural language request."""
        from Nexus.skills.generator import SkillGenerator

        generator = SkillGenerator(llm=self.llm)
        try:
            skill_dict = generator.generate(message)
        except ValueError as exc:
            # Generation/parsing failed after one retry: report instead of raising.
            return {"error": str(exc), "registered": False}

        # Register the skill; a duplicate name updates the existing entry.
        success = self.registry.register(
            skill_name=skill_dict["skill_name"],
            description=skill_dict["description"],
            python_code=skill_dict["python_code"],
            update_if_exists=True,
        )

        return {
            "skill_name": skill_dict.get("skill_name"),
            "description": skill_dict.get("description"),
            "python_code": skill_dict.get("python_code"),
            "registered": success,
        }

    def _format_skill_generation(self, skill_info):
        """Format skill generation output for UI display."""
        if skill_info is None:
            return "Skill generation failed."

        registered = skill_info.get("registered", False)
        name = skill_info.get("skill_name", "unknown")
        desc = skill_info.get("description", "")
        code = skill_info.get("python_code", "")

        if "error" in skill_info:
            return f"Skill generation failed: {skill_info['error']}"

        output = [f"Skill: {name}", f"Description: {desc}"]
        if registered:
            output.append("Status: Registered and ready for execution.")
        else:
            output.append("Status: Generation complete but registration failed.")
        output.append("\nPython code:")
        output.append(code)
        return "\n\n".join(output)

    def _execute_skill(self, message):
        """Execute a skill based on message command."""
        # Parse skill name from message (e.g., "/skill archive_logs")
        parts = message.strip().split()
        skill_name = None

        if len(parts) > 1:
            skill_name = parts[1]

        if not skill_name:
            return "Please specify which skill to execute. Use /skill <name>."

        executor = SkillExecutor(registry=self.registry)
        result = executor.execute(skill_name)

        if result["status"] == "ok":
            return (
                f"Skill executed successfully.\n"
                f"Exit code: {result['exit_code']}\n"
                f"Runtime: {result['runtime']:.2f}s\n"
                f"Stdout: {result['stdout'][-200:] if result['stdout'] else 'none'}"
            )
        elif result["status"] == "rejected":
            return f"Skill rejected: {result['error']}"
        else:
            return f"Skill not found: {result['error']}"

    def _handle_cloud_burst(self, message):
        """Handle cloud burst request through privacy gate.

        Returns (response_text, cloud_approved): cloud_approved is True only
        when the privacy gate actually forwarded to Nebius and got a string back.
        """
        # Strip the !ultra trigger before the prompt reaches the model.
        content = message.removeprefix("!ultra").strip()
        messages = [{"role": "user", "content": content}]

        # This will prompt for UI approval; in a headless context,
        # we default to local processing
        result = self.privacy_gate.cloud_request(messages, reason="Complex reasoning detected")

        if not isinstance(result, str):
            # Denied (or approved without an API key): local fallback dict.
            body = result.get("content", "") if isinstance(result, dict) else str(result)
            if body.startswith("[Local] No Nebius API key"):
                return f"[Local] {body}", False
            return (
                f"[Local] Cloud request denied by privacy gate.\n\n"
                f"{body}",
                False,
            )
        # Approved - cloud response (a string means Nebius answered).
        return f"[Cloud] Response from Nemotron 3 Ultra:\n{result}", True

    def _handle_schedule_skill(self, message):
        """Schedule an existing skill from a natural-language request.

        Understands `every day` / `every week` plus an optional `at HH:MM`
        (defaults to 09:00). The router only routes here when a registered
        skill is named in the message.
        """
        lower = message.lower()
        names = [s["name"] for s in self.registry.list_all()]
        skill_name = next((n for n in names if n.lower() in lower), None)
        if skill_name is None:
            return "I couldn't find an existing skill to schedule. Create it first, then ask again."

        time_match = re.search(r"\bat\s+(\d{1,2})(?::(\d{2}))?\b", lower)
        if time_match:
            hour = int(time_match.group(1))
            minute = int(time_match.group(2) or 0)
        else:
            hour, minute = 9, 0
        if not (0 <= hour <= 23 and 0 <= minute <= 59):
            return f"That time doesn't look valid: {hour:02d}:{minute:02d}."

        if "every week" in lower:
            weekday = _weekday_number(lower)
            cron = f"{minute} {hour} * * {weekday}"
            when = "weekly"
        else:
            cron = f"{minute} {hour} * * *"
            when = "daily"

        if not self.skill_scheduler.schedule_skill(skill_name, cron):
            return f"Could not schedule skill '{skill_name}' (bad cron: {cron})."
        return f"Scheduled skill '{skill_name}' {when} at {hour:02d}:{minute:02d} (cron: `{cron}`)."

    def _handle_unknown(self, message):
        """Handle unknown/intents that don't match routes."""
        return (
            "I'm not sure how to help with that. "
            "Try asking me about your memories, "
            "creating a skill, or using /skill commands."
        )

    def close(self):
        """Close the three SQLite-backed stores this engine owns (atexit-hooked).

        The audit log may be shared with the UI, so failures and double-closes
        are tolerated: SQLite also reclaims the handle at process exit.
        """
        stores = [
            getattr(getattr(self, "privacy_gate", None), "audit", None),
            getattr(getattr(self, "memory", None), "episodic", None),
            getattr(self, "registry", None),
        ]
        for store in stores:
            if store is None:
                continue
            try:
                store.close()
            except Exception:  # best effort at shutdown
                pass