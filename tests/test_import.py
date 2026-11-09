"""Import pipeline: scraping, the tool-driven draft builder, the LangChain loop, and the pages."""
from pathlib import Path

import pytest
from langchain_core.messages import AIMessage

from app.config import get_settings
from app.models import ImportDraft
from app.services import importer
from app.services import ingredients as ing
from app.services import recipes as rs
from app.services.llm.base import LLMError, StopRun, ToolCall, ToolError, ToolSpec
from app.services.llm.fake import FakeLLM
from app.services.llm.langchain import LangChainLLM

FIXTURES = Path(__file__).parent / "fixtures"

SALMON_CALLS = [
    ("set_details", {"title": "Lemon salmon", "description": "Quick weeknight fish.", "servings": 2,
                     "language": "en", "tags": ["fish", "dinner"]}),
    ("add_ingredient", {"quantity": 300, "unit": "g", "name": "salmon", "note": "fillets"}),
    ("add_ingredient", {"quantity": 1, "unit": "", "name": "lemon", "note": "juiced"}),
    ("add_ingredient", {"quantity": "1/2", "unit": "tbsp", "name": "olive oil", "note": ""}),
    ("add_item", {"name": "frying pan"}),
    ("add_step", {"text": "Heat the oil in a pan."}),
    ("add_step", {"text": "Fry the salmon 4 minutes per side."}),
]


def make_draft(session, **kw) -> ImportDraft:
    row = ImportDraft(**{"kind": "text", "source_text": "some recipe text", "status": "extracting",
                         "events": [], **kw})
    session.add(row)
    session.flush()
    return row


# --- Draft builder via the scripted provider ---------------------------------------

def test_text_import_builds_draft_and_events(session):
    ing.resolve(session, "salmon", "en")  # already known
    row = make_draft(session)
    importer.process(session, row, FakeLLM(SALMON_CALLS))

    assert row.status == "ready", row.events
    d = row.draft
    assert d["title"] == "Lemon salmon" and d["original_lang"] == "en" and d["servings"] == 2
    assert [(i["quantity"], i["unit"], i["name"], i["note"]) for i in d["ingredients"]] == [
        ("300", "g", "salmon", "fillets"), ("1", "", "lemon", "juiced"), ("0.5", "tbsp", "olive oil", "")]
    assert [s["text"] for s in d["steps"]] == ["Heat the oil in a pan.", "Fry the salmon 4 minutes per side."]
    assert d["items"] == [{"name": "frying pan"}]
    assert row.detected_lang == "en"

    kinds = [e["t"] for e in row.events]
    assert kinds == ["status", "details", "ingredient", "ingredient", "ingredient", "item", "step", "step", "done"]
    known = {e["name"]: e["known"] for e in row.events if e["t"] == "ingredient"}
    assert known == {"salmon": True, "lemon": False, "olive oil": False}

    # The draft is valid input for the write view and saves as a recipe.
    recipe = rs.save(session, rs.RecipeIn(**d))
    assert [r.ingredient.name_in("en") for r in recipe.ingredients] == ["salmon", "lemon", "olive oil"]


def test_tool_errors_go_back_to_the_model(session):
    row = make_draft(session)
    llm = FakeLLM([("set_details", {"title": "", "language": "is"}),
                   ("set_details", {"title": "Grautur", "language": "is"}),
                   ("add_ingredient", {"name": " "}),
                   ("add_ingredient", {"name": "hafrar", "quantity": "fullt af"}),
                   ("add_ingredient", {"name": "hafrar", "quantity": 1, "unit": "dl"})])
    importer.process(session, row, llm)
    assert llm.results[0].startswith("Error") and llm.results[2].startswith("Error")
    assert llm.results[3].startswith("Error")
    assert row.status == "ready" and len(row.draft["ingredients"]) == 1


def test_not_a_recipe_fails_with_reason(session):
    row = make_draft(session)
    importer.process(session, row, FakeLLM([("not_a_recipe", {"reason": "It's a news article."})]))
    assert row.status == "failed"
    assert row.events[-1] == {"t": "error", "code": "not_recipe", "detail": "It's a news article."}


def test_empty_result_fails(session):
    row = make_draft(session)
    importer.process(session, row, FakeLLM([]))
    assert row.status == "failed" and row.events[-1]["code"] == "empty"


def test_no_llm_configured_fails(session):
    row = make_draft(session)
    importer.process(session, row, None)
    assert row.status == "failed" and row.events[-1]["code"] == "no_llm"


def test_url_import_uses_scraped_text(session, monkeypatch):
    html = (FIXTURES / "schema_recipe.html").read_text()
    monkeypatch.setattr(importer, "fetch_page", lambda url: html)
    row = make_draft(session, kind="url", url="https://example.com/salmon", source_text=None, status="fetching")
    llm = FakeLLM(SALMON_CALLS)
    importer.process(session, row, llm)
    assert row.status == "ready"
    assert row.raw["method"] == "schema"
    assert row.draft["source_url"] == "https://example.com/salmon"
    _, user = llm.prompts[0]
    assert "300 g salmon fillets" in user and "Squeeze lemon over and serve." in user
    assert "holiday" not in user  # only the structured recipe, not the story


# --- Scraping ---------------------------------------------------------------------

def test_extract_schema_recipe():
    text, meta = importer.extract_source("https://example.com/r", (FIXTURES / "schema_recipe.html").read_text())
    assert meta["method"] == "schema" and meta["title"] == "Lemon salmon"
    assert "- 1 lemon, juiced" in text and "2. Fry the salmon 4 minutes per side." in text


def test_extract_falls_back_to_page_text():
    text, meta = importer.extract_source("https://example.is/p", (FIXTURES / "plain_recipe.html").read_text())
    assert meta["method"] == "page_text"
    assert "250 g hveiti" in text and "Bætið bræddu smjörinu" in text


def test_extract_rejects_page_without_content():
    with pytest.raises(importer.ImportFailed) as e:
        importer.extract_source("https://example.com", "<html><body><p>Hi</p></body></html>")
    assert e.value.code == "no_content"


@pytest.mark.parametrize("url", ["http://localhost:8000/", "http://127.0.0.1/", "http://192.168.1.10/x",
                                 "http://10.0.0.1/", "http://169.254.169.254/latest", "file:///etc/passwd",
                                 "ftp://example.com/"])
def test_fetch_refuses_non_public_targets(url):
    with pytest.raises(importer.ImportFailed) as e:
        importer.fetch_page(url)
    assert e.value.code == "blocked"


def test_connection_errors_are_fetch_failures(monkeypatch):
    import httpx

    def drop(self, *a, **kw):
        raise httpx.RemoteProtocolError("Server disconnected without sending a response.")
    monkeypatch.setattr(importer, "_check_public", lambda url: None)
    monkeypatch.setattr(httpx.Client, "stream", drop)
    with pytest.raises(importer.ImportFailed) as e:
        importer.fetch_page("https://example.com/x")
    assert e.value.code == "fetch" and "RemoteProtocolError" in e.value.detail


def test_user_agent_avoids_compatible_form():
    # Some site firewalls drop "(compatible; ...)" agents (e.g. gotteri.is).
    assert "compatible" not in importer.USER_AGENT and "Maturinn" in importer.USER_AGENT


# --- LangChain loop, with a scripted chat model -------------------------------------

class ScriptedChat:
    """Stands in for a LangChain chat model: bind_tools + invoke returning scripted AIMessages."""

    def __init__(self, replies):
        self.replies = list(replies)
        self.seen = []

    def bind_tools(self, tools):
        self.tools = tools
        return self

    def invoke(self, messages):
        self.seen.append(list(messages))
        return self.replies.pop(0)


def tc(name, args, id):
    return {"name": name, "args": args, "id": id, "type": "tool_call"}


TOOLS = [ToolSpec("echo", "Echo", {"type": "object", "properties": {"x": {"type": "string"}}})]


def test_langchain_loop_runs_tools_until_done():
    chat = ScriptedChat([
        AIMessage("", tool_calls=[tc("echo", {"x": "a"}, "1"), tc("echo", {"x": "b"}, "2")]),
        AIMessage("", tool_calls=[tc("echo", {"x": "bad"}, "3")]),
        AIMessage("All done."),
    ])
    seen = []

    def handler(call: ToolCall) -> str:
        seen.append(call.args["x"])
        if call.args["x"] == "bad":
            raise ToolError("x must not be bad")
        return f"got {call.args['x']}"

    LangChainLLM(chat).run_tools("sys", "user", TOOLS, handler)
    assert seen == ["a", "b", "bad"]
    assert chat.tools[0]["function"]["name"] == "echo"
    # Both results from round one go back together, then the error result.
    last = chat.seen[-1]
    tool_msgs = [m for m in last if m.type == "tool"]
    assert [(m.tool_call_id, m.content, m.status) for m in tool_msgs] == [
        ("1", "got a", "success"), ("2", "got b", "success"), ("3", "Error: x must not be bad", "error")]


def test_langchain_loop_stop_run_and_bad_stop_reason():
    chat = ScriptedChat([AIMessage("", tool_calls=[tc("echo", {"x": "a"}, "1")])])

    def stop(call):
        raise StopRun("nope")

    with pytest.raises(StopRun):
        LangChainLLM(chat).run_tools("s", "u", TOOLS, stop)

    chat = ScriptedChat([AIMessage("", response_metadata={"stop_reason": "refusal"})])
    with pytest.raises(LLMError):
        LangChainLLM(chat).run_tools("s", "u", TOOLS, lambda c: "ok")


def test_langchain_loop_round_limit():
    chat = ScriptedChat([AIMessage("", tool_calls=[tc("echo", {"x": str(i)}, str(i))]) for i in range(3)])
    with pytest.raises(LLMError):
        LangChainLLM(chat).run_tools("s", "u", TOOLS, lambda c: "ok", max_rounds=3)


# --- Pages ------------------------------------------------------------------------

@pytest.fixture
def llm_settings(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "provider", "anthropic")
    monkeypatch.setattr(s, "llm", "haiku-5.5")
    monkeypatch.setattr(s, "anthropic_api_key", "test-key")
    return s


def test_import_page_without_llm_shows_notice(client):
    r = client.get("/import")
    assert r.status_code == 200 and "Gervigreind er ekki stillt" in r.text
    assert client.post("/import", data={"text": "x"}).status_code == 422


def test_import_flow_to_saved_recipe(client, session, llm_settings):
    assert client.post("/import", data={"url": "", "text": ""}).status_code == 422
    r = client.post("/import", data={"text": "Lemon salmon: 300 g salmon..."}, follow_redirects=False)
    assert r.status_code == 303
    draft_id = int(r.headers["location"].rsplit("/", 1)[1])
    row = session.get(ImportDraft, draft_id)
    assert row.status == "pending" and row.kind == "text"

    page = client.get(f"/import/{draft_id}").text
    assert 'hx-trigger="every 1s"' in page

    importer.process(session, row, FakeLLM(SALMON_CALLS))  # what the worker does
    progress = client.get(f"/import/{draft_id}/progress")
    assert progress.headers["HX-Redirect"] == f"/import/{draft_id}/review"

    review = client.get(f"/import/{draft_id}/review").text
    assert "Yfirfara innflutning" in review and 'value="Lemon salmon"' in review
    assert f'name="draft_id" value="{draft_id}"' in review

    form = {"title": "Lemon salmon", "original_lang": "en", "servings": "2", "tags": "fish",
            "description": "", "source_url": "", "draft_id": str(draft_id),
            "ing_id": [""], "ing_qty": ["300"], "ing_unit": ["g"], "ing_name": ["salmon"], "ing_note": [""],
            "step_key": ["a"], "step_id": [""], "step_text": ["Fry it."]}
    r = client.post("/recipes", data=form, follow_redirects=False)
    assert r.status_code == 303
    session.refresh(row)
    assert row.status == "saved" and row.recipe_id == int(r.headers["location"].rsplit("/", 1)[1])
    assert client.get(f"/import/{draft_id}/review", follow_redirects=False).headers["location"] == \
        f"/recipes/{row.recipe_id}"


def test_failed_import_shows_error_and_retry(client, session, llm_settings):
    r = client.post("/import", data={"text": "hello"}, follow_redirects=False)
    draft_id = int(r.headers["location"].rsplit("/", 1)[1])
    row = session.get(ImportDraft, draft_id)
    importer.process(session, row, FakeLLM([("not_a_recipe", {"reason": "greeting"})]))
    page = client.get(f"/import/{draft_id}").text
    assert "Þetta virðist ekki vera uppskrift" in page and "every 1s" not in page
    assert client.post(f"/import/{draft_id}/retry", follow_redirects=False).status_code == 303
    session.refresh(row)
    assert row.status == "pending" and row.events == [] and row.source_text == "hello"


# --- Worker (real commits, separate sessions) -------------------------------------

def test_worker_claims_and_processes(engine, monkeypatch):
    from app import worker
    from app.db import get_sessionmaker

    with get_sessionmaker()() as s:
        row = ImportDraft(kind="text", source_text="Lemon salmon...", status="pending", events=[])
        s.add(row)
        s.commit()
        row_id = row.id
    try:
        assert worker.claim_next() == row_id
        with get_sessionmaker()() as s:
            assert s.get(ImportDraft, row_id).status == "extracting"
        assert worker.claim_next() is None  # nothing else pending

        monkeypatch.setattr(worker, "get_llm", lambda settings: FakeLLM(SALMON_CALLS))
        worker.run_one(row_id)
        with get_sessionmaker()() as s:
            done = s.get(ImportDraft, row_id)
            assert done.status == "ready" and done.draft["title"] == "Lemon salmon"

            # A restart mid-run leaves rows that can't resume.
            done.status = "extracting"
            s.commit()
        worker.recover_interrupted()
        with get_sessionmaker()() as s:
            assert s.get(ImportDraft, row_id).status == "failed"
    finally:
        with get_sessionmaker()() as s:
            s.query(ImportDraft).filter_by(id=row_id).delete()
            s.commit()
