from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path
from uuid import NAMESPACE_URL, uuid5

SCHEMA_VERSION = 1

DEFAULT_CATEGORIES = [
    ("Antipasti", "#D97757"),
    ("Primi", "#D39A38"),
    ("Secondi", "#6E8E59"),
    ("Contorni", "#7CA982"),
    ("Piatti unici", "#5D8AA8"),
    ("Dolci", "#B9789C"),
    ("Bevande", "#5B8C9A"),
    ("Salse", "#A66A4B"),
    ("Altro", "#7B7B72"),
]


class Database:
    def __init__(self, path: Path) -> None:
        self.path = path

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS categories (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL COLLATE NOCASE UNIQUE,
                    slug TEXT NOT NULL UNIQUE,
                    color TEXT,
                    sort_order INTEGER NOT NULL DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS recipes (
                    id TEXT PRIMARY KEY,
                    schema_version INTEGER NOT NULL DEFAULT 1,
                    title TEXT NOT NULL,
                    slug TEXT NOT NULL UNIQUE,
                    description TEXT,
                    category_id TEXT REFERENCES categories(id) ON DELETE SET NULL,
                    cuisine TEXT,
                    difficulty TEXT CHECK (
                        difficulty IN ('easy', 'medium', 'hard') OR difficulty IS NULL
                    ),
                    base_servings TEXT NOT NULL,
                    serving_unit TEXT NOT NULL,
                    prep_time_minutes INTEGER,
                    cook_time_minutes INTEGER,
                    rest_time_minutes INTEGER,
                    equipment_json TEXT NOT NULL DEFAULT '[]',
                    dietary_labels_json TEXT NOT NULL DEFAULT '[]',
                    allergens_json TEXT NOT NULL DEFAULT '[]',
                    notes TEXT,
                    source_json TEXT,
                    favorite INTEGER NOT NULL DEFAULT 0,
                    cover_image TEXT,
                    cover_thumbnail TEXT,
                    revision INTEGER NOT NULL DEFAULT 1,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    deleted_at TEXT
                );

                CREATE TABLE IF NOT EXISTS ingredients (
                    id TEXT PRIMARY KEY,
                    recipe_id TEXT NOT NULL REFERENCES recipes(id) ON DELETE CASCADE,
                    group_name TEXT,
                    name TEXT NOT NULL,
                    quantity TEXT,
                    unit TEXT,
                    quantity_text TEXT,
                    preparation TEXT,
                    optional INTEGER NOT NULL DEFAULT 0,
                    scalable INTEGER NOT NULL DEFAULT 1,
                    sort_order INTEGER NOT NULL,
                    original_text TEXT
                );

                CREATE TABLE IF NOT EXISTS steps (
                    id TEXT PRIMARY KEY,
                    recipe_id TEXT NOT NULL REFERENCES recipes(id) ON DELETE CASCADE,
                    title TEXT,
                    instruction TEXT NOT NULL,
                    duration_minutes INTEGER,
                    temperature_celsius INTEGER,
                    sort_order INTEGER NOT NULL
                );

                CREATE TABLE IF NOT EXISTS tags (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL COLLATE NOCASE UNIQUE
                );

                CREATE TABLE IF NOT EXISTS recipe_tags (
                    recipe_id TEXT NOT NULL REFERENCES recipes(id) ON DELETE CASCADE,
                    tag_id TEXT NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
                    PRIMARY KEY (recipe_id, tag_id)
                );

                CREATE TABLE IF NOT EXISTS recipe_revisions (
                    recipe_id TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    snapshot_json TEXT NOT NULL,
                    change_source TEXT NOT NULL,
                    reason TEXT,
                    created_at TEXT NOT NULL,
                    PRIMARY KEY (recipe_id, revision)
                );

                CREATE TABLE IF NOT EXISTS conversations (
                    id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL CHECK (kind IN ('global', 'recipe')),
                    recipe_id TEXT,
                    title TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS messages (
                    id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL REFERENCES conversations(id) ON DELETE CASCADE,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS ai_proposals (
                    id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    recipe_id TEXT,
                    base_revision INTEGER,
                    payload_json TEXT NOT NULL,
                    rationale TEXT,
                    status TEXT NOT NULL DEFAULT 'pending',
                    created_at TEXT NOT NULL,
                    expires_at TEXT
                );

                CREATE VIRTUAL TABLE IF NOT EXISTS recipe_fts USING fts5(
                    recipe_id UNINDEXED,
                    title,
                    description,
                    ingredients,
                    steps,
                    tags,
                    notes,
                    tokenize='unicode61 remove_diacritics 2'
                );

                CREATE INDEX IF NOT EXISTS idx_recipes_category ON recipes(category_id);
                CREATE INDEX IF NOT EXISTS idx_recipes_updated ON recipes(updated_at DESC);
                CREATE INDEX IF NOT EXISTS idx_recipes_deleted ON recipes(deleted_at);
                CREATE INDEX IF NOT EXISTS idx_ingredients_recipe
                    ON ingredients(recipe_id, sort_order);
                CREATE INDEX IF NOT EXISTS idx_steps_recipe ON steps(recipe_id, sort_order);
                PRAGMA user_version = 1;
                """
            )
            for index, (name, color) in enumerate(DEFAULT_CATEGORIES):
                slug = self._slug(name)
                category_id = str(uuid5(NAMESPACE_URL, f"ricettaio:category:{slug}"))
                connection.execute(
                    """
                    INSERT OR IGNORE INTO categories(id, name, slug, color, sort_order)
                    VALUES (?, ?, ?, ?, ?)
                    """,
                    (category_id, name, slug, color, index),
                )
            connection.commit()

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        connection.execute("PRAGMA busy_timeout = 10000")
        try:
            yield connection
        finally:
            connection.close()

    def check(self) -> None:
        with self.connect() as connection:
            result = connection.execute("PRAGMA quick_check").fetchone()
            if result is None or result[0] != "ok":
                raise RuntimeError("SQLite quick_check failed")

    @staticmethod
    def _slug(value: str) -> str:
        import re
        import unicodedata

        normalized = unicodedata.normalize("NFKD", value)
        ascii_value = normalized.encode("ascii", "ignore").decode("ascii").lower()
        return re.sub(r"[^a-z0-9]+", "-", ascii_value).strip("-") or "categoria"
