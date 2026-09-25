"""Manager-layer regression tests — run: python -m pytest -q"""
import importlib, os, sys, tempfile
import pytest

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO)
os.environ.setdefault("TC_LAB_STATE_DIR", tempfile.mkdtemp(prefix="tc_lab_mgr_"))
vlan_manager   = importlib.import_module("vlan_manager")
bridge_manager = importlib.import_module("bridge_manager")


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
