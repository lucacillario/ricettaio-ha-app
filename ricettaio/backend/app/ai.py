from __future__ import annotations

import json
import logging
import re
from abc import ABC, abstractmethod
from typing import Any, Literal

import httpx
from pydantic import BaseModel, Field

from .config import Settings
from .domain import ChatMessage, ChatResponse, Recipe, RecipeCreate, RecipeSource
from .repository import RecipeRepository

logger = logging.getLogger(__name__)


def sanitize_gemini_schema(schema: Any) -> Any:
    """Recursively sanitize a JSON Schema dictionary for the Gemini SDK and API.

    The Gemini SDK Schema model (google.genai.types.Schema) and the Gemini API
    REST endpoint reject JSON Schema keywords not supported in the Gemini schema
    specification (such as exclusiveMinimum, exclusiveMaximum, additionalProperties,
    $schema, and examples). This function normalizes or removes them so that
    both SDK validation and Gemini API payload validation succeed, while full
    domain validation is maintained when parsing the model response.
    """
    if isinstance(schema, dict):
        cleaned: dict[str, Any] = {}
        for key, value in schema.items():
            if key in {"additionalProperties", "additional_properties"}:
                continue
            if key == "exclusiveMinimum":
                if (
                    isinstance(value, (int, float))
                    and not isinstance(value, bool)
                    and "minimum" not in schema
                ):
                    cleaned["minimum"] = value
                continue
            if key == "exclusiveMaximum":
                if (
                    isinstance(value, (int, float))
                    and not isinstance(value, bool)
                    and "maximum" not in schema
                ):
                    cleaned["maximum"] = value
                continue
            if key in {"$schema", "examples"}:
                continue
            cleaned[key] = sanitize_gemini_schema(value)
        return cleaned
    if isinstance(schema, list):
        return [sanitize_gemini_schema(item) for item in schema]
    return schema


def gemini_response_schema(model_cls: type[BaseModel]) -> dict[str, Any]:
    return sanitize_gemini_schema(model_cls.model_json_schema())


def parse_gemini_response[TModel: BaseModel](response: Any, model_cls: type[TModel]) -> TModel:
    if isinstance(getattr(response, "parsed", None), model_cls):
        return response.parsed
    if isinstance(getattr(response, "parsed", None), dict):
        return model_cls.model_validate(response.parsed)
    text = getattr(response, "text", "") or ""
    cleaned = text.strip()
    match = re.match(r"^```(?:json)?\s*([\s\S]*?)\s*```$", cleaned)
    if match:
        cleaned = match.group(1).strip()
    return model_cls.model_validate_json(cleaned)


class AiUnavailableError(RuntimeError):
    pass


def gemini_error(error: Exception) -> AiUnavailableError:
    message = getattr(error, "message", None) or str(error) or type(error).__name__
    message = re.sub(r"AIza[0-9A-Za-z_-]+", "[API_KEY_REDACTED]", message)
    message = " ".join(message.split())[:800]
    detail = f"Gemini {type(error).__name__}: {message}"
    logger.warning(detail)
    return AiUnavailableError(detail)


def openrouter_error(error: Exception) -> AiUnavailableError:
    message = getattr(error, "message", None) or str(error) or type(error).__name__
    message = re.sub(r"sk-or-v1-[0-9A-Za-z_-]+", "[API_KEY_REDACTED]", message)
    message = " ".join(message.split())[:800]
    detail = f"OpenRouter {type(error).__name__}: {message}"
    logger.warning(detail)
    return AiUnavailableError(detail)


class AiAnswer(BaseModel):
    message: str = Field(min_length=1, max_length=20000)
    referenced_recipe_ids: list[str] = Field(default_factory=list)
    action: Literal["none", "create", "update", "delete"] = "none"
    target_recipe_id: str | None = None
    proposed_recipe: RecipeCreate | None = None
    rationale: str | None = None


class ProviderChatResult(BaseModel):
    message: str
    referenced_recipe_ids: list[str] = Field(default_factory=list)
    action: Literal["none", "create", "update", "delete"] = "none"
    target_recipe_id: str | None = None
    proposed_recipe: RecipeCreate | None = None
    rationale: str | None = None


class AiProvider(ABC):
    @abstractmethod
    async def chat(self, messages: list[ChatMessage], recipes: list[Recipe]) -> ProviderChatResult:
        raise NotImplementedError

    @abstractmethod
    async def create_draft(self, prompt: str) -> RecipeCreate:
        raise NotImplementedError


class FakeAiProvider(AiProvider):
    async def chat(self, messages: list[ChatMessage], recipes: list[Recipe]) -> ProviderChatResult:
        request = messages[-1].content.casefold()
        if recipes and any(word in request for word in ("elimina", "cancella")):
            target = recipes[0]
            return ProviderChatResult(
                message=f"Posso spostare “{target.title}” nel cestino dopo la tua conferma.",
                referenced_recipe_ids=[str(target.id)],
                action="delete",
                target_recipe_id=str(target.id),
                rationale="Eliminazione richiesta nella conversazione",
            )
        if recipes and any(word in request for word in ("variante", "modifica", "sostituisci")):
            target = recipes[0]
            proposed = recipe_to_create(target)
            proposed.notes = "\n".join(
                part for part in [proposed.notes, "Variante proposta dall'assistente."] if part
            )
            return ProviderChatResult(
                message=(
                    f"Ho preparato una modifica di “{target.title}”. Controlla i campi "
                    "cambiati prima di applicarla."
                ),
                referenced_recipe_ids=[str(target.id)],
                action="update",
                target_recipe_id=str(target.id),
                proposed_recipe=proposed,
                rationale="Aggiunta una nota che identifica la variante proposta",
            )
        if any(word in request for word in ("crea", "nuova ricetta")):
            draft = await self.create_draft(messages[-1].content)
            return ProviderChatResult(
                message=(
                    "Ho preparato una nuova ricetta come proposta. "
                    "Verificala prima di salvarla."
                ),
                action="create",
                proposed_recipe=draft,
                rationale="Nuova ricetta richiesta nella conversazione",
            )
        if recipes:
            titles = ", ".join(recipe.title for recipe in recipes)
            return ProviderChatResult(
                message=(
                    f"Ho consultato {titles}. Posso confrontare queste ricette, suggerire una "
                    "variante o preparare una proposta modificabile."
                ),
                referenced_recipe_ids=[str(recipe.id) for recipe in recipes],
            )
        return ProviderChatResult(
            message=(
                "Non ho trovato una ricetta pertinente nell'archivio. Posso comunque aiutarti "
                "a prepararne una nuova come bozza."
            )
        )

    async def create_draft(self, prompt: str) -> RecipeCreate:
        return RecipeCreate.model_validate(
            {
                "title": "Bozza generata",
                "description": f"Bozza di sviluppo per: {prompt[:300]}",
                "base_servings": "4",
                "serving_unit": "persone",
                "ingredients": [{"name": "ingrediente da definire", "quantity_text": "q.b."}],
                "steps": [{"instruction": "Completa e verifica questa bozza prima di salvarla."}],
                "source": {"type": "ai"},
            }
        )


class GeminiAiProvider(AiProvider):
    def __init__(self, api_key: str, model: str) -> None:
        if not api_key:
            raise AiUnavailableError("La chiave Gemini non è configurata")
        if not model:
            raise AiUnavailableError("Il modello Gemini non è configurato")
        try:
            from google import genai
        except ImportError as error:  # pragma: no cover - dependency/runtime guard
            raise AiUnavailableError("SDK Gemini non disponibile") from error
        self.client = genai.Client(api_key=api_key)
        self.model = model

    async def chat(self, messages: list[ChatMessage], recipes: list[Recipe]) -> ProviderChatResult:
        try:
            from google.genai import types

            context = [recipe.model_dump(mode="json") for recipe in recipes]
            transcript = "\n".join(f"{item.role}: {item.content}" for item in messages)
            prompt = f"""
Sei l'assistente di RicettAIo. Rispondi in italiano in modo pratico e prudente.
Usa come fatti sulle ricette locali soltanto il contesto JSON fornito.
Non dichiarare di avere salvato, modificato o eliminato dati.
Se l'utente chiede esplicitamente una creazione, modifica o eliminazione, restituisci
l'azione corrispondente. Per create/update, proposed_recipe deve contenere la ricetta
completa. Per update/delete, target_recipe_id deve essere uno degli ID nel contesto.
Altrimenti usa action=none. Ogni azione sarà soltanto una proposta da confermare.
Per allergie, conservazione e sicurezza alimentare invita a verificare fonti affidabili.

RICETTE LOCALI:
{json.dumps(context, ensure_ascii=False)}

CONVERSAZIONE:
{transcript}
"""
            response = await self.client.aio.models.generate_content(
                model=self.model,
                contents=prompt,
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=gemini_response_schema(AiAnswer),
                    temperature=0.3,
                ),
            )
            parsed = parse_gemini_response(response, AiAnswer)
            allowed_ids = {str(recipe.id) for recipe in recipes}
            references = [
                recipe_id for recipe_id in parsed.referenced_recipe_ids if recipe_id in allowed_ids
            ]
            return ProviderChatResult(
                message=parsed.message,
                referenced_recipe_ids=references,
                action=parsed.action,
                target_recipe_id=parsed.target_recipe_id,
                proposed_recipe=parsed.proposed_recipe,
                rationale=parsed.rationale,
            )
        except Exception as error:
            raise gemini_error(error) from error

    async def create_draft(self, prompt: str) -> RecipeCreate:
        try:
            from google.genai import types

            response = await self.client.aio.models.generate_content(
                model=self.model,
                contents=(
                    "Crea una bozza di ricetta in italiano dalla richiesta seguente. "
                    "Non inventare allergeni come certezza e usa quantità culinarie plausibili. "
                    f"La fonte deve essere di tipo ai. Richiesta: {prompt}"
                ),
                config=types.GenerateContentConfig(
                    response_mime_type="application/json",
                    response_schema=gemini_response_schema(RecipeCreate),
                    temperature=0.4,
                ),
            )
            draft = parse_gemini_response(response, RecipeCreate)
            draft.source = RecipeSource(type="ai")
            return draft
        except Exception as error:
            raise gemini_error(error) from error


class OpenRouterAiProvider(AiProvider):
    endpoint = "https://openrouter.ai/api/v1/chat/completions"

    def __init__(
        self,
        api_key: str,
        models: tuple[str, ...],
        strict_privacy: bool = True,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        if not api_key:
            raise AiUnavailableError("La chiave OpenRouter non è configurata")
        if not models:
            raise AiUnavailableError("Non è configurato alcun modello OpenRouter")
        self.api_key = api_key
        self.models = models
        self.strict_privacy = strict_privacy
        self.client = client

    async def chat(self, messages: list[ChatMessage], recipes: list[Recipe]) -> ProviderChatResult:
        context = [recipe.model_dump(mode="json") for recipe in recipes]
        transcript = "\n".join(f"{item.role}: {item.content}" for item in messages)
        prompt = f"""
Sei l'assistente di RicettAIo. Rispondi in italiano in modo pratico e prudente.
Usa come fatti sulle ricette locali soltanto il contesto JSON fornito.
Non dichiarare di avere salvato, modificato o eliminato dati.
Se l'utente chiede esplicitamente una creazione, modifica o eliminazione, restituisci
l'azione corrispondente. Per create/update, proposed_recipe deve contenere la ricetta
completa. Per update/delete, target_recipe_id deve essere uno degli ID nel contesto.
Altrimenti usa action=none. Ogni azione sarà soltanto una proposta da confermare.
Per allergie, conservazione e sicurezza alimentare invita a verificare fonti affidabili.

RICETTE LOCALI:
{json.dumps(context, ensure_ascii=False)}

CONVERSAZIONE:
{transcript}
"""
        parsed = await self._structured_completion(prompt, AiAnswer, "ricettaio_answer", 0.3)
        allowed_ids = {str(recipe.id) for recipe in recipes}
        return ProviderChatResult(
            message=parsed.message,
            referenced_recipe_ids=[
                recipe_id
                for recipe_id in parsed.referenced_recipe_ids
                if recipe_id in allowed_ids
            ],
            action=parsed.action,
            target_recipe_id=parsed.target_recipe_id,
            proposed_recipe=parsed.proposed_recipe,
            rationale=parsed.rationale,
        )

    async def create_draft(self, prompt: str) -> RecipeCreate:
        instruction = (
            "Crea una bozza di ricetta in italiano dalla richiesta seguente. "
            "Non inventare allergeni come certezza e usa quantità culinarie plausibili. "
            f"La fonte deve essere di tipo ai. Richiesta: {prompt}"
        )
        draft = await self._structured_completion(
            instruction, RecipeCreate, "ricettaio_recipe", 0.4
        )
        draft.source = RecipeSource(type="ai")
        return draft

    async def _structured_completion[TModel: BaseModel](
        self,
        prompt: str,
        model_cls: type[TModel],
        schema_name: str,
        temperature: float,
    ) -> TModel:
        payload: dict[str, Any] = {
            "models": list(self.models),
            "messages": [{"role": "user", "content": prompt}],
            "temperature": temperature,
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": schema_name,
                    "strict": True,
                    "schema": model_cls.model_json_schema(),
                },
            },
            "provider": {
                "require_parameters": True,
            },
        }
        if self.strict_privacy:
            payload["provider"].update({"data_collection": "deny", "zdr": True})
        try:
            response = await self._post(payload)
            if response.status_code >= 400:
                try:
                    error_body = response.json()
                    message = error_body.get("error", {}).get("message") or response.text
                except (ValueError, AttributeError):
                    message = response.text
                raise RuntimeError(f"HTTP {response.status_code}: {message[:600]}")
            body = response.json()
            content = body["choices"][0]["message"]["content"]
            if isinstance(content, list):
                content = "".join(
                    str(item.get("text", "")) for item in content if isinstance(item, dict)
                )
            return model_cls.model_validate_json(content)
        except AiUnavailableError:
            raise
        except Exception as error:
            raise openrouter_error(error) from error

    async def _post(self, payload: dict[str, Any]) -> httpx.Response:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
            "HTTP-Referer": "https://github.com/lucacillario/ricettaio-ha-app",
            "X-Title": "RicettAIo",
        }
        if self.client is not None:
            return await self.client.post(self.endpoint, headers=headers, json=payload)
        async with httpx.AsyncClient(timeout=90) as client:
            return await client.post(self.endpoint, headers=headers, json=payload)

class AiService:
    def __init__(
        self, settings: Settings, repository: RecipeRepository, provider: AiProvider | None = None
    ) -> None:
        self.settings = settings
        self.repository = repository
        self._provider = provider

    @property
    def configured(self) -> bool:
        if not self.settings.ai_enabled:
            return False
        if self.settings.ai_provider == "fake":
            return True
        if self.settings.ai_provider == "openrouter":
            return bool(self.settings.openrouter_api_key and self.settings.openrouter_models)
        if self.settings.ai_provider == "gemini":
            return bool(self.settings.gemini_api_key and self.settings.gemini_model)
        return False

    async def chat(self, messages: list[ChatMessage], recipe_id: str | None) -> ChatResponse:
        provider = self._get_provider()
        if recipe_id:
            recipes = [self.repository.get_recipe(recipe_id)]
        else:
            query = messages[-1].content
            page = self.repository.list_recipes(query=query, limit=5)
            if not page.items:
                page = self.repository.list_recipes(limit=3)
            recipes = [self.repository.get_recipe(item.id) for item in page.items]
        result = await provider.chat(messages, recipes)
        allowed = {str(recipe.id): recipe for recipe in recipes}
        references = [
            recipe_id for recipe_id in result.referenced_recipe_ids if recipe_id in allowed
        ]
        proposal = None
        if result.action == "create" and result.proposed_recipe is not None:
            proposal = self.repository.create_ai_proposal(
                kind="create",
                preview=result.proposed_recipe,
                recipe_id=None,
                base_revision=None,
                rationale=result.rationale,
                changed_fields=list(result.proposed_recipe.model_fields_set),
            )
        elif result.action in {"update", "delete"} and result.target_recipe_id in allowed:
            target = allowed[result.target_recipe_id]
            preview = result.proposed_recipe if result.action == "update" else None
            if result.action == "delete" or preview is not None:
                proposal = self.repository.create_ai_proposal(
                    kind=result.action,
                    preview=preview,
                    recipe_id=target.id,
                    base_revision=target.revision,
                    rationale=result.rationale,
                    changed_fields=changed_fields(target, preview) if preview else [],
                )
        return ChatResponse(
            message=result.message,
            referenced_recipe_ids=references,
            proposal=proposal,
        )

    async def create_draft(self, prompt: str) -> RecipeCreate:
        return await self._get_provider().create_draft(prompt)

    def _get_provider(self) -> AiProvider:
        if not self.settings.ai_enabled:
            raise AiUnavailableError("Le funzioni AI sono disabilitate")
        if self._provider:
            return self._provider
        if self.settings.ai_provider == "fake":
            self._provider = FakeAiProvider()
        elif self.settings.ai_provider == "openrouter":
            self._provider = OpenRouterAiProvider(
                self.settings.openrouter_api_key,
                self.settings.openrouter_models,
                self.settings.openrouter_strict_privacy,
            )
        elif self.settings.ai_provider == "gemini":
            self._provider = GeminiAiProvider(
                self.settings.gemini_api_key, self.settings.gemini_model
            )
        else:
            raise AiUnavailableError(f"Provider AI non supportato: {self.settings.ai_provider}")
        return self._provider


def recipe_to_create(recipe: Recipe) -> RecipeCreate:
    return RecipeCreate.model_validate(
        recipe.model_dump(
            exclude={
                "id",
                "schema_version",
                "slug",
                "has_cover",
                "revision",
                "created_at",
                "updated_at",
                "deleted_at",
            }
        )
    )


def changed_fields(recipe: Recipe, proposal: RecipeCreate) -> list[str]:
    current = recipe_to_create(recipe).model_dump(mode="json")
    proposed = proposal.model_dump(mode="json")
    return [key for key in current if current[key] != proposed[key]]
