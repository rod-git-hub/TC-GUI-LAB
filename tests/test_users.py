"""User management + admin recovery CLI — run: python -m pytest -q"""
import importlib, json, os, sys, tempfile
import pytest

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO)
_STATE = tempfile.mkdtemp(prefix="tc_lab_users_")
os.environ["TC_LAB_STATE_DIR"] = _STATE
os.chdir(_STATE)
app = importlib.import_module("app")
auth = importlib.import_module("auth")
cli = importlib.import_module("cli")

ADMIN_PW, USER_PW = "adminpassword", "userpassword"


@pytest.fixture
def store():
    """Fresh account store: one admin, one regular user."""
    auth._save_users({
        "admin": {"hash": auth.hash_password(ADMIN_PW), "role": "admin"},
        "bob":   {"hash": auth.hash_password(USER_PW),  "role": "user"},
    })
    app.app.config.update(TESTING=True, WTF_CSRF_ENABLED=False,
                          SESSION_COOKIE_SECURE=False)
    try: app.limiter.reset()
    except Exception: pass
    return auth.USERS_FILE


def client(as_user=None):
    c = app.app.test_client()
    if as_user:
        with c.session_transaction() as s:
            s["_user_id"] = as_user
    return c


# ── Password policy ───────────────────────────────────────────────────────────
@pytest.mark.parametrize("bad", ["", "short", "1234567", None, 12345])
def test_policy_rejects(bad):
    assert auth.validate_password(bad) is not None


def test_policy_rejects_over_bcrypt_limit():
    # bcrypt silently truncates past 72 bytes — reject rather than mislead
    assert auth.validate_password("a" * 73) is not None
    assert auth.validate_password("é" * 40) is not None      # 80 bytes UTF-8


def test_policy_accepts():
    assert auth.validate_password("goodpassword") is None
    assert auth.validate_password("a" * 72) is None


def test_hash_is_bcrypt_salted_and_verifies():
    h1, h2 = auth.hash_password("samepassword"), auth.hash_password("samepassword")
    assert h1.startswith("$2b$12$") and h2.startswith("$2b$12$")
    assert h1 != h2                                   # unique salt per hash
    assert auth.check_password("samepassword", h1)
    assert not auth.check_password("wrongpassword", h1)


# ── Store operations ──────────────────────────────────────────────────────────
def test_create_and_delete(store):
    ok, _ = auth.create_user("dave", "davepassword", "user")
    assert ok and any(u["username"] == "dave" for u in auth.list_users())
    ok, _ = auth.create_user("dave", "otherpassword", "user")
    assert not ok                                     # duplicate rejected
    ok, _ = auth.delete_user("dave")
    assert ok and not any(u["username"] == "dave" for u in auth.list_users())


def test_create_rejects_weak_password_and_bad_role(store):
    assert auth.create_user("eve", "short", "user")[0] is False
    assert auth.create_user("eve", "goodpassword", "wizard")[0] is False


def test_list_users_never_exposes_hashes(store):
    for u in auth.list_users():
        assert set(u) == {"username", "role"}


def test_cannot_delete_last_admin(store):
    assert auth.delete_user("admin")[0] is False


def test_cannot_delete_self(store):
    auth.create_user("second", "secondpassword", "admin")
    assert auth.delete_user("admin", acting_user="admin")[0] is False


def test_cannot_demote_last_admin(store):
    assert auth.set_role("admin", "user")[0] is False
    auth.create_user("second", "secondpassword", "admin")
    assert auth.set_role("admin", "user", acting_user="other")[0] is True


def test_set_password_changes_hash(store):
    before = auth._load_users()["bob"]["hash"]
    assert auth.set_password("bob", "brandnewpassword")[0] is True
    after = auth._load_users()["bob"]["hash"]
    assert before != after and auth.check_password("brandnewpassword", after)


# ── HTTP: authorization ───────────────────────────────────────────────────────
@pytest.mark.parametrize("method,path,body", [
    ("get",    "/api/users",                None),
    ("post",   "/api/users",                {"username": "x", "password": "xpassword12"}),
    ("delete", "/api/users/bob",            None),
    ("post",   "/api/users/bob/password",   {"new": "newpassword1"}),
    ("post",   "/api/users/bob/role",       {"role": "admin"}),
])
def test_user_routes_forbidden_for_regular_user(store, method, path, body):
    r = getattr(client("bob"), method)(path, json=body)
    assert r.status_code == 403


@pytest.mark.parametrize("method,path", [
    ("get", "/api/users"), ("post", "/api/users"), ("delete", "/api/users/bob"),
])
def test_user_routes_require_login(store, method, path):
    r = getattr(client(), method)(path, json={})
    assert r.status_code in (401, 302)


def test_admin_can_list_users_without_hashes(store):
    r = client("admin").get("/api/users")
    assert r.status_code == 200
    body = r.get_json()
    assert {u["username"] for u in body["users"]} == {"admin", "bob"}
    assert "hash" not in json.dumps(body)


# ── HTTP: admin operations ────────────────────────────────────────────────────
def test_admin_creates_user_who_can_then_log_in(store):
    r = client("admin").post("/api/users", json={
        "username": "carol", "password": "carolpassword", "role": "user"})
    assert r.status_code == 200 and r.get_json()["ok"]
    c = app.app.test_client()
    r = c.post("/login", data={"username": "carol", "password": "carolpassword"},
               headers={"Referer": "https://localhost/login"})
    assert r.status_code == 302                       # redirect = signed in


def test_admin_create_rejects_bad_username(store):
    for bad in ["../evil", "-flag", "has space", "a" * 21, ""]:
        r = client("admin").post("/api/users",
                                 json={"username": bad, "password": "goodpassword"})
        assert r.status_code == 400, bad


def test_admin_reset_password_does_not_need_current(store):
    r = client("admin").post("/api/users/bob/password", json={"new": "resetpassword"})
    assert r.status_code == 200 and r.get_json()["ok"]
    assert auth.check_password("resetpassword", auth._load_users()["bob"]["hash"])


def test_admin_reset_rejects_weak_password(store):
    r = client("admin").post("/api/users/bob/password", json={"new": "short"})
    assert r.status_code == 400 and not r.get_json()["ok"]


def test_regular_user_can_still_change_own_password(store):
    r = client("bob").post("/api/auth/change-password",
                           json={"current": USER_PW, "new": "bobsnewpassword"})
    assert r.get_json()["ok"] is True


def test_regular_user_cannot_change_another_users_password(store):
    """The only self-service route keys off the session, never a supplied name."""
    r = client("bob").post("/api/auth/change-password",
                           json={"current": ADMIN_PW, "new": "hijackedpassword"})
    assert r.get_json()["ok"] is False                # ADMIN_PW is not bob's
    assert auth.check_password(ADMIN_PW, auth._load_users()["admin"]["hash"])


# ── CLI recovery ──────────────────────────────────────────────────────────────
def test_cli_requires_root(store, monkeypatch):
    monkeypatch.setattr(cli.os, "geteuid", lambda: 1000)
    with pytest.raises(SystemExit) as e:
        cli.main(["reset-admin-password", "--password", "newadminpassword"])
    assert e.value.code == cli.EXIT_PERM


def test_cli_resets_admin_and_preserves_other_users(store, monkeypatch, capsys):
    monkeypatch.setattr(cli.os, "geteuid", lambda: 0)
    auth.create_user("carol", "carolpassword", "user")
    bob_hash_before = auth._load_users()["bob"]["hash"]

    assert cli.main(["reset-admin-password", "--password", "recoveredpw1"]) == cli.EXIT_OK
    assert "SUCCESS" in capsys.readouterr().out

    users = auth._load_users()
    assert auth.check_password("recoveredpw1", users["admin"]["hash"])
    assert users["admin"]["role"] == "admin"
    assert users["bob"]["hash"] == bob_hash_before     # untouched
    assert set(users) == {"admin", "bob", "carol"}     # nothing lost


def test_cli_rejects_weak_password(store, monkeypatch):
    monkeypatch.setattr(cli.os, "geteuid", lambda: 0)
    before = auth._load_users()["admin"]["hash"]
    assert cli.main(["reset-admin-password", "--password", "short"]) == cli.EXIT_ERR
    assert auth._load_users()["admin"]["hash"] == before


def test_cli_recreates_missing_admin(store, monkeypatch):
    monkeypatch.setattr(cli.os, "geteuid", lambda: 0)
    users = auth._load_users(); del users["admin"]; auth._save_users(users)
    assert cli.main(["reset-admin-password", "--password", "recreatedpw1"]) == cli.EXIT_OK
    users = auth._load_users()
    assert users["admin"]["role"] == "admin"
    assert "bob" in users


def test_cli_writes_backup(store, monkeypatch):
    monkeypatch.setattr(cli.os, "geteuid", lambda: 0)
    cli.main(["reset-admin-password", "--password", "backuptestpw"])
    assert auth.USERS_FILE.with_suffix(".json.bak").exists()


def test_cli_list_users_hides_hashes(store, monkeypatch, capsys):
    monkeypatch.setattr(cli.os, "geteuid", lambda: 0)
    assert cli.main(["list-users"]) == cli.EXIT_OK
    out = capsys.readouterr().out
    assert "admin" in out and "bob" in out and "$2b$" not in out


def test_cli_handles_closed_stdin_cleanly(store, monkeypatch, capsys):
    """Ctrl-D at the prompt must exit with a message, not a traceback."""
    monkeypatch.setattr(cli.os, "geteuid", lambda: 0)
    monkeypatch.setattr(cli.getpass, "getpass",
                        lambda *_: (_ for _ in ()).throw(EOFError()))
    before = auth._load_users()["admin"]["hash"]
    with pytest.raises(SystemExit) as e:
        cli.main(["reset-admin-password"])
    assert e.value.code == cli.EXIT_ERR
    assert "no input received" in capsys.readouterr().err
    assert auth._load_users()["admin"]["hash"] == before


def test_cli_handles_ctrl_c_cleanly(store, monkeypatch, capsys):
    monkeypatch.setattr(cli.os, "geteuid", lambda: 0)
    monkeypatch.setattr(cli.getpass, "getpass",
                        lambda *_: (_ for _ in ()).throw(KeyboardInterrupt()))
    with pytest.raises(SystemExit) as e:
        cli.main(["reset-admin-password"])
    assert e.value.code == cli.EXIT_ERR
    assert "cancelled" in capsys.readouterr().err


def test_cli_prompts_are_not_echoed(store, monkeypatch):
    """The prompt must go through getpass (no echo), never input()."""
    monkeypatch.setattr(cli.os, "geteuid", lambda: 0)
    seen = []
    monkeypatch.setattr(cli.getpass, "getpass",
                        lambda p="": seen.append(p) or "promptedpassword")
    assert cli.main(["reset-admin-password"]) == cli.EXIT_OK
    assert len(seen) == 2 and "Retype" in seen[1]
    assert auth.check_password("promptedpassword",
                               auth._load_users()["admin"]["hash"])


def test_cli_has_no_command_that_reveals_a_password():
    """Recovery must be reset-only — never disclose an existing secret."""
    import io, contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        cli.main([])
    help_text = buf.getvalue().lower()
    for forbidden in ("show-password", "get-password", "reveal", "dump-hash", "print-password"):
        assert forbidden not in help_text


# ─────────────────────────────────────────────────────────────────────────────
# CLI help and version
# ─────────────────────────────────────────────────────────────────────────────
def test_cli_version_matches_app(capsys):
    """--version is read from app.py, so it can never drift from the app."""
    with pytest.raises(SystemExit) as e:
        cli.main(["--version"])
    assert e.value.code == 0
    first = open(os.path.join(os.path.dirname(cli.__file__), "app.py")).readline()
    assert first.strip().strip('"').split()[-1] in capsys.readouterr().out


def test_cli_help_lists_commands_and_never_offers_to_show_a_password(capsys):
    with pytest.raises(SystemExit):
        cli.main(["--help"])
    out = capsys.readouterr().out
    for word in ("reset-admin-password", "list-users", "--version", "--rollback"):
        assert word in out
    assert "--password" not in out           # the provisioning flag stays hidden


def test_cli_no_arguments_prints_help(capsys):
    assert cli.main([]) == cli.EXIT_OK
    assert "reset-admin-password" in capsys.readouterr().out
