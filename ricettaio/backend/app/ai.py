from __future__ import annotations

import json
from abc import ABC, abstractmethod
from typing import Literal

from pydantic import BaseModel, Field

from .config import Settings
from .domain import ChatMessage, ChatResponse, Recipe, RecipeCreate, RecipeSource
from .repository import RecipeRepository


class AiUnavailableError(RuntimeError):
    pass


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
                    response_schema=AiAnswer,
                    temperature=0.3,
                ),
            )
            parsed = response.parsed or AiAnswer.model_validate_json(response.text)
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
        except Exception as error:  # API errors are intentionally normalized
            raise AiUnavailableError(f"Gemini non è disponibile: {type(error).__name__}") from error

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
                    response_schema=RecipeCreate,
                    temperature=0.4,
                ),
            )
            draft = response.parsed or RecipeCreate.model_validate_json(response.text)
            draft.source = RecipeSource(type="ai")
            return draft
        except Exception as error:
            raise AiUnavailableError(f"Gemini non è disponibile: {type(error).__name__}") from error


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
        return bool(self.settings.gemini_api_key and self.settings.gemini_model)

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
        else:
            self._provider = GeminiAiProvider(
                self.settings.gemini_api_key, self.settings.gemini_model
            )
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
