from __future__ import annotations

import json
import re
import sqlite3
import unicodedata
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from .database import Database
from .domain import (
    AiProposalView,
    Category,
    CategoryCreate,
    Ingredient,
    Recipe,
    RecipeCreate,
    RecipePage,
    RecipeReplace,
    RecipeSource,
    RecipeStep,
    RecipeSummary,
    Tag,
)


class NotFoundError(Exception):
    pass


class ConflictError(Exception):
    pass


def utc_now() -> str:
    return datetime.now(UTC).isoformat()


def slugify(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_value = normalized.encode("ascii", "ignore").decode("ascii").lower()
    return re.sub(r"[^a-z0-9]+", "-", ascii_value).strip("-") or "ricetta"


class RecipeRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def list_categories(self) -> list[Category]:
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT id, name, slug, color, sort_order FROM categories ORDER BY sort_order, name"
            ).fetchall()
        return [Category.model_validate(dict(row)) for row in rows]

    def create_category(self, payload: CategoryCreate) -> Category:
        category_id = str(uuid4())
        base_slug = slugify(payload.name)
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                slug = self._unique_slug(connection, "categories", base_slug)
                next_order = connection.execute(
                    "SELECT COALESCE(MAX(sort_order), -1) + 1 FROM categories"
                ).fetchone()[0]
                connection.execute(
                    """
                    INSERT INTO categories(id, name, slug, color, sort_order)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (category_id, payload.name, slug, payload.color, next_order),
                )
                connection.commit()
            except sqlite3.IntegrityError as error:
                connection.rollback()
                raise ConflictError("Esiste già una categoria con questo nome") from error
        return Category(
            id=UUID(category_id),
            name=payload.name,
            slug=slug,
            color=payload.color,
            sort_order=next_order,
        )

    def list_tags(self) -> list[Tag]:
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT id, name FROM tags ORDER BY name COLLATE NOCASE"
            ).fetchall()
        return [Tag.model_validate(dict(row)) for row in rows]

    def create_recipe(self, payload: RecipeCreate, source: str = "manual") -> Recipe:
        recipe_id = str(uuid4())
        now = utc_now()
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                slug = self._unique_slug(connection, "recipes", slugify(payload.title))
                self._insert_recipe(connection, recipe_id, slug, payload, now)
                self._replace_children(connection, recipe_id, payload)
                recipe = self._get_recipe(connection, recipe_id, include_deleted=True)
                self._save_revision(connection, recipe, source, "Creazione")
                self._refresh_fts(connection, recipe_id)
                connection.commit()
                return recipe
            except Exception:
                connection.rollback()
                raise

    def replace_recipe(
        self, recipe_id: UUID | str, payload: RecipeReplace, source: str = "manual"
    ) -> Recipe:
        recipe_id = str(recipe_id)
        create_payload = RecipeCreate.model_validate(payload.model_dump(exclude={"revision"}))
        now = utc_now()
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                current = self._get_recipe(connection, recipe_id, include_deleted=False)
                if current.revision != payload.revision:
                    raise ConflictError(
                        "La ricetta è stata modificata. Ricaricala prima di salvare."
                    )
                connection.execute(
                    """
                    UPDATE recipes SET
                        title = ?, description = ?, category_id = ?, cuisine = ?, difficulty = ?,
                        base_servings = ?, serving_unit = ?, prep_time_minutes = ?,
                        cook_time_minutes = ?, rest_time_minutes = ?, equipment_json = ?,
                        dietary_labels_json = ?, allergens_json = ?, notes = ?, source_json = ?,
                        favorite = ?, revision = revision + 1, updated_at = ?
                    WHERE id = ? AND deleted_at IS NULL
                    """,
                    (create_payload.title,)
                    + self._recipe_values(create_payload)
                    + (now, recipe_id),
                )
                self._replace_children(connection, recipe_id, create_payload)
                recipe = self._get_recipe(connection, recipe_id, include_deleted=True)
                self._save_revision(connection, recipe, source, "Modifica")
                self._trim_revisions(connection, recipe_id)
                self._refresh_fts(connection, recipe_id)
                connection.commit()
                return recipe
            except Exception:
                connection.rollback()
                raise

    def duplicate_recipe(self, recipe_id: UUID | str) -> Recipe:
        original = self.get_recipe(recipe_id)
        payload = RecipeCreate.model_validate(
            original.model_dump(
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
        payload.title = f"{payload.title} (copia)"
        payload.source = payload.source or RecipeSource(type="manual")
        for ingredient in payload.ingredients:
            ingredient.id = uuid4()
        for step in payload.steps:
            step.id = uuid4()
        return self.create_recipe(payload)

    def get_recipe(self, recipe_id: UUID | str, include_deleted: bool = False) -> Recipe:
        with self.database.connect() as connection:
            return self._get_recipe(connection, str(recipe_id), include_deleted)

    def list_recipes(
        self,
        *,
        query: str | None = None,
        category_id: UUID | None = None,
        tag: str | None = None,
        difficulty: str | None = None,
        max_time: int | None = None,
        favorite: bool | None = None,
        deleted: bool = False,
        sort: str = "updated_desc",
        limit: int = 50,
        offset: int = 0,
    ) -> RecipePage:
        joins: list[str] = ["LEFT JOIN categories c ON c.id = r.category_id"]
        where: list[str] = ["r.deleted_at IS NOT NULL" if deleted else "r.deleted_at IS NULL"]
        parameters: list[Any] = []

        fts_query = self._fts_query(query)
        if fts_query:
            joins.append("JOIN recipe_fts ON recipe_fts.recipe_id = r.id")
            where.append("recipe_fts MATCH ?")
            parameters.append(fts_query)
        if category_id:
            where.append("r.category_id = ?")
            parameters.append(str(category_id))
        if tag:
            where.append(
                """EXISTS (
                    SELECT 1 FROM recipe_tags rt JOIN tags t ON t.id = rt.tag_id
                    WHERE rt.recipe_id = r.id AND t.name = ? COLLATE NOCASE
                )"""
            )
            parameters.append(tag)
        if difficulty:
            where.append("r.difficulty = ?")
            parameters.append(difficulty)
        if max_time is not None:
            where.append(
                "COALESCE(r.prep_time_minutes, 0) + COALESCE(r.cook_time_minutes, 0) "
                "+ COALESCE(r.rest_time_minutes, 0) <= ?"
            )
            parameters.append(max_time)
        if favorite is not None:
            where.append("r.favorite = ?")
            parameters.append(int(favorite))

        order_by = {
            "title_asc": "r.title COLLATE NOCASE ASC",
            "created_desc": "r.created_at DESC",
            "time_asc": "total_time_minutes ASC, r.title COLLATE NOCASE ASC",
            "updated_desc": "r.updated_at DESC",
        }.get(sort, "r.updated_at DESC")
        where_sql = " AND ".join(where)
        joins_sql = " ".join(joins)
        select_sql = f"""
            SELECT r.id, r.title, r.slug, r.description, r.category_id, c.name AS category_name,
                   r.difficulty, r.base_servings, r.serving_unit,
                   CASE WHEN r.prep_time_minutes IS NULL AND r.cook_time_minutes IS NULL
                             AND r.rest_time_minutes IS NULL THEN NULL
                        ELSE COALESCE(r.prep_time_minutes, 0) + COALESCE(r.cook_time_minutes, 0)
                             + COALESCE(r.rest_time_minutes, 0) END AS total_time_minutes,
                   r.favorite, r.cover_image IS NOT NULL AS has_cover, r.revision,
                   r.updated_at, r.deleted_at
            FROM recipes r {joins_sql}
            WHERE {where_sql}
            ORDER BY {order_by}
            LIMIT ? OFFSET ?
        """
        count_sql = f"SELECT COUNT(DISTINCT r.id) FROM recipes r {joins_sql} WHERE {where_sql}"

        with self.database.connect() as connection:
            total = int(connection.execute(count_sql, parameters).fetchone()[0])
            rows = connection.execute(select_sql, parameters + [limit, offset]).fetchall()
            items: list[RecipeSummary] = []
            for row in rows:
                data = dict(row)
                data["tags"] = self._get_tag_names(connection, data["id"])
                data["favorite"] = bool(data["favorite"])
                data["has_cover"] = bool(data["has_cover"])
                items.append(RecipeSummary.model_validate(data))
        return RecipePage(items=items, total=total, limit=limit, offset=offset)

    def soft_delete(self, recipe_id: UUID | str, revision: int | None = None) -> None:
        recipe_id = str(recipe_id)
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                current = self._get_recipe(connection, recipe_id, include_deleted=False)
                if revision is not None and revision != current.revision:
                    raise ConflictError("La ricetta è stata modificata prima dell'eliminazione")
                now = utc_now()
                connection.execute(
                    """
                    UPDATE recipes SET deleted_at = ?, updated_at = ?, revision = revision + 1
                    WHERE id = ?
                    """,
                    (now, now, recipe_id),
                )
                self._remove_fts(connection, recipe_id)
                connection.commit()
            except Exception:
                connection.rollback()
                raise

    def restore(self, recipe_id: UUID | str) -> Recipe:
        recipe_id = str(recipe_id)
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                self._get_recipe(connection, recipe_id, include_deleted=True)
                now = utc_now()
                cursor = connection.execute(
                    """
                    UPDATE recipes SET deleted_at = NULL, updated_at = ?, revision = revision + 1
                    WHERE id = ? AND deleted_at IS NOT NULL
                    """,
                    (now, recipe_id),
                )
                if cursor.rowcount == 0:
                    raise ConflictError("La ricetta non è nel cestino")
                recipe = self._get_recipe(connection, recipe_id, include_deleted=True)
                self._save_revision(connection, recipe, "manual", "Ripristino dal cestino")
                self._refresh_fts(connection, recipe_id)
                connection.commit()
                return recipe
            except Exception:
                connection.rollback()
                raise

    def purge_expired(self, retention_days: int) -> list[Path]:
        cutoff = (datetime.now(UTC) - timedelta(days=retention_days)).isoformat()
        files: list[Path] = []
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                rows = connection.execute(
                    """
                    SELECT id, cover_image, cover_thumbnail FROM recipes
                    WHERE deleted_at IS NOT NULL AND deleted_at < ?
                    """,
                    (cutoff,),
                ).fetchall()
                for row in rows:
                    if row["cover_image"]:
                        files.append(Path(row["cover_image"]))
                    if row["cover_thumbnail"]:
                        files.append(Path(row["cover_thumbnail"]))
                    connection.execute(
                        "DELETE FROM recipe_revisions WHERE recipe_id = ?", (row["id"],)
                    )
                    connection.execute("DELETE FROM recipes WHERE id = ?", (row["id"],))
                    self._remove_fts(connection, row["id"])
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        return files

    def set_cover(
        self, recipe_id: UUID | str, image: Path | None, thumbnail: Path | None
    ) -> Recipe:
        recipe_id = str(recipe_id)
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                self._get_recipe(connection, recipe_id, include_deleted=False)
                now = utc_now()
                connection.execute(
                    """
                    UPDATE recipes SET cover_image = ?, cover_thumbnail = ?,
                        updated_at = ?, revision = revision + 1 WHERE id = ?
                    """,
                    (
                        str(image) if image else None,
                        str(thumbnail) if thumbnail else None,
                        now,
                        recipe_id,
                    ),
                )
                recipe = self._get_recipe(connection, recipe_id, include_deleted=True)
                self._save_revision(connection, recipe, "manual", "Aggiornamento copertina")
                connection.commit()
                return recipe
            except Exception:
                connection.rollback()
                raise

    def get_cover_path(self, recipe_id: UUID | str, thumbnail: bool = False) -> Path:
        field = "cover_thumbnail" if thumbnail else "cover_image"
        with self.database.connect() as connection:
            row = connection.execute(
                f"SELECT {field} AS path FROM recipes WHERE id = ? AND deleted_at IS NULL",
                (str(recipe_id),),
            ).fetchone()
        if row is None or not row["path"]:
            raise NotFoundError("Immagine non trovata")
        path = Path(row["path"])
        if not path.is_file():
            raise NotFoundError("File immagine non trovato")
        return path

    def get_cover_files(self, recipe_id: UUID | str) -> tuple[Path | None, Path | None]:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT cover_image, cover_thumbnail FROM recipes WHERE id = ?",
                (str(recipe_id),),
            ).fetchone()
        if row is None:
            raise NotFoundError("Ricetta non trovata")
        return (
            Path(row["cover_image"]) if row["cover_image"] else None,
            Path(row["cover_thumbnail"]) if row["cover_thumbnail"] else None,
        )

    def get_revision_history(self, recipe_id: UUID | str) -> list[dict[str, Any]]:
        with self.database.connect() as connection:
            self._get_recipe(connection, str(recipe_id), include_deleted=True)
            rows = connection.execute(
                """
                SELECT revision, change_source, reason, created_at
                FROM recipe_revisions WHERE recipe_id = ? ORDER BY revision DESC
                """,
                (str(recipe_id),),
            ).fetchall()
        return [dict(row) for row in rows]

    def import_archive(
        self, categories: list[Category], recipes: list[RecipeCreate]
    ) -> tuple[int, int]:
        category_map: dict[str, str] = {}
        imported_categories = 0
        now = utc_now()
        with self.database.connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            try:
                for category in categories:
                    existing = connection.execute(
                        "SELECT id FROM categories WHERE name = ? COLLATE NOCASE",
                        (category.name,),
                    ).fetchone()
                    if existing:
                        category_map[str(category.id)] = existing["id"]
                        continue
                    category_id = str(uuid4())
                    category_map[str(category.id)] = category_id
                    slug = self._unique_slug(connection, "categories", slugify(category.name))
                    next_order = connection.execute(
                        "SELECT COALESCE(MAX(sort_order), -1) + 1 FROM categories"
                    ).fetchone()[0]
                    connection.execute(
                        """
                        INSERT INTO categories(id, name, slug, color, sort_order)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (category_id, category.name, slug, category.color, next_order),
                    )
                    imported_categories += 1

                for original in recipes:
                    payload = original.model_copy(deep=True)
                    if payload.category_id:
                        mapped = category_map.get(str(payload.category_id))
                        if mapped:
                            payload.category_id = UUID(mapped)
                        else:
                            payload.category_id = None
                    for ingredient in payload.ingredients:
                        ingredient.id = uuid4()
                    for step in payload.steps:
                        step.id = uuid4()
                    recipe_id = str(uuid4())
                    slug = self._unique_slug(connection, "recipes", slugify(payload.title))
                    self._insert_recipe(connection, recipe_id, slug, payload, now)
                    self._replace_children(connection, recipe_id, payload)
                    recipe = self._get_recipe(connection, recipe_id, include_deleted=True)
                    self._save_revision(connection, recipe, "import", "Importazione JSON")
                    self._refresh_fts(connection, recipe_id)
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        return len(recipes), imported_categories

    def create_ai_proposal(
        self,
        *,
        kind: str,
        preview: RecipeCreate | None,
        recipe_id: UUID | str | None,
        base_revision: int | None,
        rationale: str | None,
        changed_fields: list[str] | None = None,
    ) -> AiProposalView:
        if kind not in {"create", "update", "delete"}:
            raise ValueError("Tipo di proposta non valido")
        proposal_id = str(uuid4())
        created_at = datetime.now(UTC)
        expires_at = created_at + timedelta(hours=24)
        payload = {
            "preview": preview.model_dump(mode="json") if preview else None,
            "changed_fields": changed_fields or [],
        }
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT INTO ai_proposals(
                    id, kind, recipe_id, base_revision, payload_json, rationale,
                    status, created_at, expires_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'pending', ?, ?)
                """,
                (
                    proposal_id,
                    kind,
                    str(recipe_id) if recipe_id else None,
                    base_revision,
                    json.dumps(payload, ensure_ascii=False),
                    rationale,
                    created_at.isoformat(),
                    expires_at.isoformat(),
                ),
            )
        return AiProposalView(
            id=proposal_id,
            kind=kind,
            recipe_id=recipe_id,
            base_revision=base_revision,
            rationale=rationale,
            preview=preview,
            changed_fields=changed_fields or [],
        )

    def get_ai_proposal(self, proposal_id: UUID | str) -> AiProposalView:
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT * FROM ai_proposals WHERE id = ?", (str(proposal_id),)
            ).fetchone()
            if row is None:
                raise NotFoundError("Proposta AI non trovata")
            if (
                row["status"] == "pending"
                and row["expires_at"]
                and datetime.fromisoformat(row["expires_at"]) < datetime.now(UTC)
            ):
                connection.execute(
                    "UPDATE ai_proposals SET status = 'expired' WHERE id = ?",
                    (str(proposal_id),),
                )
                row = connection.execute(
                    "SELECT * FROM ai_proposals WHERE id = ?", (str(proposal_id),)
                ).fetchone()
        payload = json.loads(row["payload_json"])
        return AiProposalView(
            id=row["id"],
            kind=row["kind"],
            recipe_id=row["recipe_id"],
            base_revision=row["base_revision"],
            rationale=row["rationale"],
            preview=payload.get("preview"),
            changed_fields=payload.get("changed_fields", []),
            status=row["status"],
        )

    def apply_ai_proposal(self, proposal_id: UUID | str) -> tuple[str, Recipe | None]:
        proposal = self.get_ai_proposal(proposal_id)
        if proposal.status != "pending":
            raise ConflictError("La proposta non è più applicabile")

        if proposal.kind == "create":
            if proposal.preview is None:
                raise ConflictError("La proposta non contiene una ricetta")
            recipe = self.create_recipe(proposal.preview, source="ai")
        elif proposal.kind == "update":
            if (
                proposal.preview is None
                or proposal.recipe_id is None
                or proposal.base_revision is None
            ):
                raise ConflictError("La proposta di modifica è incompleta")
            replacement = RecipeReplace.model_validate(
                {
                    **proposal.preview.model_dump(mode="json"),
                    "revision": proposal.base_revision,
                }
            )
            recipe = self.replace_recipe(proposal.recipe_id, replacement, source="ai")
        else:
            if proposal.recipe_id is None or proposal.base_revision is None:
                raise ConflictError("La proposta di eliminazione è incompleta")
            self.soft_delete(proposal.recipe_id, proposal.base_revision)
            recipe = None

        with self.database.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE ai_proposals SET status = 'applied'
                WHERE id = ? AND status = 'pending'
                """,
                (str(proposal_id),),
            )
            if cursor.rowcount != 1:
                raise ConflictError("La proposta è già stata gestita")
        return proposal.kind, recipe

    def reject_ai_proposal(self, proposal_id: UUID | str) -> None:
        with self.database.connect() as connection:
            cursor = connection.execute(
                """
                UPDATE ai_proposals SET status = 'rejected'
                WHERE id = ? AND status = 'pending'
                """,
                (str(proposal_id),),
            )
        if cursor.rowcount != 1:
            raise ConflictError("La proposta non è più rifiutabile")

    def _insert_recipe(
        self,
        connection: sqlite3.Connection,
        recipe_id: str,
        slug: str,
        payload: RecipeCreate,
        now: str,
    ) -> None:
        connection.execute(
            """
            INSERT INTO recipes(
                id, title, slug, description, category_id, cuisine, difficulty,
                base_servings, serving_unit, prep_time_minutes, cook_time_minutes,
                rest_time_minutes, equipment_json, dietary_labels_json, allergens_json,
                notes, source_json, favorite, revision, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
            """,
            (recipe_id, payload.title, slug) + self._recipe_values(payload) + (now, now),
        )

    @staticmethod
    def _recipe_values(payload: RecipeCreate) -> tuple[Any, ...]:
        return (
            payload.description,
            str(payload.category_id) if payload.category_id else None,
            payload.cuisine,
            payload.difficulty.value if payload.difficulty else None,
            str(payload.base_servings),
            payload.serving_unit,
            payload.prep_time_minutes,
            payload.cook_time_minutes,
            payload.rest_time_minutes,
            json.dumps(payload.equipment, ensure_ascii=False),
            json.dumps(payload.dietary_labels, ensure_ascii=False),
            json.dumps(payload.allergens, ensure_ascii=False),
            payload.notes,
            json.dumps(payload.source.model_dump(mode="json"), ensure_ascii=False)
            if payload.source
            else None,
            int(payload.favorite),
        )

    def _replace_children(
        self, connection: sqlite3.Connection, recipe_id: str, payload: RecipeCreate
    ) -> None:
        connection.execute("DELETE FROM ingredients WHERE recipe_id = ?", (recipe_id,))
        connection.execute("DELETE FROM steps WHERE recipe_id = ?", (recipe_id,))
        connection.execute("DELETE FROM recipe_tags WHERE recipe_id = ?", (recipe_id,))
        for ingredient in payload.ingredients:
            connection.execute(
                """
                INSERT INTO ingredients(
                    id, recipe_id, group_name, name, quantity, unit, quantity_text,
                    preparation, optional, scalable, sort_order, original_text
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(ingredient.id),
                    recipe_id,
                    ingredient.group,
                    ingredient.name,
                    str(ingredient.quantity) if ingredient.quantity is not None else None,
                    ingredient.unit,
                    ingredient.quantity_text,
                    ingredient.preparation,
                    int(ingredient.optional),
                    int(ingredient.scalable),
                    ingredient.sort_order,
                    ingredient.original_text,
                ),
            )
        for step in payload.steps:
            connection.execute(
                """
                INSERT INTO steps(
                    id, recipe_id, title, instruction, duration_minutes,
                    temperature_celsius, sort_order
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    str(step.id),
                    recipe_id,
                    step.title,
                    step.instruction,
                    step.duration_minutes,
                    step.temperature_celsius,
                    step.sort_order,
                ),
            )
        for name in payload.tags:
            row = connection.execute(
                "SELECT id FROM tags WHERE name = ? COLLATE NOCASE", (name,)
            ).fetchone()
            tag_id = row["id"] if row else str(uuid4())
            if row is None:
                connection.execute("INSERT INTO tags(id, name) VALUES (?, ?)", (tag_id, name))
            connection.execute(
                "INSERT INTO recipe_tags(recipe_id, tag_id) VALUES (?, ?)",
                (recipe_id, tag_id),
            )

    def _get_recipe(
        self, connection: sqlite3.Connection, recipe_id: str, include_deleted: bool
    ) -> Recipe:
        where_deleted = "" if include_deleted else " AND deleted_at IS NULL"
        row = connection.execute(
            f"SELECT * FROM recipes WHERE id = ?{where_deleted}", (recipe_id,)
        ).fetchone()
        if row is None:
            raise NotFoundError("Ricetta non trovata")
        ingredient_rows = connection.execute(
            "SELECT * FROM ingredients WHERE recipe_id = ? ORDER BY sort_order", (recipe_id,)
        ).fetchall()
        step_rows = connection.execute(
            "SELECT * FROM steps WHERE recipe_id = ? ORDER BY sort_order", (recipe_id,)
        ).fetchall()
        ingredients = [
            Ingredient(
                id=item["id"],
                group=item["group_name"],
                name=item["name"],
                quantity=item["quantity"],
                unit=item["unit"],
                quantity_text=item["quantity_text"],
                preparation=item["preparation"],
                optional=bool(item["optional"]),
                scalable=bool(item["scalable"]),
                sort_order=item["sort_order"],
                original_text=item["original_text"],
            )
            for item in ingredient_rows
        ]
        steps = [
            RecipeStep(
                id=item["id"],
                title=item["title"],
                instruction=item["instruction"],
                duration_minutes=item["duration_minutes"],
                temperature_celsius=item["temperature_celsius"],
                sort_order=item["sort_order"],
            )
            for item in step_rows
        ]
        data = dict(row)
        return Recipe(
            id=data["id"],
            schema_version=data["schema_version"],
            title=data["title"],
            slug=data["slug"],
            description=data["description"],
            category_id=data["category_id"],
            cuisine=data["cuisine"],
            difficulty=data["difficulty"],
            base_servings=data["base_servings"],
            serving_unit=data["serving_unit"],
            prep_time_minutes=data["prep_time_minutes"],
            cook_time_minutes=data["cook_time_minutes"],
            rest_time_minutes=data["rest_time_minutes"],
            ingredients=ingredients,
            steps=steps,
            equipment=json.loads(data["equipment_json"]),
            tags=self._get_tag_names(connection, recipe_id),
            dietary_labels=json.loads(data["dietary_labels_json"]),
            allergens=json.loads(data["allergens_json"]),
            notes=data["notes"],
            source=json.loads(data["source_json"]) if data["source_json"] else None,
            favorite=bool(data["favorite"]),
            has_cover=bool(data["cover_image"]),
            revision=data["revision"],
            created_at=data["created_at"],
            updated_at=data["updated_at"],
            deleted_at=data["deleted_at"],
        )

    @staticmethod
    def _get_tag_names(connection: sqlite3.Connection, recipe_id: str) -> list[str]:
        rows = connection.execute(
            """
            SELECT t.name FROM tags t JOIN recipe_tags rt ON rt.tag_id = t.id
            WHERE rt.recipe_id = ? ORDER BY t.name COLLATE NOCASE
            """,
            (recipe_id,),
        ).fetchall()
        return [row["name"] for row in rows]

    def _refresh_fts(self, connection: sqlite3.Connection, recipe_id: str) -> None:
        self._remove_fts(connection, recipe_id)
        row = connection.execute(
            "SELECT title, description, notes, deleted_at FROM recipes WHERE id = ?", (recipe_id,)
        ).fetchone()
        if row is None or row["deleted_at"] is not None:
            return
        ingredients = " ".join(
            item["name"]
            for item in connection.execute(
                "SELECT name FROM ingredients WHERE recipe_id = ? ORDER BY sort_order", (recipe_id,)
            ).fetchall()
        )
        steps = " ".join(
            item["instruction"]
            for item in connection.execute(
                "SELECT instruction FROM steps WHERE recipe_id = ? ORDER BY sort_order",
                (recipe_id,),
            ).fetchall()
        )
        tags = " ".join(self._get_tag_names(connection, recipe_id))
        connection.execute(
            """
            INSERT INTO recipe_fts(recipe_id, title, description, ingredients, steps, tags, notes)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                recipe_id,
                row["title"],
                row["description"] or "",
                ingredients,
                steps,
                tags,
                row["notes"] or "",
            ),
        )

    @staticmethod
    def _remove_fts(connection: sqlite3.Connection, recipe_id: str) -> None:
        connection.execute("DELETE FROM recipe_fts WHERE recipe_id = ?", (recipe_id,))

    @staticmethod
    def _fts_query(query: str | None) -> str | None:
        if not query:
            return None
        tokens = re.findall(r"[\wÀ-ÿ]+", query, flags=re.UNICODE)[:12]
        return " AND ".join(f'"{token}"*' for token in tokens) or None

    @staticmethod
    def _unique_slug(connection: sqlite3.Connection, table: str, base: str) -> str:
        if table not in {"recipes", "categories"}:
            raise ValueError("Invalid slug table")
        candidate = base
        suffix = 2
        while connection.execute(f"SELECT 1 FROM {table} WHERE slug = ?", (candidate,)).fetchone():
            candidate = f"{base}-{suffix}"
            suffix += 1
        return candidate

    @staticmethod
    def _save_revision(
        connection: sqlite3.Connection, recipe: Recipe, source: str, reason: str | None
    ) -> None:
        connection.execute(
            """
            INSERT OR REPLACE INTO recipe_revisions(
                recipe_id, revision, snapshot_json, change_source, reason, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                str(recipe.id),
                recipe.revision,
                recipe.model_dump_json(),
                source,
                reason,
                utc_now(),
            ),
        )

    @staticmethod
    def _trim_revisions(connection: sqlite3.Connection, recipe_id: str, keep: int = 50) -> None:
        connection.execute(
            """
            DELETE FROM recipe_revisions WHERE recipe_id = ? AND revision NOT IN (
                SELECT revision FROM recipe_revisions WHERE recipe_id = ?
                ORDER BY revision DESC LIMIT ?
            )
            """,
            (recipe_id, recipe_id, keep),
        )
