"""Skill Executor runs approved Python skills in a sandboxed environment."""
import ast
import json
import sys
import os
from pathlib import Path

from Nexus.skills.registry import SkillRegistry
from Nexus.sandbox.policy import validate_code
from Nexus.sandbox.runner import run_skill


class SkillExecutor:
    """Executes approved Python skills in a sandboxed subprocess."""

    MAX_RUNTIME = 30  # seconds

    def __init__(self, registry=None):
        self.registry = registry or SkillRegistry()

    def execute(self, skill_name, workspace=None):
        """Execute a registered skill by name.

        Returns dict with status, output, and audit info.
        """
        skill = self.registry.get(skill_name)
        if skill is None:
            return {
                "status": "not_found",
                "error": f"Skill '{skill_name}' not registered",
            }

        # Validate code against AST policy
        valid, error = validate_code(skill["python_code"])
        if not valid:
            self.registry.update_last_run(skill_name, exit_code=1, runtime=0)
            return {
                "status": "rejected",
                "error": f"AST validation failed: {error}",
            }

        # Execute in sandbox
        result = run_skill(skill["python_code"], workspace or self._get_sandbox_dir())

        # Update registry with runtime metrics
        runtime = result.get("runtime", self.MAX_RUNTIME)
        self.registry.update_last_run(skill_name, result.get("exit_code", 1), runtime)

        return {
            "status": result.get("status", "error"),
            "stdout": result.get("stdout", ""),
            "stderr": result.get("stderr", ""),
            "exit_code": result.get("exit_code", 1),
            "runtime": runtime,
        }

    def execute_python(self, python_code, workspace=None, skill_name=None):
        """Execute arbitrary validated Python code.

        Runtime metrics are only written when `skill_name` refers to a real
        registered skill; ad-hoc code has no registry row to update.
        """
        # Validate code against AST policy
        valid, error = validate_code(python_code)
        if not valid:
            return {
                "status": "rejected",
                "error": f"AST validation failed: {error}",
            }

        # Execute in sandbox
        result = run_skill(python_code, workspace or self._get_sandbox_dir())

        runtime = result.get("runtime", self.MAX_RUNTIME)
        if skill_name is not None:
            self.registry.update_last_run(skill_name, result.get("exit_code", 1), runtime)

        return {
            "status": result.get("status", "error"),
            "stdout": result.get("stdout", ""),
            "stderr": result.get("stderr", ""),
            "exit_code": result.get("exit_code", 1),
            "runtime": runtime,
        }

    def _get_sandbox_dir(self):
        """Get the sandbox directory path."""
        from Nexus.config import settings
        return str(settings.sandbox_dir)