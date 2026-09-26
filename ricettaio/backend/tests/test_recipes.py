from __future__ import annotations

from io import BytesIO

import httpx2
import pytest
from PIL import Image

pytestmark = pytest.mark.anyio


async def create_recipe(client: httpx2.AsyncClient, payload: dict) -> dict:
    response = await client.post("/api/v1/recipes", json=payload)
    assert response.status_code == 201, response.text
    return response.json()


async def test_health_and_seed_categories(client: httpx2.AsyncClient) -> None:
    health = await client.get("/api/v1/health")
    assert health.status_code == 200
    assert health.json()["database"] == "ok"
    assert health.json()["ai_configured"] is True


async def test_chat_stream_emits_delta_result_and_done(client: httpx2.AsyncClient) -> None:
    response = await client.post(
        "/api/v1/ai/chat/stream",
        json={"messages": [{"role": "user", "content": "Ciao"}], "recipe_id": None},
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert "event: delta" in response.text
    assert "event: result" in response.text
    assert "event: done" in response.text

    categories = await client.get("/api/v1/categories")
    assert categories.status_code == 200
    assert {item["name"] for item in categories.json()} >= {"Antipasti", "Primi", "Dolci"}


async def test_recipe_crud_search_revision_and_restore(
    client: httpx2.AsyncClient, recipe_payload: dict
) -> None:
    created = await create_recipe(client, recipe_payload)
    recipe_id = created["id"]
    assert created["slug"] == "pasta-e-ceci"
    assert created["revision"] == 1
    assert created["ingredients"][1]["quantity_text"] == "q.b."

    search = await client.get("/api/v1/recipes", params={"q": "ceci", "favorite": True})
    assert search.status_code == 200
    assert search.json()["total"] == 1
    assert search.json()["items"][0]["title"] == "Pasta e ceci"

    updated_payload = {**recipe_payload, "title": "Pasta e ceci cremosa", "revision": 1}
    updated = await client.put(f"/api/v1/recipes/{recipe_id}", json=updated_payload)
    assert updated.status_code == 200, updated.text
    assert updated.json()["revision"] == 2

    conflict = await client.put(f"/api/v1/recipes/{recipe_id}", json=updated_payload)
    assert conflict.status_code == 409

    deleted = await client.request("DELETE", f"/api/v1/recipes/{recipe_id}", json={"revision": 2})
    assert deleted.status_code == 204
    assert (await client.get(f"/api/v1/recipes/{recipe_id}")).status_code == 404
    trash = (await client.get("/api/v1/recipes", params={"deleted": True})).json()
    assert trash["total"] == 1

    restored = await client.post(f"/api/v1/recipes/{recipe_id}/restore")
    assert restored.status_code == 200
    assert restored.json()["revision"] == 4
    assert (await client.get(f"/api/v1/recipes/{recipe_id}")).status_code == 200


async def test_duplicate_has_unique_slug(client: httpx2.AsyncClient, recipe_payload: dict) -> None:
    recipe = await create_recipe(client, recipe_payload)
    duplicate = await client.post(f"/api/v1/recipes/{recipe['id']}/duplicate")
    assert duplicate.status_code == 201
    assert duplicate.json()["title"] == "Pasta e ceci (copia)"
    assert duplicate.json()["slug"] != recipe["slug"]


async def test_cover_upload_and_delete(client: httpx2.AsyncClient, recipe_payload: dict) -> None:
    recipe = await create_recipe(client, recipe_payload)
    image = Image.new("RGB", (900, 600), "#708064")
    buffer = BytesIO()
    image.save(buffer, format="PNG")

    upload = await client.post(
        f"/api/v1/recipes/{recipe['id']}/cover",
        files={"image": ("cover.png", buffer.getvalue(), "image/png")},
    )
    assert upload.status_code == 200, upload.text
    assert upload.json()["has_cover"] is True
    cover = await client.get(f"/api/v1/recipes/{recipe['id']}/cover", params={"thumbnail": True})
    assert cover.status_code == 200
    assert cover.headers["content-type"] == "image/webp"

    removed = await client.delete(f"/api/v1/recipes/{recipe['id']}/cover")
    assert removed.status_code == 200
    assert removed.json()["has_cover"] is False


async def test_ai_fake_uses_local_recipe(client: httpx2.AsyncClient, recipe_payload: dict) -> None:
    recipe = await create_recipe(client, recipe_payload)
    response = await client.post(
        "/api/v1/ai/chat",
        json={"messages": [{"role": "user", "content": "Cosa posso fare con i ceci?"}]},
    )
    assert response.status_code == 200, response.text
    assert recipe["id"] in response.json()["referenced_recipe_ids"]

    draft = await client.post("/api/v1/ai/drafts", json={"prompt": "Una torta di mele"})
    assert draft.status_code == 200
    assert draft.json()["source"]["type"] == "ai"


async def test_validation_rejects_empty_recipe(client: httpx2.AsyncClient) -> None:
    response = await client.post(
        "/api/v1/recipes",
        json={"title": "", "base_servings": 0, "ingredients": [], "steps": []},
    )
    assert response.status_code == 422


async def test_export_and_atomic_import(client: httpx2.AsyncClient, recipe_payload: dict) -> None:
    await create_recipe(client, recipe_payload)
    exported = await client.get("/api/v1/export")
    assert exported.status_code == 200
    archive = exported.json()
    assert archive["export_version"] == 1
    assert len(archive["categories"]) >= 9
    assert archive["recipes"][0]["title"] == "Pasta e ceci"

    imported = await client.post("/api/v1/import", json=archive)
    assert imported.status_code == 200, imported.text
    assert imported.json()["imported_recipes"] == 1
    page = (await client.get("/api/v1/recipes")).json()
    assert page["total"] == 2
    assert {item["slug"] for item in page["items"]} == {
        "pasta-e-ceci",
        "pasta-e-ceci-2",
    }


async def test_ai_update_proposal_requires_explicit_apply(
    client: httpx2.AsyncClient, recipe_payload: dict
) -> None:
    recipe = await create_recipe(client, recipe_payload)
    chat = await client.post(
        "/api/v1/ai/chat",
        json={
            "recipe_id": recipe["id"],
            "messages": [{"role": "user", "content": "Proponi una variante"}],
        },
    )
    assert chat.status_code == 200, chat.text
    proposal = chat.json()["proposal"]
    assert proposal["kind"] == "update"

    unchanged = (await client.get(f"/api/v1/recipes/{recipe['id']}")).json()
    assert unchanged["revision"] == 1
    assert "Variante proposta" not in unchanged["notes"]

    applied = await client.post(f"/api/v1/ai/proposals/{proposal['id']}/apply")
    assert applied.status_code == 200, applied.text
    assert applied.json()["recipe"]["revision"] == 2
    assert "Variante proposta" in applied.json()["recipe"]["notes"]

    second_apply = await client.post(f"/api/v1/ai/proposals/{proposal['id']}/apply")
    assert second_apply.status_code == 409
