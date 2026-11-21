"""Settings from the environment."""

from functools import lru_cache
from pathlib import Path
from typing import Annotated, Literal

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

PACKAGE_DATA = Path(__file__).parent / "data"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    auth_mode: Literal["clerk", "dev"] = "clerk"
    clerk_domain: str = ""
    clerk_publishable_key: str = ""
    clerk_oauth_client_id: str = ""
    clerk_oauth_client_secret: str = ""
    base_url: str = ""
    allowed_emails: str = ""
    # M17: operators (comma list). Set = the server is invite only and the operators get Settings > Server access.
    operator_emails: str = ""
    data_dir: Path = Path("./data")
    # Bundled data files (growth tables, milestones). Tests point this at small fixtures.
    bundled_data_dir: Path = PACKAGE_DATA
    # Optional sleep norms file (see README "Sleep model"). Empty = DATA_DIR/sleep_norms.json, else the bundled file.
    sleep_norms_path: Path | None = None
    llm_base_url: str = "http://llama:8080/v1"
    llm_model: str = ""
    llm_api_key: str = ""
    # Cry sound models (optional extra "cry"). Default: <DATA_DIR>/models/cry, else the bundled files
    cry_model_dir: Path | None = None
    # Voice commands (optional extra "voice"): Whisper on the CPU. The first use downloads the model to
    # DATA_DIR/models/whisper. Other languages: WHISPER_MODEL=small and WHISPER_LANGUAGE= (empty = find it).
    voice: bool = True
    whisper_model: str = "small.en"
    whisper_language: str = "en"
    host: str = "0.0.0.0"
    port: int = 8000
    # Rate limits as "count/seconds". AI and uploads: per user. Wrong tokens: per client address.
    limit_ai: Annotated[str, Field(pattern=r"^\d+/\d+$")] = "30/300"
    limit_uploads: Annotated[str, Field(pattern=r"^\d+/\d+$")] = "20/3600"
    limit_voice: Annotated[str, Field(pattern=r"^\d+/\d+$")] = "300/300"
    limit_bad_token: Annotated[str, Field(pattern=r"^\d+/\d+$")] = "20/600"
    # Model requests that can wait for the model at one time; one more gets "The assistant is busy" (429).
    llm_queue_max: int = 8
    # Seconds a request with no stream (plain words, model test) can wait for the model; then "busy" (429).
    llm_queue_wait: float = 60
    # True only behind Cloudflare Tunnel: then the client address comes from the CF-Connecting-IP header.
    behind_cloudflare: bool = False

    @property
    def allowed(self) -> frozenset[str]:
        return frozenset(e.strip().lower() for e in self.allowed_emails.split(",") if e.strip())

    @property
    def operators(self) -> frozenset[str]:
        return frozenset(e.strip().lower() for e in self.operator_emails.split(",") if e.strip())

    def check(self) -> None:
        """Refuse to start with an unsafe or incomplete auth setup."""
        if self.auth_mode == "clerk":
            missing = [
                name.upper()
                for name in ("clerk_domain", "clerk_publishable_key", "clerk_oauth_client_id",
                             "clerk_oauth_client_secret", "base_url")
                if not getattr(self, name)
            ]
            if missing:
                raise SystemExit(
                    f"Refusing to start: AUTH_MODE=clerk needs {', '.join(missing)}. "
                    "For local development set AUTH_MODE=dev."
                )


@lru_cache
def get_settings() -> Settings:
    return Settings()
