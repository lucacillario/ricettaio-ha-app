from __future__ import annotations

import json
from pathlib import Path

from app.config import Settings


def test_settings_load_openrouter_options(tmp_path: Path, monkeypatch) -> None:
    options_path = tmp_path / "options.json"
    options_path.write_text(
        json.dumps(
            {
                "ai_enabled": True,
                "ai_provider": "openrouter",
                "openrouter_api_key": "sk-or-v1-test",
                "openrouter_models": "deepseek/model, google/model ,openai/model",
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("RICETTAIO_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("RICETTAIO_OPTIONS_PATH", str(options_path))
    monkeypatch.delenv("RICETTAIO_AI_PROVIDER", raising=False)
    monkeypatch.delenv("RICETTAIO_OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("RICETTAIO_OPENROUTER_MODELS", raising=False)

    settings = Settings.from_env()

    assert settings.ai_provider == "openrouter"
    assert settings.openrouter_api_key == "sk-or-v1-test"
    assert settings.openrouter_models == ("deepseek/model", "google/model", "openai/model")
