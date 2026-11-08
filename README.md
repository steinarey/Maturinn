# Maturinn

Self-hosted recipe app for one household. Bilingual: Icelandic (default) and English.
FastAPI + SQLAlchemy 2 + Alembic + PostgreSQL 17, server-rendered with Jinja2 + HTMX, one Docker container.

What works now: write/edit recipes with structured ingredients, "you'll need" items and steps with photos;
a read view for cooking; search across both languages with has/without-ingredient filters; an ingredient
admin page for names, aliases and groups; import from a URL, pasted text or photos via an LLM; links between recipes; sending ingredients to a
Home Assistant shopping list; dark (default) and light themes; JSON API.
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
| `PROVIDER` | empty | `anthropic`, `openai` or `gemini`. Empty disables LLM features |
| `LLM` | empty | Model name for that provider, e.g. `claude-haiku-5-5`, `gpt-5.1-mini`, `gemini-3.7-flash`. For Anthropic, short forms like `haiku-5.5` are expanded to `claude-haiku-5-5` |
| `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY` | empty | Only the key for the chosen `PROVIDER` is used |
| `WORKER_ENABLED` | `true` | Background import worker (tests turn it off) |
| `HOME_ASSISTANT_URL` | empty | e.g. `http://192.168.1.10:8123`. With the token set, the shopping list feature is on |
| `HOME_ASSISTANT_TOKEN` | empty | Long-lived access token |
| `HOME_ASSISTANT_TODO` | empty | Default list entity, e.g. `todo.shopping_list` |
| `HOME_ASSISTANT_TLS_HOSTNAME` | empty | Name to verify HA's https certificate against when `HOME_ASSISTANT_URL` uses an IP (e.g. a DuckDNS certificate that only resolves from outside) |

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
   - Variables: `DATABASE_URL=postgresql://maturinn:…@<pg-host>:5432/maturinn`, optionally `DB_SCHEMA`, `DEFAULT_LANG`,
     the LLM variables and the `HOME_ASSISTANT_*` variables
4. The container runs as uid 1000. Make the photos share writable for it:
   `chown -R 1000:1000 /mnt/user/appdata/maturinn/photos` (or `99:100` and adjust the Dockerfile `useradd` if you
   prefer Unraid's `nobody:users`).
5. Open `http://<unraid-ip>:8420`. `GET /health` returns `{"status":"ok","db":"ok"}` when the db is reachable.

## Choices made (open items from the brief)

- **Frontend:** server-rendered Jinja2 + HTMX. Single container, no build step. `htmx` 2.0.4 and SortableJS 1.15.6
  are vendored in `app/static/` so the app works on a LAN without internet.
- **Auth:** none in v1. Bind to your LAN. To add auth, put a reverse proxy in front (e.g. Nginx Proxy Manager with
  access lists, or Authelia/Authentik forward auth).
- **LLM provider:** provider-agnostic through LangChain (`langchain-anthropic`, `langchain-openai`,
  `langchain-google-genai`). Features depend only on `app/services/llm/base.py`; the provider and model come from
  `PROVIDER` and `LLM`. Tests use a scripted `FakeLLM` and never call a provider.
- **Background work:** a worker thread inside the app process polls `import_draft.status` once a second. No
  Redis/Celery. Rows are claimed with `FOR UPDATE SKIP LOCKED`. Imports interrupted by a restart are marked failed
  and can be retried.
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

## Importing recipes

`/import` takes a URL, pasted text, or 1–5 photos (cookbook page, handwritten card, screenshot), plus optional
instructions for the AI ("only the cake, not the jam", "link the jam to my recipe"). Instructions are sent
separately from the source text, which is treated as untrusted content. Photos are scaled to 1600 px and sent to the
model as images, so image import needs a vision-capable model.

1. **URL only:** the page is fetched (public http/https addresses only, max 5 MB, so the server can't be used to
   reach machines on your LAN). `recipe-scrapers` reads schema.org recipe data if the page has it; otherwise
   `trafilatura` extracts the page's main text. Pasted text skips this step.
2. The LLM gets the text and builds the recipe by calling tools: `set_details` (title, description, servings,
   language, tags), `start_section`, `add_ingredient` (quantity, unit, name, note), `add_item`, `add_step`,
   `search_recipes` (to link to your saved recipes), or `not_a_recipe`. Links to recipe ids that don't exist are
   rejected back to the model.
   Bad arguments come back to the model as tool errors so it can retry.
3. Each tool call updates the draft and adds a progress event. The progress page polls and renders those events
   ("Bæti við lax 300 g", "Skrifa skref 2"), so the text comes from the tool calls, not from the model, and is in the
   UI language.
4. When done, the draft opens in the write view. Nothing is saved until you click Save. The recipe keeps its
   original language; ingredient names are matched to existing canonical ingredients the same way as typed ones.

## Links between recipes

Steps, descriptions and ingredient notes can link to another recipe with `[label](recipe:12)` (or to a web page with
`[label](https://…)`). The "Tengja uppskrift" button in the write view inserts one at the cursor; selected text
becomes the label. The read view renders them as links, and a linked recipe shows "Notað í" (used in) with the
recipes that link to it. A link to a deleted recipe shows as plain text.

## Shopping list (Home Assistant)

The read view has a **Shopping list** button. It opens a dialog with one line per ingredient, scaled to the servings
currently set in the scaler. An ingredient used twice is merged ("Sykur (300 g + 1 msk)"). Items whose name is already
an open item on the chosen list are unchecked. The checked ones are added with `todo.add_item`; lists that support
descriptions (e.g. Local To-do) also get "From recipe: <title>". Any `todo.*` entity can be chosen; the last one used is
remembered per browser.

Setup:

1. In Home Assistant, create a user for the app (Settings → People → add person, allow login, not admin), log in as it,
   and create a **long-lived access token** under the user's profile → Security.
2. Set `HOME_ASSISTANT_URL` (as reachable from the container) and `HOME_ASSISTANT_TOKEN`, optionally
   `HOME_ASSISTANT_TODO`, and restart. **Settings** (⚙ in the header) shows whether the connection works and which lists
   it found.

The app only calls `GET /api/states`, `todo.get_items` and `todo.add_item`. Added items are normal HA to-do changes, so
automations can trigger on them (e.g. on the list entity's state, which is the number of open items).

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
  services/                  recipes, ingredients, search, photos, importer, links; llm/, shopping/ (Home Assistant), nutrition/ (stub)
  routers/                   pages (HTML), imports, shopping (settings + shopping list), ingredients (admin), api (JSON), health
  templates/, static/, i18n/
alembic/versions/            migrations
tests/                       run against real Postgres
```
