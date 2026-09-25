from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator

ShortText = Annotated[str, Field(min_length=1, max_length=200)]


class Difficulty(StrEnum):
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"


class RecipeSource(BaseModel):
    model_config = ConfigDict(extra="forbid")

    type: Literal["manual", "ai", "website", "video", "book", "other"] = "manual"
    url: HttpUrl | None = None
    title: str | None = Field(default=None, max_length=300)
    author: str | None = Field(default=None, max_length=200)
    accessed_at: datetime | None = None
    license_note: str | None = Field(default=None, max_length=500)


class Ingredient(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID = Field(default_factory=uuid4)
    group: str | None = Field(default=None, max_length=120)
    name: ShortText
    quantity: Decimal | None = Field(default=None, ge=0)
    unit: str | None = Field(default=None, max_length=40)
    quantity_text: str | None = Field(default=None, max_length=80)
    preparation: str | None = Field(default=None, max_length=300)
    optional: bool = False
    scalable: bool = True
    sort_order: int = Field(default=0, ge=0)
    original_text: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def quantity_or_text(self) -> Ingredient:
        if self.quantity is None and not self.quantity_text:
            self.scalable = False
        return self


class RecipeStep(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: UUID = Field(default_factory=uuid4)
    title: str | None = Field(default=None, max_length=200)
    instruction: str = Field(min_length=1, max_length=5000)
    duration_minutes: int | None = Field(default=None, ge=0, le=1440)
    temperature_celsius: int | None = Field(default=None, ge=-50, le=500)
    sort_order: int = Field(default=0, ge=0)


class RecipeBase(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    title: ShortText
    description: str | None = Field(default=None, max_length=2000)
    category_id: UUID | None = None
    cuisine: str | None = Field(default=None, max_length=100)
    difficulty: Difficulty | None = None
    base_servings: Decimal = Field(default=4, gt=0, le=10000)
    serving_unit: str = Field(default="persone", min_length=1, max_length=40)
    prep_time_minutes: int | None = Field(default=None, ge=0, le=10080)
    cook_time_minutes: int | None = Field(default=None, ge=0, le=10080)
    rest_time_minutes: int | None = Field(default=None, ge=0, le=10080)
    ingredients: list[Ingredient] = Field(min_length=1, max_length=300)
    steps: list[RecipeStep] = Field(min_length=1, max_length=200)
    equipment: list[str] = Field(default_factory=list, max_length=100)
    tags: list[str] = Field(default_factory=list, max_length=100)
    dietary_labels: list[str] = Field(default_factory=list, max_length=100)
    allergens: list[str] = Field(default_factory=list, max_length=100)
    notes: str | None = Field(default=None, max_length=10000)
    source: RecipeSource | None = None
    favorite: bool = False

    @field_validator("equipment", "tags", "dietary_labels", "allergens")
    @classmethod
    def clean_string_lists(cls, values: list[str]) -> list[str]:
        result: list[str] = []
        seen: set[str] = set()
        for raw in values:
            value = raw.strip()
            key = value.casefold()
            if value and key not in seen:
                seen.add(key)
                result.append(value[:100])
        return result

    @model_validator(mode="after")
    def normalize_order(self) -> RecipeBase:
        for index, ingredient in enumerate(self.ingredients):
            ingredient.sort_order = index
        for index, step in enumerate(self.steps):
            step.sort_order = index
        return self


class RecipeCreate(RecipeBase):
    pass


class RecipeReplace(RecipeBase):
    revision: int = Field(ge=1)


class Recipe(RecipeBase):
    id: UUID
    schema_version: int = 1
    slug: str
    has_cover: bool = False
    revision: int
    created_at: datetime
    updated_at: datetime
    deleted_at: datetime | None = None


class RecipeSummary(BaseModel):
    id: UUID
    title: str
    slug: str
    description: str | None
    category_id: UUID | None
    category_name: str | None
    difficulty: Difficulty | None
    base_servings: Decimal
    serving_unit: str
    total_time_minutes: int | None
    tags: list[str]
    favorite: bool
    has_cover: bool
    revision: int
    updated_at: datetime
    deleted_at: datetime | None = None


class RecipePage(BaseModel):
    items: list[RecipeSummary]
    total: int
    limit: int
    offset: int


class CategoryCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    name: ShortText
    color: str | None = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")


class Category(CategoryCreate):
    id: UUID
    slug: str
    sort_order: int


class Tag(BaseModel):
    id: UUID
    name: str


class HealthStatus(BaseModel):
    status: Literal["ok"] = "ok"
    database: Literal["ok"] = "ok"
    ai_configured: bool
    version: str


class ChatMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=20000)


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    messages: list[ChatMessage] = Field(min_length=1, max_length=30)
    recipe_id: UUID | None = None


class AiProposalView(BaseModel):
    id: UUID
    kind: Literal["create", "update", "delete"]
    recipe_id: UUID | None = None
    base_revision: int | None = None
    rationale: str | None = None
    preview: RecipeCreate | None = None
    changed_fields: list[str] = Field(default_factory=list)
    status: Literal["pending", "applied", "rejected", "expired"] = "pending"


class ChatResponse(BaseModel):
    message: str
    referenced_recipe_ids: list[UUID] = Field(default_factory=list)
    proposal: AiProposalView | None = None


class ProposalApplyResult(BaseModel):
    status: Literal["applied"] = "applied"
    kind: Literal["create", "update", "delete"]
    recipe: Recipe | None = None


class ApiError(BaseModel):
    detail: str


class ImportArchive(BaseModel):
    model_config = ConfigDict(extra="ignore")

    export_version: Literal[1]
    categories: list[Category] = Field(default_factory=list, max_length=500)
    recipes: list[dict] = Field(max_length=10000)


class ImportResult(BaseModel):
    imported_recipes: int
    imported_categories: int
