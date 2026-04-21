"""app.py v8.1 — fixes: ASCII log strings, HTTP exception handler, port 5000, favicon"""
import os, json, logging
from pathlib import Path
from flask import Flask, request, jsonify, render_template, abort
from flask_login import login_required, current_user
from werkzeug.exceptions import HTTPException
from auth           import auth_bp, login_manager, get_or_create_secret, ensure_default_user, admin_required
from tc_manager     import (apply_netem, remove_qdisc, get_qdisc_stats,
                             list_interfaces, detect_all_tc_configs, split_config_for_members)
from bridge_manager import (create_bridge, delete_bridge, add_member, remove_member,
                             set_bridge_up, get_bridge_stats, get_all_bridges,
                             get_all_link_info, list_unbridged_interfaces)
from vlan_manager   import (list_vlan_interfaces, list_physical_interfaces,
                             create_vlan, delete_vlan, set_iface_up, get_iface_stats)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = get_or_create_secret()
login_manager.init_app(app)
app.register_blueprint(auth_bp)

PROFILES_DIR  = Path("profiles")
STATE_FILE    = Path("state.json")
LABELS_FILE   = Path("labels.json")
CONFIG_FILE   = Path("config.json")
PROFILES_DIR.mkdir(exist_ok=True)

VALID          = set("abcdefghijklmnopqrstuvwxyz0123456789._-")
DEFAULT_CONFIG = {"idle_timeout_minutes": 30}

# ── Error handler: pass HTTP errors (4xx) through cleanly; only log real 5xx ──
@app.errorhandler(Exception)
def handle_exception(e):
    if isinstance(e, HTTPException):
        return jsonify({"ok": False, "stderr": e.description}), e.code
    logger.exception("Unhandled server error: %s", e)
    return jsonify({"ok": False, "stderr": str(e)}), 500

# ── Suppress favicon 404 noise ─────────────────────────────────────────────────
@app.route("/favicon.ico")
def favicon():
    return "", 204

_state  = {}
_labels = {}
_config = {}

def _load_json(p, default=None):
    try:    return json.loads(p.read_text()) if p.exists() else (default or {})
    except: return default or {}

def _save_json(p, data):
    try:    p.write_text(json.dumps(data, indent=2))
    except Exception as e: logger.warning("Save %s: %s", p, e)

def _init():
    global _state, _labels, _config
    ensure_default_user()
    _labels = _load_json(LABELS_FILE)
    _config = {**DEFAULT_CONFIG, **_load_json(CONFIG_FILE)}
    saved   = _load_json(STATE_FILE)
    live    = detect_all_tc_configs(list_interfaces())
    _state  = {**saved, **live}
    _save_json(STATE_FILE, _state)
    if live: logger.info("Detected tc on: %s", list(live.keys()))

_init()

def vname(s, maxlen=20):
    if not s or len(s) > maxlen or not all(c in VALID for c in s.lower()):
        abort(400, f"Invalid name: {s!r}")
    return s

def vconfig(data):
    def clamp(v, lo, hi): return max(lo, min(hi, float(v)))
    clean = {}
    for k, lo, hi in [("latency_ms",0,60000),("jitter_ms",0,10000),("loss_pct",0,100),
                      ("duplicate_pct",0,100),("corrupt_pct",0,100),("rate_mbit",0,100000)]:
        if k in data: clean[k] = clamp(data[k], lo, hi)
    return clean

def vlan_id_ok(v):
    try:    return 1 <= int(v) <= 4094
    except: return False

# ── UI ─────────────────────────────────────────────────────────────────────────
@app.route("/")
@login_required
def index(): return render_template("index.html")

# ── Discovery ──────────────────────────────────────────────────────────────────
@app.route("/api/interfaces")
@login_required
def api_interfaces():
    bridges   = get_all_bridges()
    all_links = get_all_link_info()
    ifaces    = list_interfaces()
    unbridged = list_unbridged_interfaces()
    member_of = {m: br for br, info in bridges.items() for m in info.get("members", [])}
    meta = {}
    for link in all_links:
        n = link.get("ifname", ""); f = link.get("flags", [])
        meta[n] = {"is_bridge": n in bridges, "is_member": n in member_of,
                   "master": member_of.get(n, ""), "state": "up" if "UP" in f else "down",
                   "mtu": link.get("mtu", "")}
    return jsonify({"interfaces": ifaces, "bridges": bridges, "unbridged": unbridged,
                    "meta": meta, "state": _state, "labels": _labels})

# ── TC ─────────────────────────────────────────────────────────────────────────
@app.route("/api/stats/<iface>")
@login_required
def api_stats(iface): return jsonify(get_qdisc_stats(vname(iface)))

@app.route("/api/apply/<iface>", methods=["POST"])
@login_required
def api_apply(iface):
    iface = vname(iface); config = vconfig(request.get_json(force=True) or {})
    bridges = get_all_bridges()
    if iface in bridges:
        members = bridges[iface].get("members", [])
        if not members:
            return jsonify({"ok": False, "is_bridge": True, "stderr": f"{iface} has no members"}), 400
        mc = split_config_for_members(config, len(members))
        results = {}; all_ok = True
        for m in members:
            r = apply_netem(m, mc); results[m] = r
            if r["ok"]: _state[m] = mc
            else:       all_ok = False
        _state[iface] = config; _save_json(STATE_FILE, _state)
        return jsonify({"ok": all_ok, "is_bridge": True, "members": members,
                        "results": results, "split_cfg": mc}), 200 if all_ok else 500
    result = apply_netem(iface, config)
    if result["ok"]: _state[iface] = config; _save_json(STATE_FILE, _state)
    return jsonify(result), 200 if result["ok"] else 500

@app.route("/api/reset/<iface>", methods=["POST"])
@login_required
def api_reset(iface):
    iface = vname(iface); bridges = get_all_bridges()
    if iface in bridges:
        members = bridges[iface].get("members", [])
        results = {m: remove_qdisc(m) for m in members}
        for m, r in results.items():
            if r["ok"]: _state.pop(m, None)
        _state.pop(iface, None); _save_json(STATE_FILE, _state)
        return jsonify({"ok": all(v["ok"] for v in results.values()) if results else True,
                        "is_bridge": True, "members": results})
    result = remove_qdisc(iface)
    if result["ok"]: _state.pop(iface, None); _save_json(STATE_FILE, _state)
    return jsonify(result)

# ── Labels ─────────────────────────────────────────────────────────────────────
@app.route("/api/labels/<iface>", methods=["POST"])
@login_required
def api_set_label(iface):
    iface = vname(iface); data = request.get_json(force=True) or {}
    label = str(data.get("label", ""))[:80]
    if label: _labels[iface] = label
    else:     _labels.pop(iface, None)
    _save_json(LABELS_FILE, _labels); return jsonify({"ok": True})

# ── Config ─────────────────────────────────────────────────────────────────────
@app.route("/api/config")
@login_required
def api_get_config(): return jsonify(_config)

@app.route("/api/config", methods=["POST"])
@login_required
@admin_required
def api_set_config():
    global _config
    data = request.get_json(force=True) or {}
    if "idle_timeout_minutes" in data:
        try:
            v = int(data["idle_timeout_minutes"])
            if v < 0: return jsonify({"ok": False, "error": "Must be >= 0"}), 400
            _config["idle_timeout_minutes"] = v
        except: return jsonify({"ok": False, "error": "Invalid value"}), 400
    _save_json(CONFIG_FILE, _config)
    return jsonify({"ok": True, "config": _config})

# ── Bridges ────────────────────────────────────────────────────────────────────
@app.route("/api/bridges")
@login_required
def api_bridges(): return jsonify(get_all_bridges())

@app.route("/api/bridges/<name>", methods=["POST"])
@login_required
def api_create_bridge(name):
    data = request.get_json(force=True) or {}
    return jsonify(create_bridge(vname(name), bool(data.get("stp", False))))

@app.route("/api/bridges/<name>", methods=["DELETE"])
@login_required
def api_delete_bridge(name): return jsonify(delete_bridge(vname(name)))

@app.route("/api/bridges/<name>/up", methods=["POST"])
@login_required
def api_bridge_updown(name):
    data = request.get_json(force=True) or {}
    return jsonify(set_bridge_up(vname(name), up=bool(data.get("up", True))))

@app.route("/api/bridges/<name>/members", methods=["POST"])
@login_required
def api_add_member(name):
    data = request.get_json(force=True) or {}
    return jsonify(add_member(vname(name), vname(data.get("iface", ""))))

@app.route("/api/bridges/<name>/members/<iface>", methods=["DELETE"])
@login_required
def api_remove_member(name, iface):
    vname(name); return jsonify(remove_member(vname(iface)))

@app.route("/api/bridges/<name>/stats")
@login_required
def api_bridge_stats(name): return jsonify(get_bridge_stats(vname(name)))

# ── VLANs ──────────────────────────────────────────────────────────────────────
@app.route("/api/vlans")
@login_required
def api_vlans():
    return jsonify({"vlans":    list_vlan_interfaces(),
                    "physical": list_physical_interfaces(),
                    "bridges":  list(get_all_bridges().keys())})

@app.route("/api/vlans", methods=["POST"])
@login_required
def api_create_vlan():
    data    = request.get_json(force=True) or {}
    parent  = vname(data.get("parent", ""))
    vid_raw = data.get("vlan_id", 0)
    if not vlan_id_ok(vid_raw):
        return jsonify({"ok": False, "stderr": "VLAN ID must be 1-4094"}), 400
    name = data.get("name", "").strip()
    if name:
        safe = set("abcdefghijklmnopqrstuvwxyz0123456789._-")
        if not all(c in safe for c in name.lower()) or len(name) > 20:
            return jsonify({"ok": False, "stderr": "Invalid name"}), 400
    return jsonify(create_vlan(parent, int(vid_raw), name or None))

@app.route("/api/vlans/<name>", methods=["DELETE"])
@login_required
def api_delete_vlan(name): return jsonify(delete_vlan(vname(name)))

@app.route("/api/vlans/<name>/up", methods=["POST"])
@login_required
def api_vlan_up(name):
    data = request.get_json(force=True) or {}
    return jsonify(set_iface_up(vname(name), up=bool(data.get("up", True))))

@app.route("/api/vlans/<name>/stats")
@login_required
def api_vlan_stats(name): return jsonify(get_iface_stats(vname(name)))

@app.route("/api/iface/<name>/up", methods=["POST"])
@login_required
def api_iface_up(name):
    data = request.get_json(force=True) or {}
    return jsonify(set_iface_up(vname(name), up=bool(data.get("up", True))))

# ── Profiles ───────────────────────────────────────────────────────────────────
@app.route("/api/profiles")
@login_required
def api_list_profiles():
    return jsonify({f.stem: json.loads(f.read_text()) for f in PROFILES_DIR.glob("*.json")})

@app.route("/api/profiles/<name>", methods=["GET"])
@login_required
def api_get_profile(name):
    p = PROFILES_DIR / f"{vname(name)}.json"
    return jsonify(json.loads(p.read_text())) if p.exists() else abort(404)

@app.route("/api/profiles/<name>", methods=["POST"])
@login_required
def api_save_profile(name):
    config = vconfig(request.get_json(force=True) or {})
    (PROFILES_DIR / f"{vname(name)}.json").write_text(json.dumps(config, indent=2))
    return jsonify({"ok": True})

@app.route("/api/profiles/<name>", methods=["DELETE"])
@login_required
def api_delete_profile(name):
    p = PROFILES_DIR / f"{vname(name)}.json"
    if p.exists(): p.unlink()
    return jsonify({"ok": True})

# ── Entry point ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    if os.geteuid() != 0:
        print("[WARNING] Not root -- tc/bridge/vlan/cert commands require root.")
    from ssl_gen import ensure_cert
    cert, key = ensure_cert()
    print("[TLS] HTTPS on https://0.0.0.0:5000")
    print("[TLS] To skip Chrome warning: chrome://settings/certificates")
    print("      Authorities -> Import cert.pem -> Trust for HTTPS")
    app.run(host="0.0.0.0", port=5000, ssl_context=(cert, key), debug=False, threaded=True)
