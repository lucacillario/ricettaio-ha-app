from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import httpx2
import pytest

from app.config import Settings
from app.main import create_app


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
async def client(tmp_path: Path) -> AsyncIterator[httpx2.AsyncClient]:
    settings = Settings(
        data_dir=tmp_path,
        ai_enabled=True,
        ai_provider="fake",
        strict_ingress=False,
        trash_retention_days=30,
    )
    app = create_app(settings)
    async with app.router.lifespan_context(app):
        transport = httpx2.ASGITransport(app=app)
        async with httpx2.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as test_client:
            yield test_client


@pytest.fixture
def recipe_payload() -> dict:
    return {
        "title": "Pasta e ceci",
        "description": "Una ricetta cremosa da dispensa",
        "category_id": None,
        "cuisine": "italiana",
        "difficulty": "easy",
        "base_servings": "4",
        "serving_unit": "persone",
        "prep_time_minutes": 10,
        "cook_time_minutes": 25,
        "rest_time_minutes": None,
        "ingredients": [
            {
                "name": "ceci cotti",
                "quantity": "480",
                "unit": "g",
                "quantity_text": None,
                "preparation": "scolati",
                "optional": False,
                "scalable": True,
                "sort_order": 0,
                "original_text": None,
                "group": None,
            },
            {
                "name": "sale",
                "quantity": None,
                "unit": None,
                "quantity_text": "q.b.",
                "preparation": None,
                "optional": False,
                "scalable": False,
                "sort_order": 1,
                "original_text": None,
                "group": None,
            },
        ],
        "steps": [
            {
                "title": "Base",
                "instruction": "Scalda i ceci e frullane una parte.",
                "duration_minutes": 10,
                "temperature_celsius": None,
                "sort_order": 0,
            }
        ],
        "equipment": ["pentola"],
        "tags": ["dispensa", "vegetariano"],
        "dietary_labels": ["vegetariano"],
        "allergens": ["glutine"],
        "notes": "Aggiungere rosmarino a piacere.",
        "source": {"type": "manual"},
        "favorite": True,
    }
