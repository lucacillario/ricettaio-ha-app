from decimal import Decimal

from app.domain import Ingredient, RecipeCreate


def test_ingredient_without_quantity_is_not_scalable() -> None:
    ingredient = Ingredient(name="sale")
    assert ingredient.scalable is False


def test_recipe_normalizes_order(recipe_payload: dict) -> None:
    recipe_payload["ingredients"][0]["sort_order"] = 99
    recipe = RecipeCreate.model_validate(recipe_payload)
    assert recipe.base_servings == Decimal("4")
    assert [item.sort_order for item in recipe.ingredients] == [0, 1]
