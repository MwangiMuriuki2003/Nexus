"""Intent router for Nexus."""
from enum import Enum
import re


class Intent(Enum):
    CHAT = "chat"
    MEMORY_QUERY = "memory_query"
    SKILL_CREATION = "skill_creation"
    SCHEDULE_SKILL = "schedule_skill"
    SKILL_EXEC = "skill_exec"
    CLOUD_BURST = "cloud_burst"
    UNKNOWN = "unknown"


class IntentRouter:
    """Simple rule-based router. Replace with LLM classifier if needed.

    `known_skills` is an optional callable returning the names of registered
    skills; schedule phrases only route to SCHEDULE_SKILL when they mention one
    of them, otherwise they fall back to CHAT.
    """

    def __init__(self, known_skills=None):
        self.known_skills = known_skills

    def route(self, message: str) -> Intent:
        lower = message.lower().strip()

        if lower.startswith("!ultra"):
            return Intent.CLOUD_BURST

        if re.search(r"\b(what did i|remember|what was|find my|search for)\b", lower):
            return Intent.MEMORY_QUERY

        # Skill creation requires an explicit verb; "every day" alone is not a
        # creation request.
        if re.search(r"\b(create|make|build|generate)\s+(a\s+)?skill\b", lower):
            return Intent.SKILL_CREATION

        if re.search(r"\b(every day|every week|schedule)\b", lower):
            if self._references_known_skill(lower):
                return Intent.SCHEDULE_SKILL
            # No existing skill named: treat as ordinary chat.

        if lower.startswith("/skill"):
            return Intent.SKILL_EXEC

        return Intent.CHAT

    def _references_known_skill(self, lower: str) -> bool:
        if self.known_skills is None:
            return False
        try:
            names = list(self.known_skills())
        except Exception:
            return False
        return any(name.lower() in lower for name in names)