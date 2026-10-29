"""Core engine orchestrates the Nexus event loop: routing, memory, skills, and cloud burst."""
import atexit

from Nexus.core.router import IntentRouter, Intent
from Nexus.core.privacy_gate import PrivacyGate
from Nexus.core.memory_manager import MemoryManager
from Nexus.models.local_llm import LocalLLM
from Nexus.memory.embedder import Embedder
from Nexus.skills.registry import SkillRegistry
from Nexus.skills.executor import SkillExecutor
from Nexus.skills.scheduler import SkillScheduler


class NexusEngine:
    """Main event loop that routes user intent and coordinates all subsystem interactions."""

    def __init__(self, settings, privacy_gate=None, llm=None):
        self.settings = settings
        self.router = IntentRouter()
        self.privacy_gate = privacy_gate or PrivacyGate(settings)
        self.llm = llm or LocalLLM(
            model_path=str(settings.model_dir / settings.gguf_filename),
            n_ctx=settings.n_ctx,
        )
        self.embedder = Embedder()

        # Initialize memory manager with paths from settings
        self.memory = MemoryManager(
            episodic_db_path=str(settings.db_path),
            semantic_persist_dir=str(settings.chroma_path),
        )

        # Initialize skill scheduler for scheduled automation
        self.skill_scheduler = SkillScheduler()
        # Start it: constructed-but-never-started jobs would never fire.
        self.skill_scheduler.start()
        # Register shutdown hook: the scheduler instance (not the module-level
        # global) is what must be shut down.
        atexit.register(self.skill_scheduler.shutdown)

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
        """Handle a regular chat message with local LLM."""
        try:
            messages = [{"role": "user", "content": message}]
            response = self.llm.chat(messages)
            # Store in episodic memory
            self.memory.add_chat_message("user", message)
            return response
        except Exception as e:
            return f"Error: {e}"

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
        skill_dict = generator.generate(message)

        # Register the skill
        registry = SkillRegistry()
        success = registry.register(
            skill_name=skill_dict["skill_name"],
            description=skill_dict["description"],
            python_code=skill_dict["python_code"],
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

        output = [f"Skill: {name}", f"Description: {desc}"]
        if registered:
            output.append("Status: Registered and ready for execution.")
        else:
            output.append("Status: Generation complete but name already exists.")
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

        executor = SkillExecutor()
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

    def _handle_unknown(self, message):
        """Handle unknown/intents that don't match routes."""
        return (
            "I'm not sure how to help with that. "
            "Try asking me about your memories, "
            "creating a skill, or using /skill commands."
        )