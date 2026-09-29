"""mgmt_guard.py — keeping the management interface out of the lab.

The management interface is the one the dashboard (and SSH) is reached on. Using
it in the lab is dangerous: adding it to a bridge wipes its IP address, and
bringing it down or impairing it cuts off access. So:

- the admin can LOCK it (config.json "protect_management"): VLANs on it, bridge
  membership for it or its VLANs, and bringing it down are then refused;
- whether locked or not, nothing involving it is ever saved: such VLANs and
  bridges are left out of network_config.json, and impairments on it out of
  state.json, so a reboot always returns it to normal.

Pure functions, standard library only: used by app.py and, at boot, by
restore_helper.py (which runs outside the virtualenv).
"""
import json, os

DEFAULT_PROTECT = True


def settings(config):
    """(interface, locked) from a config dict. No interface configured → ("", False)."""
    iface = str((config or {}).get("management_interface") or "")
    return iface, bool(iface) and bool((config or {}).get("protect_management", DEFAULT_PROTECT))


def load_settings(state_dir):
    """settings() read from STATE_DIR/config.json — for restore_helper at boot."""
    try:
        with open(os.path.join(state_dir, "config.json")) as f:
            return settings(json.load(f))
    except (OSError, ValueError):
        return "", False


def related(mgmt, vlans=()):
    """Every interface that means using the management interface: the interface
    itself and any VLAN on it — by parent, or by the usual `<mgmt>.<id>` name.
    `vlans` is a list of {"name", "parent"} dicts."""
    if not mgmt:
        return set()
    out = {mgmt}
    for v in vlans or ():
        if v.get("parent") == mgmt or str(v.get("name", "")).startswith(mgmt + "."):
            out.add(v.get("name"))
    return out


def is_related(name, mgmt, vlans=()):
    return bool(mgmt) and (name in related(mgmt, vlans) or str(name).startswith(mgmt + "."))


def filter_net_config(conf, mgmt):
    """network_config without anything involving the management interface:
    its VLANs, and — whole — any bridge with such a member.
    Returns (clean_conf, dropped_names)."""
    conf = conf or {}
    vlans = list(conf.get("vlans") or [])
    bridges = dict(conf.get("bridges") or {})
    if not mgmt:
        return {"bridges": bridges, "vlans": vlans}, []
    rel = related(mgmt, vlans)
    dropped = []
    keep_vlans = []
    for v in vlans:
        if v.get("name") in rel:
            dropped.append(v.get("name"))
        else:
            keep_vlans.append(v)
    keep_bridges = {}
    for br, info in bridges.items():
        members = (info or {}).get("members") or []
        if any(m in rel or str(m).startswith(mgmt + ".") for m in members):
            dropped.append(br)
        else:
            keep_bridges[br] = info
    return {"bridges": keep_bridges, "vlans": keep_vlans}, dropped


def filter_state(state, mgmt, vlans=()):
    """state.json content without impairments on the management interface (or its
    VLANs): they apply now, but are never re-applied after a reboot."""
    rel = related(mgmt, vlans)
    return {k: v for k, v in (state or {}).items()
            if k not in rel and not (mgmt and str(k).startswith(mgmt + "."))}
