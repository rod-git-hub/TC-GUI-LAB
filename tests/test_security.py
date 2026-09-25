"""Security regression tests — run: python -m pytest -q"""
import importlib, json, os, sys, tempfile
import bcrypt
import pytest

# All state (secret, users, profiles, cert) is forced into one throwaway dir via
# TC_LAB_STATE_DIR *before* importing the app, so nothing touches the repo and the
# path constants are stable regardless of any TC_LAB_STATE_DIR set in the caller's
# environment.
_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO)
_STATE = tempfile.mkdtemp(prefix="tc_lab_test_")
os.environ["TC_LAB_STATE_DIR"] = _STATE
os.chdir(_STATE)
app = importlib.import_module("app")
auth = importlib.import_module("auth")


# ─────────────────────────────────────────────────────────────────────────────
# Pure validators
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("bad", [
    "", "..", ".", "-", "../x", "../../etc/passwd", "-rf", "--help",
    ".hidden", "a/b", "a b", "a;b", "a$b", "a" * 21, "x\x00y",
    "<script>", "a`b", "a|b",
    # non-ASCII — str.lower() maps some of these onto ASCII letters
    "\u212a", "eth\u212a0", "eth0\u200b", "\u00e9th0", "\uff45th0", "br\u0131",
])
def test_name_ok_rejects(bad):
    assert app._name_ok(bad) is False


@pytest.mark.parametrize("ok", ["eth0", "br-wan", "eth1.100", "a", "x_1", "A0", "a.b-c_d",
                                "WAN-A1", "Br-Lab1", "_x"])
def test_name_ok_accepts(ok):
    assert app._name_ok(ok) is True


def test_vname_aborts_on_bad():
    from werkzeug.exceptions import HTTPException
    with pytest.raises(HTTPException):
        app.vname("../evil")


def test_vconfig_clamps_and_filters():
    c = app.vconfig({"latency_ms": -5, "loss_pct": 500, "rate_mbit": 10**9, "evil": "x"})
    assert c == {"latency_ms": 0, "loss_pct": 100, "rate_mbit": 100000}


# ─────────────────────────────────────────────────────────────────────────────
# _sanitize_bundle  (H1 / H2 / H3)
# ─────────────────────────────────────────────────────────────────────────────
def test_sanitize_rejects_profile_path_traversal():
    with pytest.raises(ValueError):
        app._sanitize_bundle({"profiles": {"../../tmp/pwn": {"latency_ms": 1}}})


def test_sanitize_rejects_xss_profile_name():
    with pytest.raises(ValueError):
        app._sanitize_bundle({"profiles": {"<img src=x onerror=alert(1)>": {}}})


def test_sanitize_rejects_dash_prefixed_network_names():
    with pytest.raises(ValueError):
        app._sanitize_bundle({"network": {"bridges": {"-x": {"members": []}}}})
    with pytest.raises(ValueError):
        app._sanitize_bundle(
            {"network": {"vlans": [{"name": "v1", "parent": "-p", "vlan_id": 10}]}})


def test_sanitize_rejects_bad_vlan_id():
    with pytest.raises(ValueError):
        app._sanitize_bundle(
            {"network": {"vlans": [{"name": "v1", "parent": "eth0", "vlan_id": 99999}]}})


def test_sanitize_rejects_non_object():
    with pytest.raises(ValueError):
        app._sanitize_bundle([1, 2, 3])


def test_sanitize_accepts_and_cleans_a_good_bundle():
    out = app._sanitize_bundle({
        "version": "9.1",
        "profiles": {"satellite": {"latency_ms": 600, "bogus_key": 5}},
        "labels": {"eth0": "x" * 200},
        "tc_state": {"eth0": {"loss_pct": 999}},
        "network": {
            "bridges": {"br0": {"members": ["eth0", "eth1"], "stp": True}},
            "vlans": [{"name": "eth0.100", "parent": "eth0", "vlan_id": 100}],
        },
    })
    assert "bogus_key" not in out["profiles"]["satellite"]
    assert len(out["labels"]["eth0"]) == 80
    assert out["tc_state"]["eth0"]["loss_pct"] == 100
    assert out["network"]["vlans"][0]["vlan_id"] == 100


# ─────────────────────────────────────────────────────────────────────────────
# HTTP layer
# ─────────────────────────────────────────────────────────────────────────────
@pytest.fixture
def base():
    """Reset shared state (users, profiles) before each HTTP test."""
    h = bcrypt.hashpw(b"pw", bcrypt.gensalt(rounds=4)).decode()
    auth.USERS_FILE.write_text(json.dumps({
        "admin": {"hash": h, "role": "admin"},
        "bob":   {"hash": h, "role": "user"},
    }))
    for f in app.PROFILES_DIR.glob("*.json"):
        f.unlink()
    for f in (app.STATE_FILE, app.NET_CONFIG_FILE, app.LABELS_FILE):
        if f.exists():
            f.unlink()
    app.app.config.update(TESTING=True, SESSION_COOKIE_SECURE=False)
    try:
        app.limiter.reset()
    except Exception:
        pass
    return app.STATE_DIR


def _client(as_user=None, csrf=False):
    app.app.config["WTF_CSRF_ENABLED"] = csrf
    c = app.app.test_client()
    if as_user:
        with c.session_transaction() as s:
            s["_user_id"] = as_user
    return c


def test_security_headers_present(base):
    r = _client().get("/login")
    assert r.headers["X-Frame-Options"] == "DENY"
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert "frame-ancestors 'none'" in r.headers["Content-Security-Policy"]


def test_cookie_flags_configured():
    assert app.app.config["SESSION_COOKIE_SAMESITE"] == "Strict"
    assert app.app.config["SESSION_COOKIE_HTTPONLY"] is True
    assert app.app.config["REMEMBER_COOKIE_SECURE"] is True


def test_csrf_blocks_unauthenticated_state_change(base):
    c = _client(as_user="admin", csrf=True)
    r = c.post("/api/apply/lo", json={"latency_ms": 1})
    assert r.status_code == 400            # missing CSRF token
    assert b"csrf" in r.data.lower() or b"token" in r.data.lower()


def test_import_rejects_traversal_bundle(base):
    c = _client(as_user="admin")
    r = c.post("/api/import", json={"profiles": {"../pwned": {"latency_ms": 1}}})
    assert r.status_code == 400
    assert not (base / "pwned.json").exists()
    assert not (base.parent / "pwned.json").exists()
    assert not (app.PROFILES_DIR / "../pwned.json").resolve().exists()


def test_import_accepts_clean_bundle(base):
    c = _client(as_user="admin")
    r = c.post("/api/import", json={"version": "9.2",
                                    "profiles": {"good_link": {"latency_ms": 5}}})
    assert r.status_code == 200
    assert (app.PROFILES_DIR / "good_link.json").exists()


def test_role_user_cannot_create_bridge(base):
    r = _client(as_user="bob").post("/api/bridges/br0", json={})
    assert r.status_code == 403


def test_role_user_can_reach_impairment_route(base):
    # Not 403/401 — the tc command itself fails as non-root, but authz passed.
    r = _client(as_user="bob").post("/api/reset/lo", json={})
    assert r.status_code not in (401, 403)


def test_role_admin_can_reach_bridge_route(base):
    r = _client(as_user="admin").post("/api/bridges/br0", json={})
    assert r.status_code != 403


def test_login_rate_limited(base):
    c = _client()
    codes = [c.post("/login", data={"username": "x", "password": "y"}).status_code
             for _ in range(7)]
    assert 429 in codes


def test_skip_restore_env_prevents_host_mutation(monkeypatch):
    """TC_LAB_SKIP_RESTORE must stop _init() touching the host's tc/topology."""
    called = []
    monkeypatch.setattr(app, "restore_via_script", lambda: called.append("restore"))
    monkeypatch.setattr(app, "_reapply_tc", lambda *a: called.append("reapply"))
    monkeypatch.setattr(app, "detect_all_tc_configs", lambda *a: called.append("scan") or {})
    monkeypatch.setenv("TC_LAB_SKIP_RESTORE", "1")
    app._init()
    assert called == []
    monkeypatch.delenv("TC_LAB_SKIP_RESTORE")


def test_open_redirect_blocked():
    assert auth._safe_next("https://evil.example/") is None
    assert auth._safe_next("//evil.example/") is None
    assert auth._safe_next("http://x/a") is None
    assert auth._safe_next("/vlans") == "/vlans"
    assert auth._safe_next(None) is None


# ─────────────────────────────────────────────────────────────────────────────
# Open redirect — WHATWG vs RFC 3986 (CodeQL py/url-redirection, alert #17)
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("bad", [
    "https://evil.example/", "//evil.example/", "http://x/a",
    "/\\evil.example",        # browsers read "\" as "/" → //evil.example
    "/\\/evil.example",
    "/\tevil.example",        # tab/CR/LF are stripped before parsing
    "/\r/evil.example",
    "/\n/evil.example",
    "\\/evil.example",
    "", None, 123,
])
def test_safe_next_rejects(bad):
    assert auth._safe_next(bad) is None


@pytest.mark.parametrize("ok", ["/", "/vlans", "/a/b?x=1", "/p#frag"])
def test_safe_next_accepts_relative(ok):
    assert auth._safe_next(ok) == ok


# ─────────────────────────────────────────────────────────────────────────────
# Rejected values echoed in import errors are bounded (CodeQL alert #18)
# ─────────────────────────────────────────────────────────────────────────────
def test_import_error_truncates_echoed_name():
    with pytest.raises(ValueError) as ei:
        app._sanitize_bundle({"profiles": {"!" * 5000: {}}})
    assert len(str(ei.value)) < 120


def test_import_error_still_identifies_short_name():
    with pytest.raises(ValueError, match="../pwn"):
        app._sanitize_bundle({"profiles": {"../pwn": {}}})


# ─────────────────────────────────────────────────────────────────────────────
# Foreign bridges (docker0 …) must not enter the saved topology, or a config
# export would carry them and a restore would try to recreate them.
# ─────────────────────────────────────────────────────────────────────────────
def test_save_net_config_skips_foreign_bridges(base, monkeypatch):
    monkeypatch.setattr(app, "get_all_bridges", lambda: {
        "br-wan1":        {"members": ["eth1", "eth2"]},
        "docker0":        {"members": ["veth9a1"]},
        "br-1a2b3c4d5e6f": {"members": []},
        "virbr0":         {"members": []},
    })
    monkeypatch.setattr(app, "list_vlan_interfaces", lambda: [])
    app.save_net_config()
    saved = json.loads(app.NET_CONFIG_FILE.read_text())
    assert list(saved["bridges"]) == ["br-wan1"]
    assert saved["bridges"]["br-wan1"]["members"] == ["eth1", "eth2"]


# ─────────────────────────────────────────────────────────────────────────────
# The boot-time restore re-validates every name with its own copy of the rule.
# restore_helper.py executes on import, so extract just _VALID and _safe().
# ─────────────────────────────────────────────────────────────────────────────
def _restore_helper_safe():
    import ast, pathlib
    src = pathlib.Path(_REPO, "restore_helper.py").read_text()
    keep = [n for n in ast.parse(src).body
            if (isinstance(n, ast.FunctionDef) and n.name == "_safe")
            or (isinstance(n, ast.Assign)
                and any(getattr(t, "id", None) == "_VALID" for t in n.targets))]
    ns = {}
    exec(compile(ast.Module(keep, []), "restore_helper.py", "exec"), ns)
    return ns["_safe"]


@pytest.mark.parametrize("name", [
    "eth0", "eth1.100", "WAN-A1", "Br-Lab1", "_x", "a" * 20, "a" * 21,
    "", ".x", "-x", "a/b", "a b", "\u212a", "eth\u212a0", "\u00e9th0", "eth0\u200b",
])
def test_restore_helper_agrees_with_app_validator(name):
    assert _restore_helper_safe()(name) == app._name_ok(name)


def test_import_unreadable_body_does_not_echo_exception(base, monkeypatch):
    import flask
    def boom(*a, **k):
        raise ValueError("INTERNAL-DETAIL-must-not-leak")
    monkeypatch.setattr(flask.Request, "get_json", boom)
    r = _client(as_user="admin").post("/api/import", data="x")
    assert r.status_code == 400
    assert b"INTERNAL-DETAIL" not in r.data
    assert r.get_json()["stderr"] == "Invalid JSON"


# ─────────────────────────────────────────────────────────────────────────────
# "Keep me signed in" must not outlive a working week (Flask-Login defaults to 365
# days). Read the real Set-Cookie header rather than trusting the config value.
# ─────────────────────────────────────────────────────────────────────────────
def test_remember_me_cookie_lasts_seven_days(base):
    from datetime import datetime, timezone, timedelta
    from email.utils import parsedate_to_datetime
    c = _client()
    r = c.post("/login", data={"username": "bob", "password": "pw", "remember": "on"})
    assert r.status_code == 302
    cookie = next(h for h in r.headers.getlist("Set-Cookie") if h.startswith("remember_token="))
    expires = parsedate_to_datetime(cookie.split("Expires=")[1].split(";")[0])
    left = expires - datetime.now(timezone.utc)
    assert timedelta(days=6, hours=23) < left <= timedelta(days=7)
    assert "Secure" in cookie and "HttpOnly" in cookie and "SameSite=Strict" in cookie


def test_login_without_remember_sets_no_remember_cookie(base):
    r = _client().post("/login", data={"username": "bob", "password": "pw"})
    assert r.status_code == 302
    assert not any(h.startswith("remember_token=") for h in r.headers.getlist("Set-Cookie"))


def test_export_bundle_shape_and_version(base):
    """The export is what a user keeps as a backup — pin its shape, version and
    timestamp formats so a refactor cannot silently change them."""
    import re
    r = _client(as_user="bob").get("/api/export")          # any signed-in role
    assert r.status_code == 200
    assert re.fullmatch(r'attachment; filename=tc_lab_config_\d{8}_\d{6}\.json',
                        r.headers["Content-Disposition"])
    b = r.get_json()
    assert set(b) == {"version", "exported", "network", "tc_state", "labels", "profiles"}
    with open(os.path.join(_REPO, "app.py")) as fh:
        app_version = fh.readline().strip().strip('"').split()[-1].lstrip("v")
    assert b["version"] == app_version
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", b["exported"])
