"""Settings from the environment."""

from functools import lru_cache
from pathlib import Path
from typing import Literal

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
    data_dir: Path = Path("./data")
    # Bundled data files (growth tables, milestones). Tests point this at small fixtures.
    bundled_data_dir: Path = PACKAGE_DATA
    # Optional sleep norms file (see README "Sleep model"). Empty = DATA_DIR/sleep_norms.json.
    sleep_norms_path: Path | None = None
    llm_base_url: str = "http://llama:8080/v1"
    llm_model: str = ""
    llm_api_key: str = ""
    # Cry sound models (optional extra "cry"). Default: <DATA_DIR>/models/cry
    cry_model_dir: Path | None = None
    host: str = "0.0.0.0"
    port: int = 8000

    @property
    def allowed(self) -> frozenset[str]:
        return frozenset(e.strip().lower() for e in self.allowed_emails.split(",") if e.strip())

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
