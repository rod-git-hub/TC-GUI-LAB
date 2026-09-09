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
])
def test_name_ok_rejects(bad):
    assert app._name_ok(bad) is False


@pytest.mark.parametrize("ok", ["eth0", "br-wan", "eth1.100", "a", "x_1", "A0", "a.b-c_d"])
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
