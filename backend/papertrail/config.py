"""Settings, limits and paths (BUILD_PLAN §8.1).

Where settings come from, highest priority first:
1. real environment variables
2. a `.env` file in the current folder (handy when developing in the repo)
3. a `.env` file in the data folder (handy for installed users)
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

import platformdirs
from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

APP_NAME = "papertrail"
PACKAGE_DIR = Path(__file__).resolve().parent

ProviderName = Literal["claude", "replay", "fake"]
Effort = Literal["low", "medium", "high"]
EFFORT_ORDER: tuple[Effort, ...] = ("low", "medium", "high")


class MissingApiKeyError(RuntimeError):
    """Raised when the Claude provider is selected but no API key is configured."""


def default_data_dir() -> Path:
    return Path(platformdirs.user_data_dir(APP_NAME, appauthor=False))


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file_encoding="utf-8",
        extra="ignore",
        populate_by_name=True,
    )

    anthropic_api_key: SecretStr | None = Field(default=None, alias="ANTHROPIC_API_KEY")
    anthropic_workspace_id: str | None = Field(default=None, alias="ANTHROPIC_WORKSPACE_ID")

    provider: ProviderName = Field(default="claude", alias="PAPERTRAIL_PROVIDER")
    model: str = Field(default="claude-haiku-5-5", alias="PAPERTRAIL_MODEL")
    effort: Effort = Field(default="medium", alias="PAPERTRAIL_EFFORT")

    data_dir: Path = Field(default_factory=default_data_dir, alias="PAPERTRAIL_DATA_DIR")
    port: int = Field(default=8000, alias="PAPERTRAIL_PORT", ge=1, le=65535)
    max_mb: int = Field(default=20, alias="PAPERTRAIL_MAX_MB", ge=1)
    max_pages: int = Field(default=50, alias="PAPERTRAIL_MAX_PAGES", ge=1)
    dev: bool = Field(default=False, alias="PAPERTRAIL_DEV")
    max_docs_per_day: int = Field(default=50, alias="PAPERTRAIL_MAX_DOCS_PER_DAY", ge=0)
    recordings_dir: Path | None = Field(default=None, alias="PAPERTRAIL_RECORDINGS_DIR")

    # Not user-facing knobs, but settable so tests can shorten them.
    parse_timeout_s: float = Field(default=60.0, alias="PAPERTRAIL_PARSE_TIMEOUT_S", gt=0)
    api_timeout_s: float = Field(default=180.0, alias="PAPERTRAIL_API_TIMEOUT_S", gt=0)

    @field_validator("anthropic_api_key", mode="before")
    @classmethod
    def _blank_key_is_unset(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("anthropic_workspace_id", "recordings_dir", mode="before")
    @classmethod
    def _blank_is_unset(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            return None
        return value

    # Paths ---------------------------------------------------------------
    @property
    def db_path(self) -> Path:
        return self.data_dir / "papertrail.db"

    @property
    def files_dir(self) -> Path:
        return self.data_dir / "files"

    @property
    def runs_dir(self) -> Path:
        return self.data_dir / "runs"

    @property
    def tmp_dir(self) -> Path:
        return self.data_dir / "tmp"

    @property
    def logs_dir(self) -> Path:
        return self.data_dir / "logs"

    @property
    def static_dir(self) -> Path:
        return PACKAGE_DIR / "static"

    @property
    def max_bytes(self) -> int:
        return self.max_mb * 1024 * 1024

    @property
    def has_api_key(self) -> bool:
        return self.anthropic_api_key is not None

    def resolved_recordings_dir(self) -> Path:
        """Where the Replay provider looks for saved responses.

        Explicit setting first; otherwise `eval/recorded` in the current folder or in the
        source checkout this package was loaded from.
        """
        if self.recordings_dir is not None:
            return self.recordings_dir
        candidates = [
            Path.cwd() / "eval" / "recorded",
            Path.cwd().parent / "eval" / "recorded",
            PACKAGE_DIR.parent.parent / "eval" / "recorded",
        ]
        for candidate in candidates:
            if candidate.is_dir():
                return candidate
        return candidates[0]

    def ensure_dirs(self) -> None:
        for path in (self.data_dir, self.files_dir, self.runs_dir, self.tmp_dir, self.logs_dir):
            path.mkdir(parents=True, exist_ok=True)

    def require_api_key(self) -> SecretStr:
        """Fail fast with a clear message; never include the key itself."""
        if self.anthropic_api_key is None:
            raise MissingApiKeyError(
                "ANTHROPIC_API_KEY is not set. Add it to the .env file in your data folder "
                f"({self.data_dir}) or set PAPERTRAIL_PROVIDER=replay to use saved responses."
            )
        return self.anthropic_api_key


def load_settings(**overrides: Any) -> Settings:
    """Build settings with the priority order described in the module docstring.

    The data folder can itself be set in the current folder's `.env`, so it is resolved
    first, then its `.env` is added as the lowest-priority source.
    """
    bootstrap = Settings(_env_file=".env", **overrides)
    data_env = bootstrap.data_dir / ".env"
    env_files: tuple[str, ...] = (str(data_env), ".env") if data_env.is_file() else (".env",)
    # pydantic-settings gives later files priority over earlier ones.
    return Settings(_env_file=env_files, **overrides)
