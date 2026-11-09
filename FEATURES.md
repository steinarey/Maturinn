# Features

Running list. Status: **done**, **partial**, **planned**.

| Feature | Status | Notes |
|---|---|---|
| Docker image, compose, `/health` | done | Health checks the db |
| Schema + Alembic migrations | done | Tables in schema `DB_SCHEMA` (default `maturinn`) |
| UI i18n (is default, en) | done | JSON catalogs, cookie switcher, decimal comma in `is` |
| Dark theme (default) + light toggle | done | Cookie `theme` |
| Write view | done | Ingredients (qty/unit/name/note), "you'll need" items, steps; drag to reorder; tags; servings; language |
| Recipe links | done | `[label](recipe:12)` in steps, description, ingredient notes; picker in write view; "Notað í" backlinks; links to deleted recipes show as text |
| Ingredient sections | done | Named groups (e.g. Sveskjumauk / Deig) as draggable heading rows; headings in read view; import tool `start_section` |
| Step sections | planned | Same idea for method steps (e.g. "Samsetning") |
| Step photos | done | Upload to `PHOTOS_DIR`, resized to 2000 px + 640 px thumbnail, captions |
| Units | done | Fixed, translated unit list; imperial converted on save; friendliest unit on display (3 tsk → 1 msk); cups → dl/ml switch |
| Read view | done | Title → ingredients → you'll need → steps with photos; servings scaler; tap to check off; keep-screen-on |
| Canonical ingredients | done | Names per language + aliases, groups (parent), merge, inflection-aware matching |
| Ingredient admin page | done | `/ingredients` |
| Search | done | Full-text (simple + english) + pg_trgm; has/without ingredient filters with groups |
| Login | done | First (admin) user via CLI (`python -m app.users`), user admin at `/admin`, own password change, scrypt, never-expiring sessions, logged-in devices list with log-out, login throttling |
| JSON API | done | `/api/recipes` CRUD + search |
| Recipe content translation | planned | Tables exist (`*_translation`, `is_machine`, `source_hash`); LLM on demand, cached, editable |
| Import from URL, pasted text or images | done | Scraper (schema.org / page text) or 1–5 photos → LLM tool calls → live progress → review in write view. Optional instructions ("only the cake"). Model can search saved recipes and link to them. Provider via LangChain (`PROVIDER`, `LLM`) |
| Cooking-guide chat | planned | `LLMProvider` interface exists |
| Import recipe photo from page | planned | Scraper finds the image URL (stored in `import_draft.raw`); not downloaded yet |
| Nutrition via MCP food database | planned | `food_id`, `match_confidence`, `recipe_nutrition` exist; needs MCP server URL + tool names |
| Shopping list (Home Assistant to-do) | done | Read view sends checked ingredients, scaled and merged, to any `todo.*` entity; skips items already on it; Settings shows HA status |

## Known gaps

- Photos removed from a recipe stay on disk (no cleanup of orphaned files yet).
- No volume ↔ weight conversion (needs ingredient densities, e.g. from the nutrition data later).
- Import drafts can't be deleted from the UI yet (route exists, no button).
- A linked sub-recipe (e.g. the jam) is linked from a step, not listed as an ingredient of the parent recipe.
- Image imports need a vision-capable model; HEIC photos aren't supported (phones usually upload JPEG).
- Shopping list: duplicates are matched by item name only, so "Mjólk (1 l)" on the list unchecks milk even if the recipe needs more.
- Login: API clients need the session cookie (no API tokens). No password reset by email; an admin sets a new one.
- Import URL check resolves DNS before fetching; a DNS-rebinding host could still slip through.
