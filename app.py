"""app.py v9.2.1"""
import os, json, logging, subprocess
from datetime import timedelta
from pathlib import Path
from flask import Flask, request, jsonify, render_template, abort
from flask_login import login_required, current_user
from flask_wtf import CSRFProtect
from werkzeug.exceptions import HTTPException
from auth           import (auth_bp, login_manager, limiter, get_or_create_secret,
                            ensure_default_user, admin_required, role_required,
                            list_users, create_user, delete_user, set_password,
                            set_role, VALID_ROLES)
from tc_manager     import (apply_netem, remove_qdisc, get_qdisc_stats,
                             list_interfaces, detect_all_tc_configs, split_config_for_members)
from bridge_manager import (create_bridge, delete_bridge, add_member, remove_member,
                             set_bridge_up, get_bridge_stats, get_all_bridges,
                             get_all_link_info, list_unbridged_interfaces,
                             is_foreign_bridge)
from vlan_manager   import (list_vlan_interfaces, list_physical_interfaces,
                             create_vlan, delete_vlan, set_iface_up, get_iface_stats)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = get_or_create_secret()
app.config.update(
    SESSION_COOKIE_SECURE=True,        # HTTPS-only app — never send cookies over http
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Strict",
    REMEMBER_COOKIE_SECURE=True,
    REMEMBER_COOKIE_HTTPONLY=True,
    REMEMBER_COOKIE_SAMESITE="Strict",
    # "Keep me signed in" — Flask-Login's own default is 365 days, far too long for
    # a tool that runs as root. A working week, then sign in again.
    REMEMBER_COOKIE_DURATION=timedelta(days=7),
    PERMANENT_SESSION_LIFETIME=timedelta(hours=12),
    MAX_CONTENT_LENGTH=512 * 1024,     # reject oversized request bodies
)
login_manager.init_app(app)
limiter.init_app(app)
csrf = CSRFProtect(app)               # protects every POST/PUT/PATCH/DELETE
app.register_blueprint(auth_bp)

# ── Security headers (one place, every response) ───────────────────────────────
@app.after_request
def _security_headers(resp):
    resp.headers["X-Frame-Options"]        = "DENY"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Referrer-Policy"]        = "same-origin"
    resp.headers["Cross-Origin-Opener-Policy"] = "same-origin"
    resp.headers["Strict-Transport-Security"]  = "max-age=31536000"
    resp.headers.setdefault("Cache-Control", "no-store")
    resp.headers.setdefault("Content-Security-Policy",
        "default-src 'self'; img-src 'self' data:; "
        "style-src 'self' 'unsafe-inline'; script-src 'self' 'unsafe-inline'; "
        "base-uri 'none'; frame-ancestors 'none'")
    return resp

# All writable state lives under STATE_DIR (default: cwd, i.e. /opt/tc_lab under
# systemd). Set TC_LAB_STATE_DIR to move it elsewhere, e.g. onto its own mount.
STATE_DIR      = Path(os.environ.get("TC_LAB_STATE_DIR", "."))
PROFILES_DIR   = STATE_DIR / "profiles"
STATE_FILE     = STATE_DIR / "state.json"
LABELS_FILE    = STATE_DIR / "labels.json"
CONFIG_FILE    = STATE_DIR / "config.json"
NET_CONFIG_FILE = STATE_DIR / "network_config.json"   # ← persistence for bridges + VLANs
PROFILES_DIR.mkdir(parents=True, exist_ok=True)

VALID          = set("abcdefghijklmnopqrstuvwxyz0123456789._-")
DEFAULT_CONFIG = {"idle_timeout_minutes": 30, "bind_address": "0.0.0.0", "port": 5000}

# ── Error handler ──────────────────────────────────────────────────────────────
@app.errorhandler(Exception)
def handle_exception(e):
    if isinstance(e, HTTPException):
        return jsonify({"ok": False, "stderr": e.description}), e.code
    logger.exception("Unhandled server error: %s", e)          # detail → log only
    return jsonify({"ok": False, "stderr": "Internal server error"}), 500

@app.errorhandler(429)
def handle_ratelimit(e):
    if request.path == "/login":
        return render_template("login.html", rate_limited=True), 429
    return jsonify({"ok": False, "stderr": f"Too many requests — {e.description}"}), 429

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

# ── Network config persistence ─────────────────────────────────────────────────

def save_net_config():
    """Snapshot current bridges+members and VLANs to network_config.json."""
    try:
        bridges = get_all_bridges()
        vlans   = list_vlan_interfaces()
        skipped = [br for br in bridges if is_foreign_bridge(br)]
        if skipped:
            logger.info("Not persisting foreign bridge(s): %s", ", ".join(skipped))
        data = {
            "bridges": {
                br: {"members": info.get("members", []), "stp": False}
                for br, info in bridges.items() if not is_foreign_bridge(br)
            },
            "vlans": [
                {"name": v["name"], "parent": v["parent"], "vlan_id": v["vlan_id"]}
                for v in vlans
            ]
        }
        _save_json(NET_CONFIG_FILE, data)
        logger.info("Network config saved (%d bridges, %d VLANs)",
                    len(data["bridges"]), len(data["vlans"]))
    except Exception as e:
        logger.warning("save_net_config failed: %s", e)


def restore_via_script():
    """Run restore_network.sh to re-create VLANs/bridges/members before tc restore."""
    # Always use absolute path — works from any CWD (systemd ExecStartPre, app startup, import)
    install_dir = Path(__file__).parent.resolve()
    state_dir   = STATE_DIR.resolve()
    script = install_dir / "restore_network.sh"
    if not script.exists():
        logger.warning("restore_network.sh not found at %s", script)
        return
    if not NET_CONFIG_FILE.exists():
        logger.info("No network_config.json — nothing to restore")
        return
    logger.info("Running restore_network.sh (state=%s) ...", state_dir)
    try:
        r = subprocess.run(
            ["bash", str(script)],
            capture_output=True, text=True, timeout=60,
            cwd=str(install_dir),
            env={**os.environ, "TC_LAB_STATE_DIR": str(state_dir)},
        )
        for line in r.stdout.splitlines():
            logger.info("  restore: %s", line)
        if r.returncode != 0:
            logger.warning("restore_network.sh exited %d: %s", r.returncode, r.stderr)
        else:
            logger.info("restore_network.sh completed OK")
    except Exception as e:
        logger.warning("restore_network.sh error: %s", e)


def _reapply_tc(saved, bridge_names):
    """Re-push saved tc rules to kernel after a reboot."""
    if not saved:
        return
    logger.info("Re-applying %d saved tc rule(s)...", len(saved))
    ok_count = 0
    for iface, config in saved.items():
        if iface in bridge_names:
            continue
        if not config or not any(float(v) > 0 for v in config.values()):
            continue
        try:
            r = apply_netem(iface, config)
            if r["ok"]:
                logger.info("  tc restored: %s %s", iface, config)
                ok_count += 1
            else:
                logger.warning("  tc restore failed: %s — %s", iface, r["stderr"])
        except Exception as e:
            logger.warning("  tc restore error: %s — %s", iface, e)
    logger.info("tc re-apply done: %d/%d succeeded", ok_count,
                sum(1 for i, c in saved.items()
                    if i not in bridge_names and any(float(v) > 0 for v in c.values())))


def _init():
    global _state, _labels, _config
    ensure_default_user()
    _labels = _load_json(LABELS_FILE)
    _config = {**DEFAULT_CONFIG, **_load_json(CONFIG_FILE)}
    # Safe mode: come up without recreating topology or re-applying/adopting any
    # tc rules already on the host. Use when running a second instance (test,
    # staging) on a box whose interfaces are managed by another process.
    if os.environ.get("TC_LAB_SKIP_RESTORE"):
        _state = _load_json(STATE_FILE)
        logger.warning("TC_LAB_SKIP_RESTORE set — skipping topology restore, "
                       "tc re-apply and live-scan")
        return
    # 1. Restore VLANs + bridges + members via shell script (reliable ordering)
    restore_via_script()
    # 2. Load saved tc state
    saved = _load_json(STATE_FILE)
    # 3. Re-apply saved tc rules to the kernel
    bridge_names = set(get_all_bridges().keys())
    _reapply_tc(saved, bridge_names)
    # 4. Scan live rules
    live   = detect_all_tc_configs(list_interfaces())
    _state = {**saved, **live}
    _save_json(STATE_FILE, _state)
    if live: logger.info("Live tc detected on: %s", list(live.keys()))

def _name_ok(s, maxlen=20):
    """Predicate form of vname() — safe to call on untrusted dict keys/values.

    ASCII letters (either case), digits, '.', '_' and '-' only; at most `maxlen`
    characters; must not start with '-' (so a name can never be read as a
    `-flag` by ip/tc) or '.' (so it can never be '..'). isascii() is checked
    first because str.lower() maps some non-ASCII characters onto ASCII
    letters — U+212A KELVIN SIGN becomes 'k' — which would otherwise pass the
    charset check while the original, non-ASCII name is the one used."""
    s = str(s)
    if not s or not s.isascii() or len(s) > maxlen or s[0] in ".-":
        return False
    return all(c in VALID for c in s.lower())

def vname(s, maxlen=20):
    if not _name_ok(s, maxlen):
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

def _show(v, maxlen=40):
    """Quote a rejected value for an error message, truncated. The name that
    failed validation is echoed back so the admin can find it in their bundle,
    but it is attacker-supplied and unbounded in length -- cap it."""
    s = repr(v)
    return s if len(s) <= maxlen else s[:maxlen] + "...'"

def _sanitize_bundle(bundle):
    """Validate an imported config bundle before any of it is written to disk or
    replayed through `ip`/`tc`. Returns a cleaned copy; raises ValueError on any
    violation so the whole bundle is rejected (see api_import)."""
    if not isinstance(bundle, dict):
        raise ValueError("bundle must be a JSON object")
    clean = {}

    if "version" in bundle:
        clean["version"] = str(bundle["version"])[:20]

    if "profiles" in bundle:
        profs = bundle["profiles"]
        if not isinstance(profs, dict):
            raise ValueError("profiles must be an object")
        out = {}
        for name, cfg in profs.items():
            if not _name_ok(name):
                raise ValueError(f"invalid profile name: {_show(name)}")
            if not isinstance(cfg, dict):
                raise ValueError(f"invalid profile config for {_show(name)}")
            out[name] = vconfig(cfg)
        clean["profiles"] = out

    if "labels" in bundle:
        labels = bundle["labels"]
        if not isinstance(labels, dict):
            raise ValueError("labels must be an object")
        out = {}
        for iface, text in labels.items():
            if not _name_ok(iface):
                raise ValueError(f"invalid label interface: {_show(iface)}")
            out[iface] = str(text)[:80]
        clean["labels"] = out

    if "tc_state" in bundle:
        st = bundle["tc_state"]
        if not isinstance(st, dict):
            raise ValueError("tc_state must be an object")
        out = {}
        for iface, cfg in st.items():
            if not _name_ok(iface):
                raise ValueError(f"invalid tc_state interface: {_show(iface)}")
            if not isinstance(cfg, dict):
                raise ValueError(f"invalid tc_state config for {_show(iface)}")
            out[iface] = vconfig(cfg)
        clean["tc_state"] = out

    if bundle.get("network"):
        net = bundle["network"]
        if not isinstance(net, dict):
            raise ValueError("network must be an object")
        cn = {"bridges": {}, "vlans": []}
        for br, info in (net.get("bridges") or {}).items():
            if not _name_ok(br):
                raise ValueError(f"invalid bridge name: {_show(br)}")
            if not isinstance(info, dict):
                raise ValueError(f"invalid bridge info for {_show(br)}")
            members = info.get("members") or []
            if not isinstance(members, list):
                raise ValueError(f"invalid members list for {_show(br)}")
            for m in members:
                if not _name_ok(m):
                    raise ValueError(f"invalid bridge member: {_show(m)}")
            cn["bridges"][br] = {"members": list(members),
                                 "stp": bool(info.get("stp", False))}
        vlans = net.get("vlans") or []
        if not isinstance(vlans, list):
            raise ValueError("network.vlans must be a list")
        for v in vlans:
            if not isinstance(v, dict):
                raise ValueError("invalid vlan entry")
            nm, pa, vid = v.get("name", ""), v.get("parent", ""), v.get("vlan_id")
            if not _name_ok(nm):
                raise ValueError(f"invalid vlan name: {_show(nm)}")
            if not _name_ok(pa):
                raise ValueError(f"invalid vlan parent: {_show(pa)}")
            if not vlan_id_ok(vid):
                raise ValueError(f"invalid vlan id: {_show(vid)}")
            cn["vlans"].append({"name": nm, "parent": pa, "vlan_id": int(vid)})
        clean["network"] = cn

    return clean

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
    iface = vname(iface); config = vconfig(request.get_json(silent=True) or {})
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
    iface = vname(iface); data = request.get_json(silent=True) or {}
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
    data = request.get_json(silent=True) or {}
    if "idle_timeout_minutes" in data:
        try:
            v = int(data["idle_timeout_minutes"])
            if v < 0: return jsonify({"ok": False, "error": "Must be >= 0"}), 400
            _config["idle_timeout_minutes"] = v
        except: return jsonify({"ok": False, "error": "Invalid value"}), 400
    _save_json(CONFIG_FILE, _config)
    return jsonify({"ok": True, "config": _config})

# ── User management (admin only) ───────────────────────────────────────────────
# Every route here is @admin_required, so a "user" role gets 403 regardless of
# what the browser sends. Responses never include password hashes.

@app.route("/api/users")
@login_required
@admin_required
def api_list_users():
    return jsonify({"ok": True, "users": list_users(), "roles": list(VALID_ROLES),
                    "self": current_user.id})

@app.route("/api/users", methods=["POST"])
@login_required
@admin_required
def api_create_user():
    data = request.get_json(silent=True) or {}
    username = str(data.get("username", "")).strip()
    if not _name_ok(username):
        return jsonify({"ok": False, "error":
            "Username must be 1-20 chars of a-z 0-9 . _ - and start with a letter or digit"}), 400
    ok, msg = create_user(username, data.get("password", ""),
                          data.get("role", "user"))
    return jsonify({"ok": ok, "error": None if ok else msg,
                    "message": msg if ok else None}), 200 if ok else 400

@app.route("/api/users/<username>", methods=["DELETE"])
@login_required
@admin_required
def api_delete_user(username):
    ok, msg = delete_user(vname(username), acting_user=current_user.id)
    return jsonify({"ok": ok, "error": None if ok else msg,
                    "message": msg if ok else None}), 200 if ok else 400

@app.route("/api/users/<username>/password", methods=["POST"])
@login_required
@admin_required
def api_reset_password(username):
    """Admin reset — does not require the target's current password. Admins can
    only set a new one; no route ever reveals an existing password or hash."""
    data = request.get_json(silent=True) or {}
    ok, msg = set_password(vname(username), data.get("new", ""))
    return jsonify({"ok": ok, "error": None if ok else msg,
                    "message": msg if ok else None}), 200 if ok else 400

@app.route("/api/users/<username>/role", methods=["POST"])
@login_required
@admin_required
def api_set_role(username):
    data = request.get_json(silent=True) or {}
    ok, msg = set_role(vname(username), data.get("role", ""),
                       acting_user=current_user.id)
    return jsonify({"ok": ok, "error": None if ok else msg,
                    "message": msg if ok else None}), 200 if ok else 400

# ── Bridges ────────────────────────────────────────────────────────────────────
@app.route("/api/bridges")
@login_required
def api_bridges(): return jsonify(get_all_bridges())

@app.route("/api/bridges/<name>", methods=["POST"])
@login_required
@admin_required
def api_create_bridge(name):
    data = request.get_json(silent=True) or {}
    r = create_bridge(vname(name), bool(data.get("stp", False)))
    if r["ok"]: save_net_config()          # ← persist
    return jsonify(r)

@app.route("/api/bridges/<name>", methods=["DELETE"])
@login_required
@admin_required
def api_delete_bridge(name):
    r = delete_bridge(vname(name))
    if r["ok"]: save_net_config()          # ← persist
    return jsonify(r)

@app.route("/api/bridges/<name>/up", methods=["POST"])
@login_required
@admin_required
def api_bridge_updown(name):
    data = request.get_json(silent=True) or {}
    return jsonify(set_bridge_up(vname(name), up=bool(data.get("up", True))))

@app.route("/api/bridges/<name>/members", methods=["POST"])
@login_required
@admin_required
def api_add_member(name):
    data = request.get_json(silent=True) or {}
    r = add_member(vname(name), vname(data.get("iface", "")))
    if r["ok"]: save_net_config()          # ← persist
    return jsonify(r)

@app.route("/api/bridges/<name>/members/<iface>", methods=["DELETE"])
@login_required
@admin_required
def api_remove_member(name, iface):
    vname(name)
    r = remove_member(vname(iface))
    if r["ok"]: save_net_config()          # ← persist
    return jsonify(r)

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
@admin_required
def api_create_vlan():
    data    = request.get_json(silent=True) or {}
    parent  = vname(data.get("parent", ""))
    vid_raw = data.get("vlan_id", 0)
    if not vlan_id_ok(vid_raw):
        return jsonify({"ok": False, "stderr": "VLAN ID must be 1-4094"}), 400
    name = data.get("name", "").strip()
    if name and not _name_ok(name):
        return jsonify({"ok": False, "stderr": "Invalid name"}), 400
    r = create_vlan(parent, int(vid_raw), name or None)
    if r["ok"]: save_net_config()          # ← persist
    return jsonify(r)

@app.route("/api/vlans/<name>", methods=["DELETE"])
@login_required
@admin_required
def api_delete_vlan(name):
    r = delete_vlan(vname(name))
    if r["ok"]: save_net_config()          # ← persist
    return jsonify(r)

@app.route("/api/vlans/<name>/up", methods=["POST"])
@login_required
@admin_required
def api_vlan_up(name):
    data = request.get_json(silent=True) or {}
    return jsonify(set_iface_up(vname(name), up=bool(data.get("up", True))))

@app.route("/api/vlans/<name>/stats")
@login_required
def api_vlan_stats(name): return jsonify(get_iface_stats(vname(name)))

@app.route("/api/iface/<name>/up", methods=["POST"])
@login_required
@admin_required
def api_iface_up(name):
    data = request.get_json(silent=True) or {}
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
    config = vconfig(request.get_json(silent=True) or {})
    (PROFILES_DIR / f"{vname(name)}.json").write_text(json.dumps(config, indent=2))
    return jsonify({"ok": True})

@app.route("/api/profiles/<name>", methods=["DELETE"])
@login_required
def api_delete_profile(name):
    p = PROFILES_DIR / f"{vname(name)}.json"
    if p.exists(): p.unlink()
    return jsonify({"ok": True})


# ── Export / Import ────────────────────────────────────────────────────────────
@app.route("/api/export")
@login_required
def api_export():
    """Bundle network config, tc state, labels and profiles into one JSON."""
    from datetime import datetime, timezone
    profiles = {}
    for f in PROFILES_DIR.glob("*.json"):
        try: profiles[f.stem] = json.loads(f.read_text())
        except: pass
    bundle = {
        "version":  "9.2.1",
        "exported": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "network":  _load_json(NET_CONFIG_FILE),
        "tc_state": _load_json(STATE_FILE),
        "labels":   _load_json(LABELS_FILE),
        "profiles": profiles
    }
    from flask import Response
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    return Response(
        json.dumps(bundle, indent=2),
        mimetype="application/json",
        headers={"Content-Disposition": f"attachment; filename=tc_lab_config_{ts}.json"}
    )

@app.route("/api/import", methods=["POST"])
@login_required
@admin_required
def api_import():
    """Restore a previously exported config bundle."""
    global _state, _labels
    try:
        bundle = request.get_json(silent=True) or {}
    except Exception as e:
        logger.warning("Import: unreadable request body: %s", e)   # detail → log only
        return jsonify({"ok": False, "stderr": "Invalid JSON"}), 400

    try:
        bundle = _sanitize_bundle(bundle)
    except ValueError as e:
        logger.warning("Rejected import bundle: %s", e)
        return jsonify({"ok": False, "stderr": f"Rejected bundle: {e}"}), 400

    ver = bundle.get("version", "?")
    imported = []

    # Profiles
    profs = bundle.get("profiles", {})
    for name, cfg in profs.items():
        try:
            (PROFILES_DIR / f"{name}.json").write_text(json.dumps(cfg, indent=2))
            imported.append(f"profile:{name}")
        except Exception as e:
            logger.warning("Import profile %s: %s", name, e)

    # Labels
    if "labels" in bundle:
        _labels = bundle["labels"]
        _save_json(LABELS_FILE, _labels)
        imported.append("labels")

    # TC state — save to disk; will be re-applied on next restart
    if "tc_state" in bundle:
        _state = bundle["tc_state"]
        _save_json(STATE_FILE, _state)
        imported.append("tc_state")

    # Network config — save to disk; apply immediately via restore script
    if "network" in bundle and bundle["network"]:
        _save_json(NET_CONFIG_FILE, bundle["network"])
        imported.append("network_config")
        # Apply network config immediately (don't wait for reboot)
        restore_via_script()
        # Re-apply tc rules right away too
        bridge_names = set(get_all_bridges().keys())
        _reapply_tc(_state, bridge_names)

    return jsonify({"ok": True, "version": ver, "imported": imported})

# ── Entry point ────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    _init()
    if os.geteuid() != 0:
        print("[WARNING] Not root -- tc/bridge/vlan/cert commands require root.")
    from ssl_gen import ensure_cert
    cert, key = ensure_cert()
    bind = _config.get("bind_address", "0.0.0.0")
    try:    port = int(_config.get("port", 5000))
    except (TypeError, ValueError): port = 5000
    print(f"[TLS] HTTPS on https://{bind}:{port}")
    print("[TLS] To skip Chrome warning: chrome://settings/certificates")
    print("      Authorities -> Import cert.pem -> Trust for HTTPS")
    app.run(host=bind, port=port, ssl_context=(cert, key),
            debug=False, threaded=True)
