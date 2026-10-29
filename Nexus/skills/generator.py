"""Generate Python skills from natural language."""
import json

from Nexus.sandbox.policy import validate_code

SKILL_PROMPT_TEMPLATE = """You are a helpful assistant that writes Python automation scripts.
Write a script that does the following:
{description}

Respond ONLY with a JSON object in this exact format:
{{
  "skill_name": "short_snake_case_name",
  "description": "One-line description",
  "python_code": "Complete Python source code as a single string"
}}

Rules for the code:
- Use only the Python standard library.
- Do not use exec, eval, compile, or __import__.
- Do not import socket, urllib, http.client, requests, subprocess, ctypes, or multiprocessing.
- The script should be runnable as a standalone file.
"""

REQUIRED_KEYS = ("skill_name", "description", "python_code")


def _candidate_payloads(raw: str):
    """Yield candidate JSON payloads: the raw reply first, then the fenced block."""
    text = (raw or "").strip()
    yield text
    if "```" in text:
        start = text.find("```")
        end = text.rfind("```")
        if end > start:
            block = text[start + 3 : end]
            lines = block.splitlines()
            # Drop the fence language tag (```json) if present.
            if lines and lines[0].strip() and not lines[0].lstrip().startswith("{"):
                lines = lines[1:]
            yield "\n".join(lines).strip()


def extract_skill(raw: str) -> dict | None:
    """Parse an LLM reply into a skill dict, or None if it never becomes one.

    Tries `json.loads` on the whole reply first, then on the reply with
    markdown fences stripped, and finally validates the required keys.
    """
    for candidate in _candidate_payloads(raw):
        try:
            parsed = json.loads(candidate)
        except (json.JSONDecodeError, TypeError):
            continue
        if not isinstance(parsed, dict):
            continue
        if not all(isinstance(parsed.get(key), str) and parsed[key].strip() for key in REQUIRED_KEYS):
            continue
        return {key: parsed[key] for key in REQUIRED_KEYS}
    return None


class SkillGenerator:
    def __init__(self, llm):
        self.llm = llm

    def generate(self, description: str, attempts: int = 2) -> dict:
        """Generate a sandbox-valid skill dict, retrying once on failure.

        Raises ValueError when no attempt produced parseable JSON whose code
        also passes the sandbox policy.
        """
        prompt = SKILL_PROMPT_TEMPLATE.format(description=description)
        messages = [{"role": "user", "content": prompt}]
        last_error = "no response from the model"

        for _ in range(max(1, attempts)):
            raw = self.llm.chat(messages)
            skill = extract_skill(raw)
            if skill is None:
                last_error = "reply was not JSON with skill_name/description/python_code"
                continue
            valid, error = validate_code(skill["python_code"])
            if not valid:
                last_error = f"generated code rejected by sandbox policy: {error}"
                continue
            return skill

        raise ValueError(f"skill generation failed after {attempts} attempts: {last_error}")
