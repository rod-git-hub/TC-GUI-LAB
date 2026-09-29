"""In-app Help and About — run: python -m pytest -q

Help renders the Markdown that ships with the install. These tests also keep the
documents honest: every link between them must land on a heading that exists.
"""
import importlib, json, os, re, sys, tempfile
import bcrypt
import markdown
import pytest

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO)
os.environ.setdefault("TC_LAB_STATE_DIR", tempfile.mkdtemp(prefix="tc_lab_help_"))
app = importlib.import_module("app")
auth = importlib.import_module("auth")
help_docs = importlib.import_module("help_docs")

PAGE_IDS = [p for p, _, _ in help_docs.PAGES]


@pytest.fixture(scope="module")
def rendered():
    return {p: help_docs.render(p, app.VERSION)[1] for p in PAGE_IDS}


def _client(as_user=None):
    h = bcrypt.hashpw(b"pw", bcrypt.gensalt(rounds=4)).decode()
    auth.USERS_FILE.write_text(json.dumps({"admin": {"hash": h, "role": "admin"},
                                           "bob": {"hash": h, "role": "user"}}))
    app.app.config.update(TESTING=True, SESSION_COOKIE_SECURE=False)
    c = app.app.test_client()
    if as_user:
        with c.session_transaction() as s:
            s["_user_id"] = as_user
    return c


# ── The documents ─────────────────────────────────────────────────────────────
def test_every_page_renders(rendered):
    for page, html in rendered.items():
        assert "<h1" in html and len(html) > 2000, page


def test_links_between_documents_land_on_real_headings(rendered):
    """A link like deployment.md#4-configuration must open that page at that
    heading. Catches renamed headings and moved files in the docs."""
    ids = {p: set(re.findall(r' id="([^"]+)"', html)) for p, html in rendered.items()}
    broken = []
    for page, html in rendered.items():
        for target, anchor in re.findall(r'data-help="([^"]+)"(?: data-anchor="([^"]+)")?', html):
            if target not in ids or (anchor and help_docs.ANCHOR_PREFIX + anchor not in ids[target]):
                broken.append(f"{page} -> {target}#{anchor}")
    assert broken == []


def test_images_are_served_from_docs_img_only(rendered):
    for page, html in rendered.items():
        for src in re.findall(r'<img[^>]*src="([^"]+)"', html):
            name = src.rsplit("/", 1)[-1]
            assert src == f"/help/img/{name}", (page, src)
            assert os.path.isfile(os.path.join(help_docs.IMG_DIR, name)), (page, src)


def test_outside_links_open_in_a_new_tab(rendered):
    for page, html in rendered.items():
        for a in re.findall(r'<a [^>]*href="https?://[^"]*"[^>]*>', html):
            assert 'target="_blank"' in a and "noopener" in a, (page, a)


def test_hostile_markdown_is_neutralised():
    src = ('# T <script>alert(1)</script>\n\n<div onclick="x()">block</div>\n\n'
           'x <img src=x onerror=alert(1)> <b>b</b>\n\n'
           '[a](javascript:alert(1)) [b](data:text/html,x) [c](//evil.example/) [d](../../x)\n'
           '![e](img/evil.svg) ![f](../../../etc/p.png) ![g](img/01-login.png)\n')
    html = markdown.Markdown(extensions=[
        "tables", help_docs.TocExtension(slugify=help_docs._github_slug),
        help_docs._HelpExtension("docs/x.md", "guide", "9.9")]).convert(src)
    assert "<script" not in html and "<div" not in html and "<b>" not in html
    # The injected <img onerror=...> survives only as visible text; the one real
    # image element is the legitimate screenshot.
    assert re.findall(r"<img[^>]*>", html) == [
        '<img alt="g" loading="lazy" src="/help/img/01-login.png" />']
    assert "javascript:" not in html and "data:text" not in html and "evil.example" not in html
    assert "evil.svg" not in html and "etc/p.png" not in html
    assert 'src="/help/img/01-login.png"' in html


@pytest.mark.parametrize("heading,github", [
    ("4. Configuration", "4-configuration"),
    ("4. TC Emulation — applying impairments", "4-tc-emulation--applying-impairments"),
    ("🐳 Docker / containers", "-docker--containers"),
    ("8. Users (admin only)", "8-users-admin-only"),
])
def test_heading_anchors_match_github(heading, github):
    assert help_docs._github_slug(heading) == github


# ── The routes ────────────────────────────────────────────────────────────────
def test_help_needs_sign_in():
    c = _client()
    for url in ("/api/help", "/api/help/guide", "/help/img/01-login.png"):
        assert c.get(url).status_code in (302, 401), url


@pytest.mark.parametrize("who", ["admin", "bob"])
def test_every_signed_in_user_can_read_help(who):
    c = _client(who)
    idx = c.get("/api/help").get_json()
    assert idx["version"] == app.VERSION
    assert [p["id"] for p in idx["pages"]] == PAGE_IDS
    r = c.get("/api/help/guide").get_json()
    assert r["ok"] and r["title"] == "Using TC Lab" and "<h1" in r["html"]


@pytest.mark.parametrize("page", ["nope", "..", "..%2F..%2Fetc%2Fpasswd", "README.md"])
def test_unknown_page_is_404(page):
    assert _client("admin").get(f"/api/help/{page}").status_code == 404


def test_missing_document_says_not_installed(monkeypatch, tmp_path):
    monkeypatch.setattr(help_docs, "ROOT", str(tmp_path))
    monkeypatch.setattr(help_docs, "_cache", {})
    r = _client("admin").get("/api/help/guide")
    assert r.status_code == 404 and "not installed" in r.get_json()["error"]


def test_image_route_serves_screenshots():
    r = _client("admin").get("/help/img/01-login.png")
    assert r.status_code == 200 and r.mimetype == "image/png"
    assert r.data[:8] == b"\x89PNG\r\n\x1a\n"


@pytest.mark.parametrize("name", ["..%2Fapp.py", "evil.svg", "01-login.PNG", ".hidden.png",
                                  "nothere.png"])
def test_image_route_refuses_anything_else(name):
    assert _client("admin").get(f"/help/img/{name}").status_code == 404


# ── One version string ────────────────────────────────────────────────────────
def test_version_comes_from_app_docstring():
    with open(os.path.join(_REPO, "app.py")) as f:
        first = f.readline()
    assert first.strip().strip('"').split()[-1] == "v" + app.VERSION
    assert re.fullmatch(r"\d+\.\d+(\.\d+)?", app.VERSION)


def test_page_and_export_show_the_same_version():
    c = _client("admin")
    page = c.get("/").get_data(as_text=True)
    assert f"<title>TC Lab v{app.VERSION}</title>" in page
    assert f'<span class="brand-ver">v{app.VERSION}</span>' in page
    assert "{{" not in page
    assert c.get("/api/export").get_json()["version"] == app.VERSION
