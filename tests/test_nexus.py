"""Integration tests across the Nexus modules."""

import pytest

from Nexus.config import settings

MODEL_AVAILABLE = (settings.model_dir / settings.gguf_filename).exists()

requires_model = pytest.mark.skipif(
    not MODEL_AVAILABLE,
    reason="local GGUF model not downloaded (run `python -m Nexus setup`, see RUN.md)",
)


def test_memory_manager_round_trip(isolated_settings):
    """A stored event must come back out of the memory manager."""
    from Nexus.core.memory_manager import MemoryManager

    memory = MemoryManager(
        episodic_db_path=str(isolated_settings.db_path),
        semantic_persist_dir=str(isolated_settings.chroma_path),
    )
    memory.add_chat_message("user", "I copied the quarterly report into the archive folder")

    results = memory.query("copied the quarterly report")

    assert results["episodic"], "episodic search should hit the stored event"
    assert results["episodic"][0]["source"] == "chat"
    assert results["episodic"][0]["content"].startswith("I copied")


def test_skill_register_and_execute(isolated_settings):
    """A registered skill runs in the sandbox and reports its exit code."""
    from Nexus.skills.registry import SkillRegistry
    from Nexus.skills.executor import SkillExecutor

    registry = SkillRegistry()
    assert registry.register(
        skill_name="say_hi",
        description="Prints a greeting",
        python_code="import os\nprint('hi from skill')\n",
    )

    result = SkillExecutor(registry=registry).execute("say_hi")

    assert result["status"] == "ok", result
    assert result["exit_code"] == 0
    assert "hi from skill" in result["stdout"]
    assert result["runtime"] >= 0

    assert registry.get("say_hi")["exit_code"] == 0


def test_skill_executor_rejects_disallowed_import(isolated_settings):
    """AST validation stops unsafe skills before execution."""
    from Nexus.skills.registry import SkillRegistry
    from Nexus.skills.executor import SkillExecutor

    registry = SkillRegistry()
    registry.register(
        skill_name="unsafe_skill",
        description="Uses a banned import",
        python_code="import requests\nprint('nope')\n",
    )

    result = SkillExecutor(registry=registry).execute("unsafe_skill")

    assert result["status"] == "rejected"
    assert "requests" in result["error"].lower()


def test_skill_executor_missing_skill(isolated_settings):
    """Executing an unknown skill reports not_found instead of raising."""
    from Nexus.skills.executor import SkillExecutor

    result = SkillExecutor().execute("does_not_exist")

    assert result["status"] == "not_found"
    assert "does_not_exist" in result["error"]


class _StubLLM:
    """Stands in for the GGUF model so the engine can be tested without it."""

    def __init__(self):
        self.calls = []

    def chat(self, messages, temperature=0.7):
        self.calls.append(messages)
        return "stub reply"


def test_engine_stores_both_turns_and_recalls_them(isolated_settings):
    """Chat stores user+assistant with roles, injects context, and MEMORY_QUERY hits."""
    from Nexus.core.engine import NexusEngine
    from Nexus.core.privacy_gate import PrivacyGate

    class _ChattyLLM(_StubLLM):
        def chat(self, messages, temperature=0.7):
            self.calls.append(messages)
            # The stored assistant turn carries the phrases a later recall uses.
            return "what was on the pineapple dashboard: your project notes"

    llm = _ChattyLLM()
    engine = NexusEngine(
        settings=isolated_settings,
        privacy_gate=PrivacyGate(isolated_settings),
        llm=llm,
    )

    engine.process_message("my favorite project is pineapple dashboard")

    # Both turns are stored with their roles preserved.
    user_rows = engine.memory.episodic.search("favorite project is pineapple", include_role=True)
    assistant_rows = engine.memory.episodic.search("what was on the pineapple", include_role=True)
    assert user_rows and user_rows[0][3] == "user"
    assert assistant_rows and assistant_rows[0][3] == "assistant"

    # The local LLM got a system context message before the user turn.
    first_call = llm.calls[0]
    assert first_call[0]["role"] == "system"
    assert first_call[-1] == {"role": "user", "content": "my favorite project is pineapple dashboard"}

    # MEMORY_QUERY now returns hits from the past chat.
    result = engine.process_message("what was on the pineapple dashboard")
    assert result["intent"].name == "MEMORY_QUERY"
    contents = [hit["content"] for hit in result["memory_results"]["episodic"]]
    assert any("pineapple dashboard" in content for content in contents)


def test_engine_cloud_burst_strips_prefix_and_stays_unapproved(isolated_settings):
    """!ultra is stripped before forwarding; denial never reports cloud_approved."""
    from Nexus.core.engine import NexusEngine
    from Nexus.core.privacy_gate import PrivacyGate

    gate = PrivacyGate(isolated_settings)
    captured = []
    original = gate.cloud_request

    def spy(messages, reason):
        captured.append(messages)
        return original(messages, reason)

    gate.cloud_request = spy

    engine = NexusEngine(settings=isolated_settings, privacy_gate=gate, llm=_StubLLM())

    burst = engine.process_message("!ultra prove it works")

    assert burst["intent"].name == "CLOUD_BURST"
    assert burst["cloud_approved"] is False
    assert "denied" in burst["response"].lower()
    # The trigger prefix is stripped before the prompt reaches the gate.
    assert captured == [[{"role": "user", "content": "prove it works"}]]


def test_engine_routes_and_never_calls_cloud(isolated_settings):
    """Chat goes to the local model; cloud bursts stay denied without approval."""
    from Nexus.core.engine import NexusEngine
    from Nexus.core.privacy_gate import PrivacyGate

    llm = _StubLLM()
    engine = NexusEngine(
        settings=isolated_settings,
        privacy_gate=PrivacyGate(isolated_settings),
        llm=llm,
    )

    chat = engine.process_message("something completely different")
    assert chat["intent"].name == "CHAT"
    assert chat["response"] == "stub reply"
    assert len(llm.calls) == 1

    burst = engine.process_message("!ultra summarise my week")
    assert burst["intent"].name == "CLOUD_BURST"
    assert burst["cloud_approved"] is False
    assert "denied" in burst["response"].lower()
    assert len(llm.calls) == 1  # the cloud path must not touch the local model


@requires_model
def test_engine_end_to_end(isolated_settings):
    """Full pipeline: message -> intent -> local LLM -> response."""
    from Nexus.core.engine import NexusEngine

    engine = NexusEngine(settings=isolated_settings)

    chat = engine.process_message("hello, who are you?")
    assert chat["intent"].name == "CHAT"
    assert isinstance(chat["response"], str) and chat["response"]

    memory_query = engine.process_message("what did i copy yesterday")
    assert memory_query["intent"].name == "MEMORY_QUERY"
    assert memory_query["memory_results"] is not None
