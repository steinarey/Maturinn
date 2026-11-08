"""Shopping list interface. The real implementation is a Home Assistant to-do list
(`homeassistant.py`); tests use `FakeShoppingList`."""
from dataclasses import dataclass, field
from typing import Protocol


class ShoppingError(Exception):
    """The list service failed (network, throttling, permissions)."""


@dataclass(frozen=True)
class ShoppingListInfo:
    id: str
    name: str
    is_default: bool = False  # the service's own shopping list (todo.shopping_list in HA)


@dataclass
class ShoppingItem:
    title: str  # e.g. "Hveiti (300 g)"
    names: set[str] = field(default_factory=set)  # normalized names, for "already on the list"


class ShoppingList(Protocol):
    def lists(self) -> list[ShoppingListInfo]: ...
    def open_titles(self, list_id: str) -> list[str]: ...
    def add_items(self, list_id: str, titles: list[str], note: str = "") -> None: ...


class FakeShoppingList:
    """In-memory list service for tests."""

    def __init__(self, lists: dict[str, list[str]] | None = None) -> None:
        self.data = lists if lists is not None else {"L1": []}
        self.notes: list[str] = []

    def lists(self) -> list[ShoppingListInfo]:
        return [ShoppingListInfo(id=k, name=k) for k in self.data]

    def open_titles(self, list_id: str) -> list[str]:
        return list(self.data[list_id])

    def add_items(self, list_id: str, titles: list[str], note: str = "") -> None:
        self.data[list_id].extend(titles)
        self.notes.append(note)
