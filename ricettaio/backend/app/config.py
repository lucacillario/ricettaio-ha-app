from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

DEFAULT_OPENROUTER_MODELS = (
    "deepseek/deepseek-v4.1-flash",
    "google/gemini-3.8-flash",
    "openai/gpt-5.2",
)


def _as_bool(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _as_list(value: Any, default: tuple[str, ...]) -> tuple[str, ...]:
    if value is None:
        return default
    values = value if isinstance(value, list) else str(value).split(",")
    result = tuple(str(item).strip() for item in values if str(item).strip())
    return result or default


@dataclass(frozen=True, slots=True)
class Settings:
    data_dir: Path
    ai_enabled: bool = True
    gemini_api_key: str = ""
    gemini_model: str = ""
    openrouter_api_key: str = ""
    openrouter_models: tuple[str, ...] = DEFAULT_OPENROUTER_MODELS
    ai_provider: str = "openrouter"
    strict_ingress: bool = False
    trash_retention_days: int = 30
    frontend_dir: Path | None = None

    @property
    def database_path(self) -> Path:
        return self.data_dir / "ricettaio.db"

    @property
    def uploads_dir(self) -> Path:
        return self.data_dir / "uploads"

    @classmethod
    def from_env(cls) -> Settings:
        data_dir = Path(os.getenv("RICETTAIO_DATA_DIR", "/data"))
        options_path = Path(os.getenv("RICETTAIO_OPTIONS_PATH", data_dir / "options.json"))
        options: dict[str, Any] = {}
        if options_path.is_file():
            try:
                options = json.loads(options_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                options = {}

        frontend_value = os.getenv("RICETTAIO_FRONTEND_DIR")
        frontend_dir = Path(frontend_value) if frontend_value else None

        return cls(
            data_dir=data_dir,
            ai_enabled=_as_bool(os.getenv("RICETTAIO_AI_ENABLED", options.get("ai_enabled")), True),
            gemini_api_key=os.getenv("RICETTAIO_GEMINI_API_KEY", options.get("gemini_api_key", "")),
            gemini_model=os.getenv("RICETTAIO_GEMINI_MODEL", options.get("gemini_model", "")),
            openrouter_api_key=os.getenv(
                "RICETTAIO_OPENROUTER_API_KEY", options.get("openrouter_api_key", "")
            ),
            openrouter_models=_as_list(
                os.getenv("RICETTAIO_OPENROUTER_MODELS", options.get("openrouter_models")),
                DEFAULT_OPENROUTER_MODELS,
            ),
            ai_provider=os.getenv(
                "RICETTAIO_AI_PROVIDER", options.get("ai_provider", "openrouter")
            ),
            strict_ingress=_as_bool(
                os.getenv("RICETTAIO_STRICT_INGRESS", options.get("strict_ingress")), False
            ),
            trash_retention_days=int(options.get("trash_retention_days", 30)),
            frontend_dir=frontend_dir,
        )
