#!/usr/bin/env python3
"""
restore_helper.py — called by restore_network.sh
Order: VLANs → bridges → members
TC rules re-applied separately by app.py _init()
"""
import json, subprocess, sys, time, os

CONF = os.path.join(os.environ.get("TC_LAB_STATE_DIR", "/opt/tc_lab"),
                    "network_config.json")

def log(msg):
    print(msg, flush=True)

def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    return r.returncode, r.stdout.strip(), r.stderr.strip()

_VALID = set("abcdefghijklmnopqrstuvwxyz0123456789._-")
def _safe(s):
    """Defence in depth: network_config.json is validated by app.py's
    _sanitize_bundle on import, but this script also runs standalone from
    systemd, so re-check every name before it reaches `ip`. First char must be
    alphanumeric so a name can't be read as a `-flag`."""
    s = str(s)
    if not s or len(s) > 20 or s[0] in ".-":
        return False
    return all(c in _VALID for c in s.lower())

def get_live(obj_type):
    rc, out, _ = run(["ip", "-j", "link", "show", "type", obj_type])
    try:
        return {l["ifname"] for l in json.loads(out or "[]")}
    except:
        return set()

try:
    with open(CONF) as f:
        conf = json.load(f)
except Exception as e:
    log(f"ERROR reading {CONF}: {e}")
    sys.exit(1)

vlans   = conf.get("vlans", [])
bridges = conf.get("bridges", {})
log(f"Config: {len(vlans)} VLAN(s), {len(bridges)} bridge(s)")

# ── STEP 1: VLAN sub-interfaces ──────────────────────────────────────────────
log("--- Step 1: VLANs ---")
live_vlans = get_live("vlan")
log(f"  Already live: {live_vlans or 'none'}")

for v in vlans:
    name   = v.get("name", "")
    parent = v.get("parent", "")
    vid    = v.get("vlan_id")
    # Fallback: parse vid from name if missing/invalid
    if not vid and "." in name:
        try: vid = int(name.rsplit(".", 1)[-1])
        except: pass
    if not name or not parent or not vid:
        log(f"  Skipping invalid entry (missing name/parent/vid): {v}")
        continue
    if not _safe(name) or not _safe(parent):
        log(f"  Skipping unsafe VLAN entry: name={name!r} parent={parent!r}")
        continue
    try:
        vid = int(vid)
    except:
        log(f"  Skipping {name}: invalid vlan_id={vid!r}")
        continue
    if name in live_vlans:
        run(["ip", "link", "set", name, "up"])
        log(f"  {name}: already exists — brought up")
        continue
    run(["ip", "link", "set", parent, "up"])
    rc, _, err = run(["ip","link","add","link",parent,"name",name,"type","vlan","id",str(vid)])
    if rc == 0:
        run(["ip", "link", "set", name, "up"])
        log(f"  {name}: CREATED (parent={parent}, vid={vid})")
    else:
        log(f"  {name}: FAILED — {err}")

# ── STEP 2: Bridges ──────────────────────────────────────────────────────────
log("--- Step 2: Bridges ---")
live_bridges = get_live("bridge")
log(f"  Already live: {live_bridges or 'none'}")

for br, info in bridges.items():
    if not _safe(br):
        log(f"  Skipping unsafe bridge name: {br!r}")
        continue
    if br not in live_bridges:
        rc, _, err = run(["ip", "link", "add", "name", br, "type", "bridge"])
        if rc == 0:
            run(["ip", "link", "set", br, "type", "bridge", "stp_state", "0"])
            run(["ip", "link", "set", br, "up"])
            log(f"  {br}: CREATED")
        else:
            log(f"  {br}: FAILED — {err}")
            continue
    else:
        run(["ip", "link", "set", br, "up"])
        log(f"  {br}: already exists — brought up")

    # ── STEP 3: Bridge members ───────────────────────────────────────────────
    rc, out, _ = run(["ip", "-j", "link", "show", "master", br])
    try:
        live_members = {l["ifname"] for l in json.loads(out or "[]")}
    except:
        live_members = set()

    for iface in info.get("members", []):
        if not _safe(iface):
            log(f"    Skipping unsafe member name: {iface!r}")
            continue
        if iface in live_members:
            log(f"    {iface}: already member of {br}")
            continue
        success = False
        for attempt in range(4):
            run(["ip", "addr", "flush", "dev", iface])
            run(["ip", "link", "set", iface, "up"])
            rc, _, err = run(["ip", "link", "set", iface, "master", br])
            if rc == 0:
                log(f"    {iface}: ADDED to {br} (attempt {attempt+1})")
                success = True
                break
            log(f"    {iface}: attempt {attempt+1} failed — {err}")
            time.sleep(1)
        if not success:
            log(f"    {iface}: FAILED after 4 attempts")

log("--- restore_helper.py DONE ---")
