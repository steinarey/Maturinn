"""Shopping list interface (Microsoft To Do via the user's Azure project, later phase)."""
from typing import Protocol


class ShoppingList(Protocol):
    def add_items(self, list_name: str, items: list[str]) -> None: ...


class StubShoppingList:
    """Records items in memory. Replaced once Azure credentials are configured."""

    def __init__(self) -> None:
        self.added: list[tuple[str, list[str]]] = []

    def add_items(self, list_name: str, items: list[str]) -> None:
        self.added.append((list_name, list(items)))
