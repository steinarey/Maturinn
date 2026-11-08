# Features

Running list. Status: **done**, **partial**, **planned**.

| Feature | Status | Notes |
|---|---|---|
| Docker image, compose, `/health` | done | Health checks the db |
| Schema + Alembic migrations | done | Tables in schema `DB_SCHEMA` (default `maturinn`) |
| UI i18n (is default, en) | done | JSON catalogs, cookie switcher, decimal comma in `is` |
| Dark theme (default) + light toggle | done | Cookie `theme` |
| Write view | done | Ingredients (qty/unit/name/note), "you'll need" items, steps; drag to reorder; tags; servings; language |
| Step photos | done | Upload to `PHOTOS_DIR`, resized to 2000 px + 640 px thumbnail, captions |
| Read view | done | Title → ingredients → you'll need → steps with photos; servings scaler; tap to check off; keep-screen-on |
| Canonical ingredients | done | Names per language + aliases, groups (parent), merge, inflection-aware matching |
| Ingredient admin page | done | `/ingredients` |
| Search | done | Full-text (simple + english) + pg_trgm; has/without ingredient filters with groups |
| JSON API | done | `/api/recipes` CRUD + search |
| Recipe content translation | planned | Tables exist (`*_translation`, `is_machine`, `source_hash`); LLM on demand, cached, editable |
| Import from URL or pasted text | done | Scraper (schema.org / page text) → LLM tool calls → live progress → review in write view. Provider via LangChain (`PROVIDER`, `LLM`) |
| Cooking-guide chat | planned | `LLMProvider` interface exists |
| Import recipe photo from page | planned | Scraper finds the image URL (stored in `import_draft.raw`); not downloaded yet |
| Nutrition via MCP food database | planned | `food_id`, `match_confidence`, `recipe_nutrition` exist; needs MCP server URL + tool names |
| Shopping list (Microsoft To Do) | planned | `ShoppingList.add_items` stub; needs Azure setup |

## Known gaps

- Photos removed from a recipe stay on disk (no cleanup of orphaned files yet).
- Units are free text and not translated ("stk" stays "stk" in the English UI).
- Quantities in the read view scale linearly; no unit conversion yet.
- Import has only been exercised with a scripted LLM in tests; no live provider run yet (no API key was configured).
- Import URL check resolves DNS before fetching; a DNS-rebinding host could still slip through.
