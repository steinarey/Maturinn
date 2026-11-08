"""Food database interface (MCP server, later phase). Nutrition is derived
asynchronously from recipe_ingredient.food_id + quantities converted to grams."""
from dataclasses import dataclass
from typing import Protocol


@dataclass
class FoodMatch:
    food_id: str
    name: str
    confidence: float  # 0..1
    grams_per_unit: dict[str, float] | None = None  # e.g. {"piece": 170}


class FoodDatabase(Protocol):
    def search(self, name: str, lang: str) -> list[FoodMatch]: ...
    def nutrients(self, food_id: str) -> dict[str, float]:
        """Nutrients per 100 g."""
        ...


class NoFoodDatabase:
    """Stub until the MCP server details are configured."""

    def search(self, name: str, lang: str) -> list[FoodMatch]:
        return []

    def nutrients(self, food_id: str) -> dict[str, float]:
        return {}
