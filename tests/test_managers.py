"""Manager-layer regression tests — run: python -m pytest -q"""
import importlib, os, sys, tempfile
import pytest

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO)
os.environ.setdefault("TC_LAB_STATE_DIR", tempfile.mkdtemp(prefix="tc_lab_mgr_"))
vlan_manager   = importlib.import_module("vlan_manager")
bridge_manager = importlib.import_module("bridge_manager")
tc_manager     = importlib.import_module("tc_manager")


# ─────────────────────────────────────────────────────────────────────────────
# VLAN id resolution — a bridge-member VLAN with a non-dotted name used to be
# silently dropped from list_vlan_interfaces(), and therefore from every export.
# ─────────────────────────────────────────────────────────────────────────────
_PROC = """VLAN Dev name\t | VLAN ID
Name-Type: VLAN_NAME_TYPE_RAW_PLUS_VID_NO_PAD
eth1.1100    | 1100  | eth1
wan1           | 250  | eth1
eth1.100     | 100  | eth1
"""


def _proc_file(tmp_path):
    p = tmp_path / "config"
    p.write_text(_PROC)
    return str(p)


def test_proc_vlan_ids_parses_registry(tmp_path):
    ids = vlan_manager._proc_vlan_ids(_proc_file(tmp_path))
    assert ids == {"eth1.1100": 1100, "wan1": 250, "eth1.100": 100}


def test_proc_vlan_ids_skips_headers(tmp_path):
    ids = vlan_manager._proc_vlan_ids(_proc_file(tmp_path))
    assert "VLAN Dev name" not in ids and "Name-Type: VLAN_NAME_TYPE_RAW_PLUS_VID_NO_PAD" not in ids


def test_proc_vlan_ids_missing_file_is_empty():
    assert vlan_manager._proc_vlan_ids("/nonexistent/vlan/config") == {}


def _fake_ip_json(monkeypatch, payload):
    monkeypatch.setattr(vlan_manager, "_run", lambda cmd: (0, payload, ""))


def test_non_dotted_bridge_member_vlan_is_not_dropped(monkeypatch, tmp_path):
    """The regression: no linkinfo (bridge member) AND no dot in the name."""
    _fake_ip_json(monkeypatch, """[
      {"ifname":"wan1","link":"eth1","master":"br0","flags":["UP"],"mtu":1500}
    ]""")
    monkeypatch.setattr(vlan_manager, "_proc_vlan_ids",
                        lambda *a: {"wan1": 250})
    out = vlan_manager.list_vlan_interfaces()
    assert len(out) == 1
    assert out[0]["name"] == "wan1"
    assert out[0]["vlan_id"] == 250
    assert out[0]["parent"] == "eth1"


def test_dotted_name_still_resolves_without_the_registry(monkeypatch):
    """The name-parse fallback must keep working — don't read /proc needlessly."""
    _fake_ip_json(monkeypatch, """[
      {"ifname":"eth1.100","link":"eth1","master":"br0","flags":["UP"],"mtu":1500}
    ]""")
    def _boom(*a):
        raise AssertionError("registry should not be consulted for a dotted name")
    monkeypatch.setattr(vlan_manager, "_proc_vlan_ids", _boom)
    out = vlan_manager.list_vlan_interfaces()
    assert out[0]["vlan_id"] == 100


def test_still_skipped_when_nothing_can_resolve_it(monkeypatch):
    _fake_ip_json(monkeypatch, """[
      {"ifname":"weird","link":"eth1","master":"br0","flags":["UP"],"mtu":1500}
    ]""")
    monkeypatch.setattr(vlan_manager, "_proc_vlan_ids", lambda *a: {})
    assert vlan_manager.list_vlan_interfaces() == []


# ─────────────────────────────────────────────────────────────────────────────
# Foreign bridges (docker0 etc.) must never be persisted or recreated
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("name", [
    "docker0", "docker1", "br-1a2b3c4d5e6f", "virbr0", "virbr0-nic",
    "lxcbr0", "podman0", "cni-podman0",
])
def test_foreign_bridges_detected(name):
    assert bridge_manager.is_foreign_bridge(name) is True


@pytest.mark.parametrize("name", [
    "br0", "br-wan1", "lab-br100", "lab-bridge", "docker", "br-xyz",
    "br-1a2b3c", "mydocker0",
])
def test_own_bridges_not_treated_as_foreign(name):
    assert bridge_manager.is_foreign_bridge(name) is False


# ─────────────────────────────────────────────────────────────────────────────
# v9.3: nothing outside netlink. The service is confined (ProtectKernelTunables,
# ProtectKernelModules), so writing sysctls or running modprobe would only fail.
# ─────────────────────────────────────────────────────────────────────────────
def test_create_bridge_does_not_turn_on_ip_forwarding(monkeypatch):
    """A bridge forwards at layer 2; setting ip_forward made the host a router."""
    ran, opened = [], []
    monkeypatch.setattr(bridge_manager, "_run", lambda cmd: ran.append(cmd) or (0, "", ""))
    real_open = open
    monkeypatch.setattr("builtins.open",
                        lambda f, *a, **k: opened.append(str(f)) or real_open(f, *a, **k))
    assert bridge_manager.create_bridge("br-wan1")["ok"] is True
    assert not any("ip_forward" in f or f.startswith("/proc/sys") for f in opened)
    assert ["ip", "link", "add", "name", "br-wan1", "type", "bridge"] in ran


def test_create_vlan_does_not_run_modprobe(monkeypatch):
    """The kernel loads 8021q itself when `ip link add ... type vlan` needs it."""
    ran = []
    monkeypatch.setattr(vlan_manager, "_run", lambda cmd: ran.append(cmd) or (0, "", ""))
    assert vlan_manager.create_vlan("eth1", 100)["ok"] is True
    assert not any(cmd[0] == "modprobe" for cmd in ran)
    assert ["ip", "link", "add", "link", "eth1", "name", "eth1.100",
            "type", "vlan", "id", "100"] in ran


# ─────────────────────────────────────────────────────────────────────────────
# v9.3: a bridge shows the total of its members (combine = inverse of split)
# ─────────────────────────────────────────────────────────────────────────────
def test_bridge_total_adds_member_delays():
    """Rod's example: 10 ms on one member, 40 ms on the other = 50 ms."""
    t = tc_manager.combine_member_configs([{"latency_ms": 10}, {"latency_ms": 40}])
    assert t["latency_ms"] == 50.0 and t["loss_pct"] == 0.0 and t["rate_mbit"] == 0.0


def test_bridge_total_compounds_loss():
    # 1% then 1% is 1.99% end to end, not 2%.
    t = tc_manager.combine_member_configs([{"loss_pct": 1}, {"loss_pct": 1}])
    assert t["loss_pct"] == 1.99


def test_bridge_total_rate_is_the_bottleneck():
    t = tc_manager.combine_member_configs([{"rate_mbit": 50}, {"rate_mbit": 10}, {}])
    assert t["rate_mbit"] == 10            # 0 on the third = no limit, not "0 mbit"


def test_bridge_total_of_nothing_is_zero():
    t = tc_manager.combine_member_configs([{}, None])
    assert set(t.values()) == {0.0} and len(t) == 6


@pytest.mark.parametrize("n", [1, 2, 3, 4])
@pytest.mark.parametrize("cfg", [
    {"latency_ms": 50, "jitter_ms": 8, "loss_pct": 2, "duplicate_pct": 0.2,
     "corrupt_pct": 0.1, "rate_mbit": 20},
    {"latency_ms": 150, "jitter_ms": 20, "loss_pct": 0.5, "duplicate_pct": 0,
     "corrupt_pct": 0, "rate_mbit": 10},
    {"latency_ms": 45.5, "jitter_ms": 0, "loss_pct": 8, "duplicate_pct": 1,
     "corrupt_pct": 0.5, "rate_mbit": 0},
])
def test_split_then_total_gives_back_what_was_set(cfg, n):
    """Apply X on a bridge, and the bridge must show X again."""
    each = tc_manager.split_config_for_members(cfg, n)
    total = tc_manager.combine_member_configs([each] * n)
    assert total["latency_ms"] == pytest.approx(cfg["latency_ms"], abs=0.1)
    assert total["jitter_ms"] == pytest.approx(cfg["jitter_ms"], abs=0.1)
    for k in ("loss_pct", "duplicate_pct", "corrupt_pct"):
        assert total[k] == pytest.approx(cfg[k], abs=0.001), k
    assert total["rate_mbit"] == cfg["rate_mbit"]
