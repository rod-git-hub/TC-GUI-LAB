"""A bridge shows the total of its members; Apply on it splits — run: python -m pytest -q

The members are the only record of what is applied. The kernel is not touched:
the bridge list, ip/tc calls and link listings are replaced for each test.
"""
import importlib, json, os, sys, tempfile
import bcrypt
import pytest

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO)
os.environ.setdefault("TC_LAB_STATE_DIR", tempfile.mkdtemp(prefix="tc_lab_br_"))
app = importlib.import_module("app")
auth = importlib.import_module("auth")

BR, M1, M2 = "lab-br100", "eth1.100", "eth1.200"


@pytest.fixture
def lab(monkeypatch):
    h = bcrypt.hashpw(b"pw", bcrypt.gensalt(rounds=4)).decode()
    auth.USERS_FILE.write_text(json.dumps({"admin": {"hash": h, "role": "admin"}}))
    app.app.config.update(TESTING=True, SESSION_COOKIE_SECURE=False, WTF_CSRF_ENABLED=False)
    bridges = {BR: {"members": [M1, M2], "state": "up", "mtu": 1500}}
    monkeypatch.setattr(app, "get_all_bridges", lambda: bridges)
    monkeypatch.setattr(app, "get_all_link_info", lambda: [])
    monkeypatch.setattr(app, "list_interfaces", lambda: ["eth1", M1, M2, BR])
    monkeypatch.setattr(app, "list_unbridged_interfaces", lambda: [])
    applied = {}
    monkeypatch.setattr(app, "apply_netem",
                        lambda i, cfg: applied.__setitem__(i, cfg) or {"ok": True})
    monkeypatch.setattr(app, "remove_qdisc", lambda i: (applied.pop(i, None), {"ok": True})[1])
    monkeypatch.setattr(app, "_state", {})
    c = app.app.test_client()
    with c.session_transaction() as s:
        s["_user_id"] = "admin"
    c.applied = applied
    return c


def total(c):
    return c.get("/api/interfaces").get_json()["totals"][BR]


def test_example_1_bridge_value_is_split_and_shown_as_total(lab):
    """50 ms on the bridge → 25 ms on each member; the bridge shows 50 ms."""
    r = lab.post(f"/api/apply/{BR}", json={"latency_ms": 50}).get_json()
    assert lab.applied[M1]["latency_ms"] == 25 and lab.applied[M2]["latency_ms"] == 25
    assert r["total"]["latency_ms"] == 50
    assert total(lab)["latency_ms"] == 50
    assert BR not in app._state                 # no separate bridge value to go stale


def test_example_2_members_set_by_hand_add_up(lab):
    """10 ms and 40 ms on the members → the bridge shows 50 ms."""
    lab.post(f"/api/apply/{M1}", json={"latency_ms": 10})
    r = lab.post(f"/api/apply/{M2}", json={"latency_ms": 40}).get_json()
    assert r["bridge"] == BR and r["total"]["latency_ms"] == 50
    assert total(lab)["latency_ms"] == 50


def test_member_change_after_bridge_apply_updates_total(lab):
    lab.post(f"/api/apply/{BR}", json={"latency_ms": 50})
    lab.post(f"/api/apply/{M1}", json={"latency_ms": 5})
    assert total(lab)["latency_ms"] == 30       # 5 + 25


def test_member_reset_updates_total(lab):
    lab.post(f"/api/apply/{BR}", json={"latency_ms": 50, "loss_pct": 2})
    r = lab.post(f"/api/reset/{M2}").get_json()
    assert r["bridge"] == BR and r["total"]["latency_ms"] == 25
    assert total(lab)["loss_pct"] == pytest.approx(1.005, abs=0.001)


def test_bridge_reset_clears_members_and_total(lab):
    lab.post(f"/api/apply/{BR}", json={"latency_ms": 50})
    r = lab.post(f"/api/reset/{BR}").get_json()
    assert r["total"]["latency_ms"] == 0 and lab.applied == {}


def test_standalone_interface_reports_no_bridge(lab):
    r = lab.post("/api/apply/eth1", json={"latency_ms": 7}).get_json()
    assert "bridge" not in r and "total" not in r


def test_startup_drops_a_v92_bridge_entry(lab, monkeypatch):
    """v9.2 stored the bridge's own value too; it could only disagree."""
    app.STATE_FILE.write_text(json.dumps({BR: {"latency_ms": 20},
                                          M1: {"latency_ms": 10}, M2: {"latency_ms": 10}}))
    monkeypatch.setenv("TC_LAB_RESTARTED", "1")       # skip restore/re-apply
    monkeypatch.delenv("TC_LAB_SKIP_RESTORE", raising=False)
    monkeypatch.setattr(app, "detect_all_tc_configs", lambda ifaces: {})
    app._init()
    assert BR not in app._state and app._state[M1] == {"latency_ms": 10}
    assert BR not in json.loads(app.STATE_FILE.read_text())


def test_import_of_v92_bundle_drops_bridge_entry(lab, monkeypatch):
    monkeypatch.setattr(app, "restore_via_script", lambda: None)
    monkeypatch.setattr(app, "_reapply_tc", lambda *a: None)
    bundle = {"version": "9.2.1",
              "tc_state": {BR: {"latency_ms": 20}, M1: {"latency_ms": 10},
                           M2: {"latency_ms": 10}},
              "network": {"bridges": {BR: {"members": [M1, M2], "stp": False}}, "vlans": []}}
    assert lab.post("/api/import", json=bundle).status_code == 200
    assert BR not in app._state and app._state[M2] == {"latency_ms": 10}
