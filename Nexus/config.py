"""Configuration and paths for Nexus."""
from pathlib import Path
from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="nexus_")

    data_dir: Path = Path.home() / ".nexus"
    # The paths below are derived from data_dir in model_post_init: setting
    # NEXUS_DATA_DIR=/opt/nexus moves model_dir, skills_dir, sandbox_dir,
    # db_path, audit_path and chroma_path with it.
    model_dir: Path = Path()
    skills_dir: Path = Path()
    sandbox_dir: Path = Path()
    db_path: Path = Path()
    audit_path: Path = Path()
    chroma_path: Path = Path()

    model_name: str = "nvidia/Llama-3.1-Nemotron-Nano-4B-v1"
    gguf_filename: str = "Llama-3.1-Nemotron-Nano-4B-v1-Q4_K_M.gguf"

    nebius_api_key: SecretStr = SecretStr("")
    nebius_base_url: str = "https://api.studio.nebius.com/v1/"
    nebius_model: str = "nvidia/Nemotron-3-Ultra-550B"

    n_ctx: int = 4096
    temperature: float = 0.7
    # Stop sequences for local generation (NEXUS_STOP_TOKENS, JSON list).
    stop_tokens: list[str] = ["<|eot_id|>"]

    def model_post_init(self, __context) -> None:
        data_dir = Path(self.data_dir).expanduser().resolve()
        self.data_dir = data_dir
        self.model_dir = data_dir / "models"
        self.skills_dir = data_dir / "skills"
        self.sandbox_dir = data_dir / "sandbox"
        self.db_path = data_dir / "episodic.db"
        self.audit_path = data_dir / "audit.db"
        self.chroma_path = data_dir / "chroma"


settings = Settings()


def ensure_dirs() -> None:
    for d in [settings.data_dir, settings.model_dir, settings.skills_dir, settings.sandbox_dir]:
        d.mkdir(parents=True, exist_ok=True)
