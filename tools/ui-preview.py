#!/usr/bin/env python3
"""Render the UI with no backend, for design work.

Writes _preview.html — templates/index.html with fetch() stubbed to a fixture
of interfaces, bridges, VLANs and profiles. Open it over HTTP, e.g.

    python3 tools/ui-preview.py [role]      # role: admin (default) | user
    python3 -m http.server 8777
    # then browse to http://localhost:8777/_preview.html

Pass "user" to check which controls the non-admin role hides.
"""
import json, os, sys

ROLE = sys.argv[1] if len(sys.argv) > 1 else "admin"

SRC = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "templates", "index.html")
DST = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_preview.html")

ifaces = ["eth0", "eth1", "eth1.200", "eth1.101",
          "eth1.201", "eth1.100", "br-wan1", "br-wan2"]
bridges = {
    "br-wan1": {"members": ["eth1.200", "eth1.100"], "state": "up", "mtu": 1500},
    "br-wan2": {"members": ["eth1.101", "eth1.201"], "state": "up", "mtu": 1500},
}
meta = {}
for i in ifaces:
    master = next((b for b, v in bridges.items() if i in v["members"]), "")
    meta[i] = {"is_bridge": i in bridges, "is_member": bool(master), "master": master,
               "state": "down" if i == "eth1.201" else "up", "mtu": 1500}
state = {
    "eth1.100":  {"latency_ms": 5.0},
    "eth1.200": {"latency_ms": 5.0},
    "br-wan1":  {"latency_ms": 10, "jitter_ms": 0, "loss_pct": 0,
                    "duplicate_pct": 0, "corrupt_pct": 0, "rate_mbit": 0},
}
DATA = {
    "/api/interfaces": {"interfaces": ifaces, "bridges": bridges,
                        "unbridged": ["eth0", "eth1"], "meta": meta, "state": state,
                        "labels": {"br-wan1": "Branch office uplink",
                                   "eth1.100": "MPLS circuit"}},
    "/api/vlans": {"vlans": [{"name": f"eth1.{v}", "parent": "eth1", "vlan_id": v,
                              "proto": "802.1Q", "state": "down" if v == 201 else "up",
                              "master": "br-wan1" if v in (100, 200) else "br-wan2",
                              "mtu": 1500} for v in (200, 101, 201, 100)],
                   "physical": [{"name": "eth0", "state": "up", "mtu": 1500, "master": ""},
                                {"name": "eth1", "state": "up", "mtu": 1500, "master": ""}],
                   "bridges": list(bridges)},
    "/api/profiles": {"good_link": {"latency_ms": 0},
                      "mpls_good": {"latency_ms": 10, "rate_mbit": 100},
                      "broadband": {"latency_ms": 20, "rate_mbit": 50, "loss_pct": 0.1},
                      "high_latency_wan": {"latency_ms": 150, "jitter_ms": 20, "loss_pct": 0.5},
                      "lte_congested": {"latency_ms": 80, "jitter_ms": 30, "loss_pct": 1.5},
                      "satellite_link": {"latency_ms": 600, "jitter_ms": 50, "loss_pct": 2},
                      "packet_loss": {"loss_pct": 5, "duplicate_pct": 0.5},
                      "wan_degraded": {"latency_ms": 200, "jitter_ms": 80, "loss_pct": 8}},
    "/api/config": {"idle_timeout_minutes": 30},
    "/api/auth/whoami": {"username": "operator" if ROLE == "user" else "admin", "role": ROLE},
    "/api/users": {"ok": True, "self": "admin", "roles": ["admin", "user"],
                   "users": [{"username": "admin", "role": "admin"},
                             {"username": "operator", "role": "user"},
                             {"username": "lab-tech", "role": "user"}]},
    "/api/stats/": {"ok": True, "raw": "qdisc netem 1: root refcnt 2 limit 1000 delay 5ms\n"
                                       " Sent 128944 bytes 1043 pkt (dropped 4, overlimits 0)\n"
                                       " backlog 0b 0p requeues 0"},
}

STUB = """
/* ---- preview fixture: no backend required ---- */
window.fetch=function(u){
  const D=__DATA__;
  const k=Object.keys(D).sort((a,b)=>b.length-a.length).find(p=>String(u).startsWith(p));
  return Promise.resolve({status:200,json:()=>Promise.resolve(k?D[k]:{ok:true})});
};
""".replace("__DATA__", json.dumps(DATA))

html = open(SRC).read().replace("{{ csrf_token() }}", "PREVIEW-TOKEN")
assert "<script>" in html
html = html.replace("<script>", "<script>" + STUB, 1)
open(DST, "w").write(html)
print(f"wrote {DST} ({len(html)} bytes)")
