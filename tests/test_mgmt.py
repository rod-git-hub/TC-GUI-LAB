"""Management-interface protection — run: python -m pytest -q

eth0 plays the management interface, eth1 the lab NIC. Nothing touches the host:
system calls are replaced, and the boot-restore script runs against a stand-in `ip`.
"""
import importlib, json, os, subprocess, sys, tempfile
import bcrypt
import pytest

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO)
os.environ.setdefault("TC_LAB_STATE_DIR", tempfile.mkdtemp(prefix="tc_lab_mgmt_"))
app = importlib.import_module("app")
auth = importlib.import_module("auth")
mg = importlib.import_module("mgmt_guard")

VLANS = [{"name": "eth0.100", "parent": "eth0", "vlan_id": 100},
         {"name": "wan1", "parent": "eth0", "vlan_id": 250},        # on eth0, custom name
         {"name": "eth1.100", "parent": "eth1", "vlan_id": 100}]


# ── The rules ─────────────────────────────────────────────────────────────────
def test_settings():
    assert mg.settings({}) == ("", False)                          # nothing chosen yet
    assert mg.settings({"management_interface": "eth0"}) == ("eth0", True)   # locked by default
    assert mg.settings({"management_interface": "eth0", "protect_management": False}) == ("eth0", False)


def test_related_covers_the_interface_and_its_vlans():
    assert mg.related("eth0", VLANS) == {"eth0", "eth0.100", "wan1"}
    assert mg.related("", VLANS) == set()
    assert mg.is_related("eth0.300", "eth0")                     # by name, even if not listed
    assert not mg.is_related("eth1.100", "eth0", VLANS)


def test_net_config_never_keeps_the_management_interface():
    conf = {"vlans": VLANS, "bridges": {
        "br-lab":  {"members": ["eth1.100", "eth1.200"]},
        "br-mix":  {"members": ["eth1.300", "eth0.200"]},          # one side on eth0
        "br-mgmt": {"members": ["eth0"]}}}
    clean, dropped = mg.filter_net_config(conf, "eth0")
    assert [v["name"] for v in clean["vlans"]] == ["eth1.100"]
    assert list(clean["bridges"]) == ["br-lab"]                   # mixed bridge dropped whole
    assert set(dropped) == {"eth0.100", "wan1", "br-mix", "br-mgmt"}
    assert mg.filter_net_config(conf, "")[0]["bridges"] == conf["bridges"]   # none chosen


def test_impairments_on_it_are_never_kept():
    state = {"eth0": {"latency_ms": 5}, "eth0.100": {}, "wan1": {}, "eth1.100": {"latency_ms": 7}}
    assert mg.filter_state(state, "eth0", VLANS) == {"eth1.100": {"latency_ms": 7}}


def test_load_settings(tmp_path):
    assert mg.load_settings(str(tmp_path)) == ("", False)
    (tmp_path / "config.json").write_text('{"management_interface": "eth0"}')
    assert mg.load_settings(str(tmp_path)) == ("eth0", True)


# ── The dashboard ─────────────────────────────────────────────────────────────
@pytest.fixture
def lab(monkeypatch):
    h = bcrypt.hashpw(b"pw", bcrypt.gensalt(rounds=4)).decode()
    auth.USERS_FILE.write_text(json.dumps({"admin": {"hash": h, "role": "admin"},
                                           "bob": {"hash": h, "role": "user"}}))
    app.app.config.update(TESTING=True, SESSION_COOKIE_SECURE=False, WTF_CSRF_ENABLED=False)
    monkeypatch.setattr(app, "_config", {**app.DEFAULT_CONFIG, "management_interface": "eth0"})
    for f in (app.CONFIG_FILE, app.NET_CONFIG_FILE, app.STATE_FILE):
        f.unlink(missing_ok=True)
    bridges = {"br-lab": {"members": ["eth1.100"], "state": "up"}}
    monkeypatch.setattr(app, "get_all_bridges", lambda: bridges)
    monkeypatch.setattr(app, "list_vlan_interfaces", lambda: VLANS)
    monkeypatch.setattr(app, "get_all_link_info", lambda: [])
    monkeypatch.setattr(app, "list_interfaces", lambda: ["eth0", "eth1"])
    monkeypatch.setattr(app, "list_unbridged_interfaces", lambda: [])
    calls = []
    monkeypatch.setattr(app, "create_vlan", lambda *a: calls.append(("vlan",) + a) or {"ok": True})
    monkeypatch.setattr(app, "add_member", lambda *a: calls.append(("member",) + a) or {"ok": True})
    monkeypatch.setattr(app, "set_iface_up", lambda n, up=True: calls.append(("up", n, up)) or {"ok": True})
    monkeypatch.setattr(app, "apply_netem", lambda i, c: {"ok": True})
    monkeypatch.setattr(app, "_state", {})

    def client(user="admin"):
        c = app.app.test_client()
        with c.session_transaction() as s:
            s["_user_id"] = user
        return c
    return client, calls


@pytest.mark.parametrize("request_", [
    ("POST", "/api/vlans", {"parent": "eth0", "vlan_id": 200}),
    ("POST", "/api/bridges/br-lab/members", {"iface": "eth0"}),
    ("POST", "/api/bridges/br-lab/members", {"iface": "eth0.100"}),
    ("POST", "/api/bridges/br-lab/members", {"iface": "wan1"}),       # a VLAN on eth0
    ("POST", "/api/iface/eth0/up", {"up": False}),
])
def test_locked_refuses_every_use(lab, request_):
    client, calls = lab
    method, url, body = request_
    r = client().open(url, method=method, json=body)
    assert r.status_code == 403 and "management interface" in r.get_json()["stderr"]
    assert calls == []


def test_locked_still_allows_the_lab_and_bringing_it_up(lab):
    client, calls = lab
    c = client()
    assert c.post("/api/vlans", json={"parent": "eth1", "vlan_id": 300}).get_json()["ok"]
    assert c.post("/api/bridges/br-lab/members", json={"iface": "eth1.100"}).get_json()["ok"]
    assert c.post("/api/iface/eth0/up", json={"up": True}).get_json()["ok"]
    assert len(calls) == 3


def test_unlocked_allows_it_at_your_own_risk(lab):
    client, calls = lab
    app._config["protect_management"] = False
    c = client()
    assert c.post("/api/vlans", json={"parent": "eth0", "vlan_id": 200}).get_json()["ok"]
    assert c.post("/api/bridges/br-lab/members", json={"iface": "eth0"}).get_json()["ok"]
    assert c.post("/api/iface/eth0/up", json={"up": False}).get_json()["ok"]
    assert [x[0] for x in calls] == ["vlan", "member", "up"]


def test_saved_topology_never_includes_it(lab, monkeypatch):
    client, _ = lab
    app._config["protect_management"] = False             # even when allowed
    monkeypatch.setattr(app, "get_all_bridges", lambda: {
        "br-lab": {"members": ["eth1.100"]}, "br-mix": {"members": ["eth1.300", "eth0.100"]}})
    monkeypatch.setattr(app, "list_vlan_interfaces", lambda: VLANS)
    app.save_net_config()
    saved = json.loads(app.NET_CONFIG_FILE.read_text())
    assert list(saved["bridges"]) == ["br-lab"]
    assert [v["name"] for v in saved["vlans"]] == ["eth1.100"]


def test_impairment_on_it_applies_but_is_never_saved(lab):
    client, _ = lab
    assert client().post("/api/apply/eth0", json={"latency_ms": 5}).get_json()["ok"]
    assert "eth0" in app._state                                    # shown now
    assert "eth0" not in json.loads(app.STATE_FILE.read_text())     # gone after a reboot


def test_boot_reapply_skips_it(lab, monkeypatch):
    applied = []
    monkeypatch.setattr(app, "apply_netem", lambda i, c: applied.append(i) or {"ok": True})
    app._reapply_tc({"eth0": {"latency_ms": 5}, "eth1.100": {"latency_ms": 7}}, set())
    assert applied == ["eth1.100"]


@pytest.mark.parametrize("locked,status", [(True, 400), (False, 200)])
def test_import_with_it(lab, monkeypatch, locked, status):
    client, _ = lab
    app._config["protect_management"] = locked
    monkeypatch.setattr(app, "restore_via_script", lambda: None)
    monkeypatch.setattr(app, "_reapply_tc", lambda *a: None)
    bundle = {"network": {"vlans": [{"name": "eth1.100", "parent": "eth1", "vlan_id": 100}],
                          "bridges": {"br-mgmt": {"members": ["eth0", "eth1.100"]}}}}
    r = client().post("/api/import", json=bundle)
    assert r.status_code == status
    if not locked:                         # imported, minus the part that cannot persist
        assert "br-mgmt" not in json.loads(app.NET_CONFIG_FILE.read_text())["bridges"]
        assert any("management interface" in x for x in r.get_json()["imported"])


def test_settings_api(lab):
    client, _ = lab
    c = client()
    r = c.post("/api/config", json={"management_interface": "eth1", "protect_management": False})
    assert r.get_json()["ok"]
    saved = json.loads(app.CONFIG_FILE.read_text())
    assert saved["management_interface"] == "eth1" and saved["protect_management"] is False
    assert c.post("/api/config", json={"management_interface": "../x"}).status_code == 400
    assert c.post("/api/config", json={"protect_management": "yes"}).status_code == 400
    assert client("bob").post("/api/config", json={"protect_management": False}).status_code == 403


def test_page_is_told_which_interfaces_are_management(lab):
    client, _ = lab
    info = client().get("/api/interfaces").get_json()["mgmt"]
    assert info == {"interface": "eth0", "locked": True, "related": ["eth0", "eth0.100", "wan1"]}


def test_suggestion_is_admin_only(lab, monkeypatch):
    client, _ = lab
    monkeypatch.setattr(app, "interface_for", lambda addr: "eth0")
    assert client().get("/api/config/mgmt-suggest").get_json() == {"interface": "eth0"}
    assert client("bob").get("/api/config/mgmt-suggest").status_code == 403


# ── At boot ───────────────────────────────────────────────────────────────────
def test_boot_restore_never_rebuilds_it(tmp_path):
    """The real restore_helper.py, with a stand-in `ip` that records every call."""
    bindir = tmp_path / "bin"; bindir.mkdir()
    log = tmp_path / "ip.log"
    (bindir / "ip").write_text(f'#!/bin/sh\necho "$*" >> {log}\ncase "$*" in *-j*) echo "[]";; esac\n')
    (bindir / "ip").chmod(0o755)
    state = tmp_path / "state"; state.mkdir()
    (state / "config.json").write_text('{"management_interface": "eth0"}')
    (state / "network_config.json").write_text(json.dumps({
        "vlans": [{"name": "eth0.100", "parent": "eth0", "vlan_id": 100},
                  {"name": "eth1.200", "parent": "eth1", "vlan_id": 200}],
        "bridges": {"br-lab": {"members": ["eth1.200"]},
                    "br-mix": {"members": ["eth1.300", "eth0.100"]}}}))
    r = subprocess.run([sys.executable, os.path.join(_REPO, "restore_helper.py")],
                       env={**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}",
                            "TC_LAB_STATE_DIR": str(state)},
                       capture_output=True, text=True, timeout=120)
    calls = log.read_text()
    assert "eth1.200" in calls and "br-lab" in calls                # the lab is rebuilt
    assert "eth0" not in calls and "br-mix" not in calls             # the management side is not
    assert "Skipping (uses the management interface eth0)" in r.stdout
