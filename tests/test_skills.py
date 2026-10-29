"""Skills module tests for Nexus."""

import json
import time

import pytest

from Nexus.config import settings
from Nexus.skills.generator import SkillGenerator, SKILL_PROMPT_TEMPLATE
from Nexus.skills.registry import SkillRegistry
from Nexus.skills.executor import SkillExecutor
from Nexus.sandbox.policy import validate_code


def test_skill_registry(tmp_path, monkeypatch):
    """Test SkillRegistry CRUD operations."""
    skills_dir = tmp_path / "skills"
    skills_dir.mkdir()
    monkeypatch.setattr(settings, "skills_dir", skills_dir)

    registry = SkillRegistry()

    python_code = "import os\nprint('hello')"
    assert registry.register(
        skill_name="test_skill",
        description="A test skill",
        python_code=python_code,
    ) is True, "First registration should succeed"

    # Duplicate names are rejected
    assert registry.register(
        skill_name="test_skill",
        description="Another description",
        python_code=python_code,
    ) is False, "Duplicate name should fail"

    skill = registry.get("test_skill")
    assert skill is not None
    assert skill["name"] == "test_skill"
    assert skill["description"] == "A test skill"
    assert skill["python_code"] == python_code

    skills = registry.list_all()
    assert len(skills) >= 1
    assert "test_skill" in [s["name"] for s in skills]

    assert registry.delete("test_skill") is True
    assert registry.delete("test_skill") is False

    assert registry.get("test_skill") is None


def test_skill_registry_validate(tmp_path):
    """Test that AST validation blocks disallowed imports in registry."""
    registry = SkillRegistry(db_path=tmp_path / "skills.db")

    bad_code = "import requests\nprint('bad')"
    valid, error = validate_code(bad_code)
    assert valid is False
    assert "requests" in error.lower()

    good_code = "import os\nimport json\nprint('good')"
    valid, error = validate_code(good_code)
    assert valid is True


def test_skill_executor_import(tmp_path):
    """Test SkillExecutor can be instantiated."""
    registry = SkillRegistry(db_path=tmp_path / "skills.db")
    executor = SkillExecutor(registry=registry)
    assert executor is not None
    assert executor.MAX_RUNTIME == 30


def test_skill_generator_extracts_fenced_json():
    """Bare JSON, then markdown-fenced JSON; missing keys rejected."""
    from Nexus.skills.generator import SkillGenerator, extract_skill

    fenced = (
        "Here you go:\n```json\n"
        '{"skill_name": "hello_world", "description": "says hi", '
        '"python_code": "print(1)"}'
        "\n```"
    )
    skill = extract_skill(fenced)
    assert skill is not None
    assert skill["skill_name"] == "hello_world"
    assert extract_skill('not json at all') is None
    assert extract_skill('{"skill_name": "x", "description": "y"}') is None
    assert extract_skill('{"skill_name": "", "description": "y", "python_code": "z"}') is None

    class _FlakyLLM:
        def __init__(self):
            self.calls = 0

        def chat(self, messages):
            self.calls += 1
            if self.calls == 1:
                return "sorry, I cannot comply"
            return json.dumps(
                {"skill_name": "ok_skill", "description": "d", "python_code": "print(1)"}
            )

    llm = _FlakyLLM()
    out = SkillGenerator(llm).generate("do a thing")
    assert out["skill_name"] == "ok_skill"
    assert llm.calls == 2, "one retry after a bad first reply"


def test_skill_generator_rejects_code_failing_policy():
    """validate_code runs before registration; failure retries then raises."""
    from Nexus.skills.generator import SkillGenerator

    class _EvilLLM:
        def __init__(self):
            self.calls = 0

        def chat(self, messages):
            self.calls += 1
            return json.dumps(
                {"skill_name": "evil", "description": "d", "python_code": "import socket"}
            )

    llm = _EvilLLM()
    with pytest.raises(ValueError):
        SkillGenerator(llm).generate("do a thing")
    assert llm.calls == 2


def test_registry_update_if_exists(tmp_path):
    """Duplicates are refused by default, updated on request."""
    registry = SkillRegistry(db_path=tmp_path / "skills.db")

    assert registry.register("dup", "first", "print(1)", cron_schedule="0 9 * * *")
    assert registry.register("dup", "second", "print(2)") is False

    assert registry.register("dup", "second", "print(2)", update_if_exists=True) is True
    skill = registry.get("dup")
    assert skill["description"] == "second"
    assert skill["python_code"] == "print(2)"
    # Regenerating code must not silently drop the existing schedule.
    assert skill["cron_schedule"] == "0 9 * * *"


def test_scheduler_fires_cron_job(tmp_path):
    """A registered cron job actually executes the skill on a fast tick."""
    from Nexus.skills.scheduler import SkillScheduler
    from apscheduler.triggers.cron import CronTrigger

    registry = SkillRegistry(db_path=tmp_path / "skills.db")
    assert registry.register(
        skill_name="tick",
        description="prints a tick",
        python_code="print('tick')\n",
    )

    scheduler = SkillScheduler(registry=registry)
    # 1-second cron tick keeps the test fast while staying a real CronTrigger.
    scheduler.scheduler.add_job(
        scheduler._execute_skill_job,
        CronTrigger(second="*/1"),
        args=["tick"],
        id="skill_tick",
        replace_existing=True,
    )
    scheduler.start()
    try:
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if registry.get("tick")["last_run"]:
                break
            time.sleep(0.2)
    finally:
        scheduler.shutdown()

    skill = registry.get("tick")
    assert skill["last_run"], "cron job should have run the skill"
    assert skill["exit_code"] == 0


def test_skill_generator_template():
    """Test SkillGenerator prompt template structure."""
    generator = SkillGenerator(llm=None)

    prompt = SKILL_PROMPT_TEMPLATE.format(description="archive my downloads folder")

    assert "archive my downloads folder" in prompt
    assert "skill_name" in prompt
    assert "description" in prompt
    assert "python_code" in prompt
    assert generator.llm is None
