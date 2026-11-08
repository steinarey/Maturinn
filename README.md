# Maturinn

Self-hosted recipe app for one household. Bilingual: Icelandic (default) and English.
FastAPI + SQLAlchemy 2 + Alembic + PostgreSQL 17, server-rendered with Jinja2 + HTMX, one Docker container.

What works now: write/edit recipes with structured ingredients, "you'll need" items and steps with photos;
a read view for cooking; search across both languages with has/without-ingredient filters; an ingredient
admin page for names, aliases and groups; dark (default) and light themes; JSON API.
See [FEATURES.md](FEATURES.md) for the running list.

## Run locally

Needs Docker and [uv](https://docs.astral.sh/uv/).

```sh
cp .env.example .env
docker compose up --build        # app on http://localhost:8000, dev Postgres on localhost:5433
```

Or run the app on the host against the compose database:

```sh
docker compose up -d db
uv sync
uv run alembic upgrade head
uv run uvicorn app.main:app --reload
```

## Tests

Tests need a real Postgres (search depends on `pg_trgm` and text search). They use the compose db by
default, in a separate schema `maturinn_test` that is dropped and re-created on each run.

```sh
docker compose up -d db
uv run pytest
```

Override with `DATABASE_URL` / `TEST_DB_SCHEMA`. The test fixture refuses to run in schema `maturinn`.

## Configuration

All config is environment variables (see `.env.example`).

| Variable | Default | Notes |
|---|---|---|
| `DATABASE_URL` | required | `postgresql://user:pass@host:5432/db` |
| `DB_SCHEMA` | `maturinn` | All app tables live in this schema; it is created on first migration |
| `PHOTOS_DIR` | `/data/photos` | Uploaded photos; mount a volume here |
| `DEFAULT_LANG` | `is` | UI language when no cookie is set |
| `LLM_ENABLED`, `ANTHROPIC_API_KEY`, `LLM_MODEL` | off | Later phases (import, translation, cooking guide) |
| `SHOPPING_ENABLED` | `false` | Later phase (Microsoft To Do) |

### Database permissions

The first migration runs `CREATE SCHEMA IF NOT EXISTS <DB_SCHEMA>` and
`CREATE EXTENSION IF NOT EXISTS pg_trgm WITH SCHEMA public`. `pg_trgm` is a trusted extension, so a
database owner can create it without superuser. If your role can't, have an admin run
`CREATE EXTENSION pg_trgm WITH SCHEMA public;` once in the target database. If `pg_trgm` is already
installed in some other schema, make sure that schema is on the role's `search_path`.

Migrations run automatically when the container starts (`alembic upgrade head`).

## Running on Unraid

Only the app container runs on Unraid; it uses your existing Postgres 17 server.

1. Create a database and role on the Postgres server, e.g. `CREATE ROLE maturinn LOGIN PASSWORD '…';
   CREATE DATABASE maturinn OWNER maturinn;` (or reuse a database; the tables stay in their own schema).
2. Build the image (on any machine with Docker) and push it to a registry your Unraid can pull from,
   or build it on Unraid: `docker build -t maturinn:latest .`
3. In Unraid **Docker → Add Container**:
   - Repository: `maturinn:latest` (or your registry path)
   - Network: bridge, port `8000` → host port of your choice (e.g. `8420`)
   - Path: container `/data/photos` → host `/mnt/user/appdata/maturinn/photos`
   - Variables: `DATABASE_URL=postgresql://maturinn:…@<pg-host>:5432/maturinn`, optionally `DB_SCHEMA`, `DEFAULT_LANG`
4. The container runs as uid 1000. Make the photos share writable for it:
   `chown -R 1000:1000 /mnt/user/appdata/maturinn/photos` (or `99:100` and adjust the Dockerfile `useradd` if you
   prefer Unraid's `nobody:users`).
5. Open `http://<unraid-ip>:8420`. `GET /health` returns `{"status":"ok","db":"ok"}` when the db is reachable.

## Choices made (open items from the brief)

- **Frontend:** server-rendered Jinja2 + HTMX. Single container, no build step. `htmx` 2.0.4 and SortableJS 1.15.6
  are vendored in `app/static/` so the app works on a LAN without internet.
- **Auth:** none in v1. Bind to your LAN. To add auth, put a reverse proxy in front (e.g. Nginx Proxy Manager with
  access lists, or Authelia/Authentik forward auth).
- **LLM provider:** Anthropic, behind `app/services/llm/base.py` (`LLMProvider`). Not wired yet: the LLM features
  come in later phases. A `FakeLLM` exists for tests.
- **i18n:** flat JSON catalogs in `app/i18n/{is,en}.json`, Babel for number/date formatting. Missing keys fall back
  `is` → `en` → key. A test fails if a template uses a key that isn't in the catalogs or the two catalogs differ.
- **Theme:** dark by default; a toggle stores `light`/`dark` in a cookie.
- **Database schema:** all tables in one Postgres schema (`DB_SCHEMA`) so they can't collide with anything already on
  the shared server.
- **Search index:** a `recipe_search` table (two tsvectors + trigram text, GIN-indexed) rebuilt by the app on every
  save, rather than triggers across many tables.

## How search handles Icelandic

Postgres has no Icelandic stemmer. Each query word matches a recipe when any of these hit:

1. Prefix query on a shortened stem, `simple` config: `kjúklingabringur` → `kjúklingabring:*` finds `kjúklingabringa`.
2. English stemming, `english` config: `breasts` → `breast`.
3. `pg_trgm` word similarity against title + ingredient names + tags (catches typos like `spagetti` and other endings).
   Words under 6 letters need a closer match so `salt` doesn't find `salat`.

Words are ANDed. Ingredient names in every language are indexed, so an Icelandic recipe is found by the English
name of its ingredient once that name is set on the ingredient.

**Has / without** filters work on canonical ingredients, not text. "has chicken" matches any ingredient whose name
contains the whole word *chicken*. Groups expand: put *kasjúhnetur* and *almonds* in group *hnetur/nuts* on the
Ingredients page, and "without nuts" excludes both.

## Ingredient normalization

Recipe rows link to a canonical `ingredient`; names live in `ingredient_name` (per language, with aliases). When a
recipe is saved, each typed name is resolved in this order:

1. Exact match on any name in any language (case-insensitive, whitespace collapsed; Icelandic letters kept).
2. Naive English singular (`breasts` → `breast`, `berries` → `berry`).
3. Conservative inflection match: a long shared stem with different endings (`kjúklingabringur` ↔ `kjúklingabringa`,
   `laukar` ↔ `laukur`). Short words don't qualify, so `salt`/`salat` stay separate.
4. Otherwise a new ingredient is created.

The write view shows "✓ <canonical name>" or "New ingredient" with suggestions as you type. Fragmented
ingredients can be merged on the Ingredients page.

## Project layout

```
app/
  main.py, config.py, db.py, i18n.py, web.py
  models/recipe.py           all tables (incl. translation, nutrition and import tables for later phases)
  services/                  recipes, ingredients, search, photos; llm/, nutrition/, shopping/ interfaces
  routers/                   pages (HTML), ingredients (admin), api (JSON), health
  templates/, static/, i18n/
alembic/versions/            migrations
tests/                       run against real Postgres
```
