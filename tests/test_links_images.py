"""Recipe links, import instructions, image imports, search_recipes tool."""
import io

import pytest
from langchain_core.messages import AIMessage
from PIL import Image as PILImage

from app.config import get_settings
from app.models import ImportDraft
from app.services import importer
from app.services import links
from app.services import recipes as rs
from app.services.llm.base import Image
from app.services.llm.fake import FakeLLM
from app.services.llm.langchain import LangChainLLM


def save(session, title, steps=(), note="", description=""):
    return rs.save(session, rs.RecipeIn(
        title=title, description=description,
        ingredients=[rs.IngredientIn(name="sykur", note=note)] if note else [],
        steps=[rs.StepIn(text=s) for s in steps]))


# --- Links ------------------------------------------------------------------------

def test_render_escapes_and_links():
    html = str(links.render("Gerið [mauk](recipe:3) <script>x</script> [vef](https://a.is/?a=1&b=2)", {3}))
    assert '<a class="rlink" href="/recipes/3">mauk</a>' in html
    assert "&lt;script&gt;" in html and "<script>" not in html
    assert 'href="https://a.is/?a=1&amp;b=2"' in html


def test_render_link_to_missing_recipe_is_plain_text():
    assert str(links.render("Sjá [mauk](recipe:9)", set())) == "Sjá mauk"


def test_label_cannot_inject_html():
    html = str(links.render('[<img src=x onerror=alert(1)>](recipe:1)', {1}))
    assert "<img" not in html and "&lt;img" in html


def test_read_view_renders_links_and_backlinks(client, session):
    jam = save(session, "Sveskjumauk", ["Sjóðið sveskjur."])
    cake = save(session, "Sveskjuterta", [f"Smyrjið [sveskjumaukinu](recipe:{jam.id}) á milli."],
                note=f"sjá [mauk](recipe:{jam.id})")
    session.flush()
    page = client.get(f"/recipes/{cake.id}").text
    assert f'<a class="rlink" href="/recipes/{jam.id}">sveskjumaukinu</a>' in page
    assert f'<a class="rlink" href="/recipes/{jam.id}">mauk</a>' in page
    jam_page = client.get(f"/recipes/{jam.id}").text
    assert "Notað í" in jam_page and f'href="/recipes/{cake.id}">Sveskjuterta</a>' in jam_page


def test_picker_lists_recipes_except_current(client, session):
    jam = save(session, "Sveskjumauk", ["x"])
    cake = save(session, "Sveskjuterta", ["x"])
    session.flush()
    html = client.get("/fragments/recipe-links", params={"q": "sveskju", "exclude": cake.id}).text
    assert f'data-link="[Sveskjumauk](recipe:{jam.id})"' in html
    assert "Sveskjuterta" not in html


def test_edit_view_has_picker(client):
    page = client.get("/recipes/new").text
    assert 'id="link-picker"' in page and "data-picker" in page


# --- Import: instructions, search_recipes, link checks -----------------------------

def draft(session, **kw):
    row = ImportDraft(**{"kind": "text", "source_text": "Kaka og sulta...", "status": "extracting",
                         "events": [], **kw})
    session.add(row)
    session.flush()
    return row


def test_instructions_go_in_prompt_outside_source(session):
    row = draft(session, instructions="Bara kakan, ekki sultan")
    llm = FakeLLM([("set_details", {"title": "Kaka", "language": "is"}), ("add_step", {"text": "Bakið."})])
    importer.process(session, row, llm)
    _, user = llm.prompts[0]
    assert "<user_instructions>\nBara kakan, ekki sultan\n</user_instructions>" in user
    assert user.index("</user_instructions>") < user.index("<recipe_source>")


def test_no_instructions_block_when_empty(session):
    row = draft(session)
    llm = FakeLLM([("set_details", {"title": "Kaka", "language": "is"}), ("add_step", {"text": "Bakið."})])
    importer.process(session, row, llm)
    assert "user_instructions" not in llm.prompts[0][1]


def test_search_recipes_and_valid_link(session):
    jam = save(session, "Sveskjumauk", ["x"])
    session.flush()
    row = draft(session, instructions="tengdu sultuna")
    llm = FakeLLM([
        ("set_details", {"title": "Sveskjuterta", "language": "is"}),
        ("search_recipes", {"query": "sveskjumauk"}),
        ("add_step", {"text": "Smyrjið [sveskjumauki](recipe:999999) á."}),
        ("add_step", {"text": f"Smyrjið [sveskjumauki](recipe:{jam.id}) á."}),
    ])
    importer.process(session, row, llm)
    assert f"recipe:{jam.id} — Sveskjumauk" in llm.results[1]
    assert llm.results[2].startswith("Error") and "search_recipes" in llm.results[2]
    assert row.status == "ready"
    assert row.draft["steps"] == [{"text": f"Smyrjið [sveskjumauki](recipe:{jam.id}) á.", "photos": []}]
    assert {"t": "lookup", "q": "sveskjumauk", "found": 1} in row.events


# --- Image imports ------------------------------------------------------------------

def jpeg_bytes(color="white", size=(2400, 1800)):
    buf = io.BytesIO()
    PILImage.new("RGB", size, color).save(buf, "JPEG")
    return buf.getvalue()


@pytest.fixture
def llm_settings(monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "provider", "anthropic")
    monkeypatch.setattr(s, "llm", "claude-sonnet-5-5")
    monkeypatch.setattr(s, "anthropic_api_key", "test-key")


def test_image_import_flow(client, session, llm_settings):
    r = client.post("/import", data={"source": "image", "instructions": "Bara kakan"},
                    files=[("images", ("p1.jpg", jpeg_bytes(), "image/jpeg")),
                           ("images", ("p2.jpg", jpeg_bytes("gray"), "image/jpeg"))],
                    follow_redirects=False)
    assert r.status_code == 303, r.text
    row = session.get(ImportDraft, int(r.headers["location"].rsplit("/", 1)[1]))
    assert row.kind == "image" and len(row.images) == 2 and row.instructions == "Bara kakan"
    stored = PILImage.open(get_settings().photos_dir / row.images[0])
    assert max(stored.size) == 1600

    llm = FakeLLM([("set_details", {"title": "Kaka", "language": "is"}), ("add_step", {"text": "Bakið."})])
    importer.process(session, row, llm)
    assert row.status == "ready"
    assert len(llm.images) == 2 and llm.images[0].mime_type == "image/jpeg"
    assert "2 attached image(s)" in llm.prompts[0][1] and "<recipe_source>" not in llm.prompts[0][1]
    assert {"t": "images", "n": 2} in row.events

    review = client.get(f"/import/{row.id}/review").text
    assert f'src="/photos/{row.images[0]}"' in review and "Bara kakan" in review


def test_image_import_validation(client, llm_settings):
    assert client.post("/import", data={"source": "image"}).status_code == 422
    r = client.post("/import", data={"source": "image"},
                    files=[("images", ("x.jpg", b"not an image", "image/jpeg"))])
    assert r.status_code == 422 and "Gat ekki lesið myndina" in r.text
    many = [("images", (f"{i}.jpg", jpeg_bytes(size=(10, 10)), "image/jpeg")) for i in range(6)]
    r = client.post("/import", data={"source": "image"}, files=many)
    assert r.status_code == 422 and "Mest 5 myndir" in r.text


def test_text_source_still_works_with_tabs_form(client, session, llm_settings):
    r = client.post("/import", data={"source": "text", "text": "Kaka...", "url": "", "instructions": ""},
                    follow_redirects=False)
    row = session.get(ImportDraft, int(r.headers["location"].rsplit("/", 1)[1]))
    assert row.kind == "text" and row.source_text == "Kaka..."


def test_langchain_sends_images_as_content_blocks():
    class Chat:
        def bind_tools(self, tools):
            return self

        def invoke(self, messages):
            self.messages = messages
            return AIMessage("done")

    chat = Chat()
    LangChainLLM(chat).run_tools("sys", "read it", [], lambda c: "ok", images=[Image(b"\xff\xd8abc")])
    content = chat.messages[1].content
    assert content[0] == {"type": "image", "base64": "/9hhYmM=", "mime_type": "image/jpeg"}
    assert content[1] == {"type": "text", "text": "read it"}


def test_deleting_image_draft_removes_files(client, session, llm_settings):
    r = client.post("/import", data={"source": "image"},
                    files=[("images", ("p.jpg", jpeg_bytes(size=(50, 50)), "image/jpeg"))], follow_redirects=False)
    row = session.get(ImportDraft, int(r.headers["location"].rsplit("/", 1)[1]))
    path = get_settings().photos_dir / row.images[0]
    assert path.exists()
    row.status = "failed"
    session.flush()
    assert client.post(f"/import/{row.id}/delete", follow_redirects=False).status_code == 303
    assert not path.exists()
