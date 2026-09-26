from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated, Any
from uuid import UUID

from fastapi import (
    Body,
    FastAPI,
    File,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
)
from fastapi.exception_handlers import http_exception_handler
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .ai import AiService, AiUnavailableError
from .config import Settings
from .database import Database
from .domain import (
    Category,
    CategoryCreate,
    ChatRequest,
    ChatResponse,
    HealthStatus,
    ImportArchive,
    ImportResult,
    ProposalApplyResult,
    Recipe,
    RecipeCreate,
    RecipePage,
    RecipeReplace,
    Tag,
)
from .images import ImageStore, InvalidImageError
from .repository import ConflictError, NotFoundError, RecipeRepository

APP_VERSION = os.getenv("RICETTAIO_VERSION", "0.2.0")


class DraftRequest(BaseModel):
    prompt: str = Field(min_length=3, max_length=10000)


class DeleteRequest(BaseModel):
    revision: int | None = Field(default=None, ge=1)


def create_app(settings: Settings | None = None) -> FastAPI:
    active_settings = settings or Settings.from_env()
    database = Database(active_settings.database_path)
    repository = RecipeRepository(database)
    image_store = ImageStore(active_settings.uploads_dir)
    ai_service = AiService(active_settings, repository)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        active_settings.data_dir.mkdir(parents=True, exist_ok=True)
        active_settings.uploads_dir.mkdir(parents=True, exist_ok=True)
        database.initialize()
        expired_files = repository.purge_expired(active_settings.trash_retention_days)
        image_store.delete_files(*expired_files)
        app.state.settings = active_settings
        app.state.repository = repository
        app.state.ai_service = ai_service
        yield

    app = FastAPI(
        title="RicettAIo API",
        version=APP_VERSION,
        docs_url="/api/docs",
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
    )

    @app.middleware("http")
    async def security_middleware(request: Request, call_next: Any) -> Response:
        if (
            active_settings.strict_ingress
            and request.client
            and request.client.host not in {"172.30.32.2", "127.0.0.1", "::1"}
        ):
            return JSONResponse(status_code=403, content={"detail": "Accesso solo via Ingress"})
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "same-origin"
        response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
        return response

    @app.exception_handler(NotFoundError)
    async def not_found_handler(_: Request, error: NotFoundError) -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": str(error)})

    @app.exception_handler(ConflictError)
    async def conflict_handler(_: Request, error: ConflictError) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": str(error)})

    @app.exception_handler(AiUnavailableError)
    async def ai_error_handler(_: Request, error: AiUnavailableError) -> JSONResponse:
        return JSONResponse(status_code=503, content={"detail": str(error)})

    @app.exception_handler(HTTPException)
    async def custom_http_exception_handler(request: Request, error: HTTPException) -> Response:
        return await http_exception_handler(request, error)

    @app.get("/api/v1/health", response_model=HealthStatus)
    async def health() -> HealthStatus:
        database.check()
        return HealthStatus(ai_configured=ai_service.configured, version=APP_VERSION)

    @app.get("/api/v1/categories", response_model=list[Category])
    async def categories() -> list[Category]:
        return repository.list_categories()

    @app.post("/api/v1/categories", response_model=Category, status_code=201)
    async def create_category(payload: CategoryCreate) -> Category:
        return repository.create_category(payload)

    @app.get("/api/v1/tags", response_model=list[Tag])
    async def tags() -> list[Tag]:
        return repository.list_tags()

    @app.get("/api/v1/recipes", response_model=RecipePage)
    async def list_recipes(
        q: str | None = Query(default=None, max_length=300),
        category_id: UUID | None = None,
        tag: str | None = Query(default=None, max_length=100),
        difficulty: str | None = Query(default=None, pattern="^(easy|medium|hard)$"),
        max_time: int | None = Query(default=None, ge=0, le=10080),
        favorite: bool | None = None,
        deleted: bool = False,
        sort: str = Query(default="updated_desc"),
        limit: int = Query(default=50, ge=1, le=200),
        offset: int = Query(default=0, ge=0),
    ) -> RecipePage:
        return repository.list_recipes(
            query=q,
            category_id=category_id,
            tag=tag,
            difficulty=difficulty,
            max_time=max_time,
            favorite=favorite,
            deleted=deleted,
            sort=sort,
            limit=limit,
            offset=offset,
        )

    @app.post("/api/v1/recipes", response_model=Recipe, status_code=201)
    async def create_recipe(payload: RecipeCreate) -> Recipe:
        return repository.create_recipe(payload)

    @app.get("/api/v1/recipes/{recipe_id}", response_model=Recipe)
    async def get_recipe(recipe_id: UUID) -> Recipe:
        return repository.get_recipe(recipe_id)

    @app.put("/api/v1/recipes/{recipe_id}", response_model=Recipe)
    async def replace_recipe(recipe_id: UUID, payload: RecipeReplace) -> Recipe:
        return repository.replace_recipe(recipe_id, payload)

    @app.post("/api/v1/recipes/{recipe_id}/duplicate", response_model=Recipe, status_code=201)
    async def duplicate_recipe(recipe_id: UUID) -> Recipe:
        return repository.duplicate_recipe(recipe_id)

    @app.delete("/api/v1/recipes/{recipe_id}", status_code=204)
    async def delete_recipe(
        recipe_id: UUID, payload: Annotated[DeleteRequest | None, Body()] = None
    ) -> Response:
        repository.soft_delete(recipe_id, payload.revision if payload else None)
        return Response(status_code=204)

    @app.post("/api/v1/recipes/{recipe_id}/restore", response_model=Recipe)
    async def restore_recipe(recipe_id: UUID) -> Recipe:
        return repository.restore(recipe_id)

    @app.get("/api/v1/recipes/{recipe_id}/revisions")
    async def recipe_revisions(recipe_id: UUID) -> list[dict[str, Any]]:
        return repository.get_revision_history(recipe_id)

    @app.post("/api/v1/recipes/{recipe_id}/cover", response_model=Recipe)
    async def upload_cover(
        recipe_id: UUID, image: Annotated[UploadFile, File(description="JPEG, PNG o WebP")]
    ) -> Recipe:
        old_full, old_thumb = repository.get_cover_files(recipe_id)
        try:
            full, thumb = await image_store.save_cover(str(recipe_id), image)
        except InvalidImageError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        try:
            recipe = repository.set_cover(recipe_id, full, thumb)
        except Exception:
            image_store.delete_files(full, thumb)
            raise
        image_store.delete_files(old_full, old_thumb)
        return recipe

    @app.delete("/api/v1/recipes/{recipe_id}/cover", response_model=Recipe)
    async def delete_cover(recipe_id: UUID) -> Recipe:
        old_full, old_thumb = repository.get_cover_files(recipe_id)
        recipe = repository.set_cover(recipe_id, None, None)
        image_store.delete_files(old_full, old_thumb)
        return recipe

    @app.get("/api/v1/recipes/{recipe_id}/cover")
    async def cover(recipe_id: UUID, thumbnail: bool = False) -> Response:
        path = repository.get_cover_path(recipe_id, thumbnail)
        return Response(
            content=path.read_bytes(),
            media_type="image/webp",
            headers={"Cache-Control": "private, max-age=3600"},
        )

    @app.post("/api/v1/ai/chat", response_model=ChatResponse)
    async def ai_chat(payload: ChatRequest) -> ChatResponse:
        return await ai_service.chat(
            payload.messages, str(payload.recipe_id) if payload.recipe_id else None
        )

    @app.post("/api/v1/ai/chat/stream")
    async def ai_chat_stream(payload: ChatRequest) -> StreamingResponse:
        answer = await ai_service.chat(
            payload.messages, str(payload.recipe_id) if payload.recipe_id else None
        )

        async def events() -> AsyncIterator[str]:
            yield f"event: message\ndata: {answer.model_dump_json()}\n\n"
            yield "event: done\ndata: {}\n\n"

        return StreamingResponse(events(), media_type="text/event-stream")

    @app.post("/api/v1/ai/drafts", response_model=RecipeCreate)
    async def create_ai_draft(payload: DraftRequest) -> RecipeCreate:
        return await ai_service.create_draft(payload.prompt)

    @app.post("/api/v1/ai/proposals/{proposal_id}/apply", response_model=ProposalApplyResult)
    async def apply_ai_proposal(proposal_id: UUID) -> ProposalApplyResult:
        kind, recipe = repository.apply_ai_proposal(proposal_id)
        return ProposalApplyResult(kind=kind, recipe=recipe)

    @app.delete("/api/v1/ai/proposals/{proposal_id}", status_code=204)
    async def reject_ai_proposal(proposal_id: UUID) -> Response:
        repository.reject_ai_proposal(proposal_id)
        return Response(status_code=204)

    @app.get("/api/v1/export")
    async def export_recipes() -> JSONResponse:
        page = repository.list_recipes(limit=10000, offset=0)
        recipes = [repository.get_recipe(item.id) for item in page.items]
        content = {
            "export_version": 1,
            "app_version": APP_VERSION,
            "categories": [
                category.model_dump(mode="json") for category in repository.list_categories()
            ],
            "recipes": [recipe.model_dump(mode="json") for recipe in recipes],
        }
        return JSONResponse(
            content=content,
            headers={"Content-Disposition": 'attachment; filename="ricettaio-export.json"'},
        )

    @app.post("/api/v1/import", response_model=ImportResult)
    async def import_recipes(payload: ImportArchive) -> ImportResult:
        recipes: list[RecipeCreate] = []
        metadata = {
            "id",
            "schema_version",
            "slug",
            "has_cover",
            "revision",
            "created_at",
            "updated_at",
            "deleted_at",
        }
        for raw_recipe in payload.recipes:
            recipe_data = {key: value for key, value in raw_recipe.items() if key not in metadata}
            recipes.append(RecipeCreate.model_validate(recipe_data))
        imported_recipes, imported_categories = repository.import_archive(
            payload.categories, recipes
        )
        return ImportResult(
            imported_recipes=imported_recipes,
            imported_categories=imported_categories,
        )

    frontend_dir = active_settings.frontend_dir
    if frontend_dir and frontend_dir.is_dir():
        assets_dir = frontend_dir / "assets"
        if assets_dir.is_dir():
            app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

        @app.get("/{path:path}", include_in_schema=False)
        async def spa(path: str) -> FileResponse:
            candidate = (frontend_dir / path).resolve()
            if path and candidate.is_file() and frontend_dir.resolve() in candidate.parents:
                headers = {"Cache-Control": "no-store"} if candidate.name == "index.html" else None
                return FileResponse(candidate, headers=headers)
            return FileResponse(
                frontend_dir / "index.html",
                headers={"Cache-Control": "no-store"},
            )

    return app


app = create_app()
