from __future__ import annotations

import json
from decimal import Decimal
from typing import Any

import httpx
import pytest
from google.genai import _transformers as t
from google.genai import types
from pydantic import ValidationError

from app.ai import (
    AiAnswer,
    AiUnavailableError,
    OpenRouterAiProvider,
    gemini_response_schema,
    parse_gemini_response,
    sanitize_gemini_schema,
)
from app.domain import ChatMessage, RecipeCreate


class MockResponse:
    def __init__(self, parsed: Any = None, text: str = "") -> None:
        self.parsed = parsed
        self.text = text


def test_sanitize_gemini_schema_removes_exclusive_bounds() -> None:
    raw_schema = {
        "type": "object",
        "properties": {
            "servings": {
                "type": "number",
                "exclusiveMinimum": 0.0,
                "maximum": 100.0,
            },
            "ratio": {
                "type": "number",
                "exclusiveMaximum": 1.0,
            },
            "unsupported": {
                "$schema": "http://json-schema.org/draft-07/schema#",
                "examples": ["test"],
            },
        },
    }

    sanitized = sanitize_gemini_schema(raw_schema)
    assert "additionalProperties" not in sanitized
    assert "additional_properties" not in sanitized
    servings_prop = sanitized["properties"]["servings"]
    assert "exclusiveMinimum" not in servings_prop
    assert servings_prop["minimum"] == 0.0
    assert servings_prop["maximum"] == 100.0

    ratio_prop = sanitized["properties"]["ratio"]
    assert "exclusiveMaximum" not in ratio_prop
    assert ratio_prop["maximum"] == 1.0

    unsupported_prop = sanitized["properties"]["unsupported"]
    assert "$schema" not in unsupported_prop
    assert "examples" not in unsupported_prop


def test_gemini_response_schemas_compatible_with_genai_sdk() -> None:
    def assert_no_forbidden_keys(node: Any) -> None:
        if isinstance(node, dict):
            for key, val in node.items():
                assert key not in {"additionalProperties", "additional_properties"}
                assert key not in {"exclusiveMinimum", "exclusiveMaximum"}
                assert_no_forbidden_keys(val)
        elif isinstance(node, list):
            for item in node:
                assert_no_forbidden_keys(item)

    # AiAnswer contains proposed_recipe (RecipeCreate) with base_servings > 0
    ai_schema = gemini_response_schema(AiAnswer)
    assert_no_forbidden_keys(ai_schema)
    validated_ai = t.t_schema(None, ai_schema)
    assert validated_ai is not None
    assert isinstance(validated_ai, types.Schema)
    assert validated_ai.additional_properties is None

    # RecipeCreate directly
    recipe_schema = gemini_response_schema(RecipeCreate)
    assert_no_forbidden_keys(recipe_schema)
    validated_recipe = t.t_schema(None, recipe_schema)
    assert validated_recipe is not None
    assert isinstance(validated_recipe, types.Schema)
    assert validated_recipe.additional_properties is None


def test_parse_gemini_response_supports_dict_and_fenced_markdown() -> None:
    # 1. Dict parsing (standard when response_schema is passed as dict)
    dict_resp = MockResponse(parsed={"message": "Risposta in dict", "action": "none"})
    parsed_dict = parse_gemini_response(dict_resp, AiAnswer)
    assert parsed_dict.message == "Risposta in dict"
    assert parsed_dict.action == "none"

    # 2. Markdown fenced string parsing fallback
    fenced_resp = MockResponse(
        parsed=None,
        text="```json\n{\"message\": \"Risposta fenced\", \"action\": \"none\"}\n```",
    )
    parsed_fenced = parse_gemini_response(fenced_resp, AiAnswer)
    assert parsed_fenced.message == "Risposta fenced"


def test_parse_gemini_response_preserves_strict_pydantic_validation() -> None:
    # Valid proposal
    valid_payload = {
        "message": "Bozza creata",
        "action": "create",
        "proposed_recipe": {
            "title": "Torta margherita",
            "base_servings": 6,
            "serving_unit": "persone",
            "ingredients": [{"name": "uova", "quantity": "3"}],
            "steps": [{"instruction": "Sbatti le uova"}],
        },
    }
    result = parse_gemini_response(MockResponse(parsed=valid_payload), AiAnswer)
    assert result.proposed_recipe is not None
    assert result.proposed_recipe.base_servings == Decimal("6")

    # Invalid proposal: base_servings must be gt 0
    invalid_payload = {
        "message": "Bozza non valida",
        "action": "create",
        "proposed_recipe": {
            "title": "Torta",
            "base_servings": 0,
            "serving_unit": "persone",
            "ingredients": [{"name": "uova"}],
            "steps": [{"instruction": "Mescola"}],
        },
    }
    with pytest.raises(ValidationError):
        parse_gemini_response(MockResponse(parsed=invalid_payload), AiAnswer)


@pytest.mark.anyio
async def test_openrouter_uses_fallbacks_structured_output_and_privacy() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        assert request.headers["Authorization"] == "Bearer sk-or-v1-test"
        return httpx.Response(
            200,
            json={
                "model": "deepseek/deepseek-v4.1-flash",
                "choices": [
                    {
                        "message": {
                            "content": json.dumps(
                                {
                                    "message": "Nessuna ricetta trovata.",
                                    "referenced_recipe_ids": [],
                                    "action": "none",
                                    "target_recipe_id": None,
                                    "proposed_recipe": None,
                                    "rationale": None,
                                }
                            )
                        }
                    }
                ],
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = OpenRouterAiProvider(
            "sk-or-v1-test",
            (
                "deepseek/deepseek-v4.1-flash",
                "google/gemini-3.8-flash",
                "openai/gpt-5.2",
            ),
            client=client,
        )
        result = await provider.chat([ChatMessage(role="user", content="Cosa posso cucinare?")], [])

    assert result.message == "Nessuna ricetta trovata."
    assert captured["models"] == [
        "deepseek/deepseek-v4.1-flash",
        "google/gemini-3.8-flash",
        "openai/gpt-5.2",
    ]
    assert captured["response_format"]["type"] == "json_schema"
    assert captured["response_format"]["json_schema"]["strict"] is True
    assert captured["provider"] == {
        "require_parameters": True,
        "data_collection": "deny",
        "zdr": True,
    }


@pytest.mark.anyio
async def test_openrouter_free_uses_compatible_json_mode() -> None:
    captured: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured.update(json.loads(request.content))
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": {
                            "content": "```json\n"
                            '{"message":"Funziona","action":"none"}'
                            "\n```"
                        }
                    }
                ]
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = OpenRouterAiProvider(
            "sk-or-v1-test",
            ("openrouter/free",),
            strict_privacy=False,
            client=client,
        )
        result = await provider.chat([ChatMessage(role="user", content="Ciao")], [])

    assert result.message == "Funziona"
    assert captured["models"] == ["google/gemma-4-26b-a4b-it:free"]
    assert captured["response_format"] == {"type": "json_object"}
    assert captured["provider"] == {"require_parameters": True}
    assert "JSON Schema" in captured["messages"][0]["content"]


@pytest.mark.anyio
async def test_openrouter_reports_embedded_api_error_instead_of_key_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={"error": {"message": "No compatible free endpoints available"}},
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = OpenRouterAiProvider(
            "sk-or-v1-test",
            ("openrouter/free",),
            strict_privacy=False,
            client=client,
        )
        with pytest.raises(AiUnavailableError, match="No compatible free endpoints"):
            await provider.chat([ChatMessage(role="user", content="Ciao")], [])


@pytest.mark.anyio
async def test_openrouter_free_retries_invalid_json_once() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        content = (
            "User Safety: safe"
            if calls == 1
            else '{"message":"Risposta recuperata","action":"none"}'
        )
        return httpx.Response(200, json={"choices": [{"message": {"content": content}}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = OpenRouterAiProvider(
            "sk-or-v1-test",
            ("openrouter/free",),
            strict_privacy=False,
            client=client,
        )
        result = await provider.chat([ChatMessage(role="user", content="Ciao")], [])

    assert calls == 2
    assert result.message == "Risposta recuperata"
