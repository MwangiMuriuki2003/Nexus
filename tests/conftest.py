"""Shared test configuration for the Nexus suite."""

import pytest

from Nexus.config import ensure_dirs


@pytest.fixture(scope="session", autouse=True)
def nexus_data_dirs():
    """Create ~/.nexus/{models,skills,sandbox} so stores can be opened."""
    ensure_dirs()


@pytest.fixture
def isolated_settings(tmp_path, monkeypatch):
    """Point every on-disk Nexus store at a temporary directory."""
    from Nexus.config import settings

    for name in ("data_dir", "model_dir", "skills_dir", "sandbox_dir"):
        path = tmp_path / name
        path.mkdir(parents=True, exist_ok=True)
        monkeypatch.setattr(settings, name, path)
    monkeypatch.setattr(settings, "db_path", tmp_path / "episodic.db")
    monkeypatch.setattr(settings, "audit_path", tmp_path / "audit.db")
    monkeypatch.setattr(settings, "chroma_path", tmp_path / "chroma")
    return settings
