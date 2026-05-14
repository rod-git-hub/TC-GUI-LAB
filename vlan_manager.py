import subprocess, json as _json, logging, os as _os
logger = logging.getLogger(__name__)

def _run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    return r.returncode, r.stdout, r.stderr

def list_vlan_interfaces():
    rc, out, _ = _run(["ip", "-j", "link", "show", "type", "vlan"])
    if rc != 0 or not out.strip(): return []
    vlans = []
    try:
        for l in _json.loads(out):
            n = l.get("ifname", ""); f = l.get("flags", [])
            id_ = l.get("linkinfo", {}).get("info_data", {}).get("id")
            # Fallback: parse VLAN ID from interface name (e.g. ens224.111 → 111)
            if id_ is None and "." in n:
                try: id_ = int(n.rsplit(".", 1)[-1])
                except: pass
            if id_ is None:
                logger.warning("Cannot determine VLAN ID for %s, skipping", n)
                continue
            vlans.append({"name": n, "parent": l.get("link", ""), "vlan_id": int(id_),
                          "proto": l.get("linkinfo", {}).get("info_data", {}).get("protocol", "802.1Q"),
                          "state": "up" if "UP" in f else "down",
                          "master": l.get("master", ""), "mtu": l.get("mtu", "")})
    except Exception as e:
        logger.warning("VLAN parse: %s", e)
    return vlans

def _is_bridge(name):
    """Check sysfs — reliable regardless of info_kind population."""
    return _os.path.isdir(f"/sys/class/net/{name}/bridge")

def _is_vlan_subif(link):
    """True if interface is a VLAN sub-interface."""
    ik = link.get("linkinfo", {}).get("info_kind", "")
    if ik == "vlan":
        return True
    # Fallback: name contains a dot (e.g. ens224.100)
    name = link.get("ifname", "")
    if "." in name:
        return True
    # Has a parent link AND no explicit non-vlan kind
    if link.get("link") and ik in ("", "vlan"):
        return True
    return False

def list_physical_interfaces():
    """Return only true physical NICs — excludes bridges, VLAN sub-interfaces,
    veth, tun, dummy, bond. Safe to use as VLAN parent candidates."""
    rc, out, _ = _run(["ip", "-j", "link", "show"])
    result = []
    if rc != 0: return result
    try:
        for l in _json.loads(out):
            n  = l.get("ifname", "")
            f  = l.get("flags", [])
            ik = l.get("linkinfo", {}).get("info_kind", "")
            lt = l.get("link_type", "")
            # Skip loopback
            if n == "lo" or lt == "loopback":
                continue
            # Skip by info_kind
            if ik in ("bridge", "vlan", "veth", "tun", "dummy", "bond"):
                continue
            # Skip bridges detected via sysfs (info_kind sometimes absent)
            if _is_bridge(n):
                continue
            # Skip VLAN sub-interfaces
            if _is_vlan_subif(l):
                continue
            result.append({"name": n, "state": "up" if "UP" in f else "down",
                           "mtu": l.get("mtu", ""), "master": l.get("master", "")})
    except Exception as e:
        logger.warning("Physical iface parse: %s", e)
    return result

def create_vlan(parent, vlan_id, name=""):
    if not name: name = f"{parent}.{vlan_id}"
    if not (1 <= vlan_id <= 4094):
        return {"ok": False, "stderr": f"VLAN ID {vlan_id} out of range"}
    _run(["modprobe", "8021q"])
    _run(["ip", "link", "set", parent, "up"])
    rc, _, err = _run(["ip", "link", "add", "link", parent,
                        "name", name, "type", "vlan", "id", str(vlan_id)])
    if rc != 0: return {"ok": False, "stderr": err}
    rc2, _, err2 = _run(["ip", "link", "set", name, "up"])
    return {"ok": rc2 == 0, "stderr": err2, "name": name}

def delete_vlan(name):
    _run(["ip", "link", "set", name, "down"])
    rc, _, err = _run(["ip", "link", "del", name])
    return {"ok": rc == 0, "stderr": err}

def set_iface_up(iface, up=True):
    rc, _, err = _run(["ip", "link", "set", iface, "up" if up else "down"])
    return {"ok": rc == 0, "stderr": err}

def get_iface_stats(iface):
    rc, out, err = _run(["ip", "-s", "link", "show", iface])
    return {"ok": rc == 0, "raw": out, "stderr": err}
