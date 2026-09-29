#!/usr/bin/env bash
#
# TC Lab installer / upgrader.
#
# Safe to re-run on an existing install: your accounts, TLS certificate,
# saved impairments, topology and config.json are preserved unless you
# explicitly ask for them to be reset.
#
#   sudo bash setup.sh                  # install or upgrade (asks about accounts)
#   sudo bash setup.sh --keep-users     # never prompt, keep existing accounts
#   sudo bash setup.sh --reset-users    # never prompt, wipe accounts (fresh admin)
#   sudo bash setup.sh --no-backup      # skip the pre-upgrade snapshot
#   sudo bash setup.sh --port 8443      # dashboard port (1024-65535; default 5000)
#   sudo bash setup.sh --protect-mgmt   # lock the management interface (--allow-mgmt: don't)
#   sudo bash setup.sh --mgmt-iface IF  # say which interface that is (else: detected)
#   sudo bash setup.sh --list-backups   # show snapshots available to roll back to
#   sudo bash setup.sh --rollback       # restore the most recent snapshot
#   sudo bash setup.sh --rollback NAME  # restore a specific one (see --list-backups)
#   sudo bash setup.sh --help
#
# The code goes to /opt/tc_lab (owned by root). The service runs as the
# unprivileged system user tc-lab, and everything it writes lives in
# /var/lib/tc_lab. Upgrading from v9.2.x moves the state there automatically.
#
# Every upgrade snapshots code AND state (accounts, certificate, topology,
# saved impairments) to TC_LAB_BACKUP_DIR, default /var/backups/tc-lab.
# The five most recent are kept.
#
set -euo pipefail

INSTALL_DIR="${TC_LAB_DIR:-/opt/tc_lab}"
# Service name. Override to install a second instance, or to exercise this
# script against a scratch unit without touching a live one.
SERVICE="${TC_LAB_SERVICE:-tc_lab}"
# Where the systemd unit is written. Override for packaging or for testing an
# install into a scratch directory without touching the real service.
UNIT_DIR="${TC_LAB_UNIT_DIR:-/etc/systemd/system}"
BACKUP_DIR="${TC_LAB_BACKUP_DIR:-/var/backups/tc-lab}"
# The unit already installed, if any. An upgrade keeps its state directory and
# service user, so a custom TC_LAB_STATE_DIR does not have to be repeated.
EXISTING_UNIT="${UNIT_DIR}/${SERVICE}.service"
unit_setting() { [ -f "$EXISTING_UNIT" ] && sed -n "s/^$1=//p" "$EXISTING_UNIT" | head -1; }
# Everything the service writes: accounts, settings, certificate, saved
# impairments, topology, profiles. Owned by SVC_USER; the code stays root's.
STATE_DIR="${TC_LAB_STATE_DIR:-$(unit_setting Environment=TC_LAB_STATE_DIR || true)}"
STATE_DIR="${STATE_DIR:-/var/lib/tc_lab}"
# The unprivileged system user the service runs as. Override for scratch installs.
SVC_USER="${TC_LAB_USER:-$(unit_setting User || true)}"
SVC_USER="${SVC_USER:-tc-lab}"
# Where the tc-lab CLI symlink goes. Override for packaging or scratch installs.
BIN_DIR="${TC_LAB_BIN_DIR:-/usr/local/bin}"
KEEP_BACKUPS="${TC_LAB_KEEP_BACKUPS:-5}"
SRC_DIR="$(dirname "$(realpath "$0")")"
# Dashboard port range — the same rule as ports.py (a test keeps them in step).
# The service is not root, so it cannot listen below 1024.
PORT_MIN=1024
PORT_MAX=65535
PORT_ARG=""
PORT_SET=0
MGMT_IFACE_ARG=""
MGMT_MODE=""            # "" = ask (or keep), protect, allow
USERS_MODE="ask"
DO_BACKUP=1
ACTION="install"
ROLLBACK_NAME=""

usage() {
    sed -n '3,28p' "$0" | sed 's/^# \{0,1\}//'
    exit 0
}

while [ $# -gt 0 ]; do
    case "$1" in
        --keep-users)   USERS_MODE="keep"  ;;
        --reset-users)  USERS_MODE="reset" ;;
        --no-backup)    DO_BACKUP=0 ;;
        --port)         PORT_SET=1; PORT_ARG="${2:-}"; [ $# -gt 1 ] && shift ;;
        --mgmt-iface)   MGMT_IFACE_ARG="${2:-}"; [ $# -gt 1 ] && shift
                        [[ "$MGMT_IFACE_ARG" =~ ^[A-Za-z0-9_][A-Za-z0-9._-]{0,14}$ ]] || {
                            echo "error: --mgmt-iface needs an interface name, got '${MGMT_IFACE_ARG}'" >&2; exit 1; } ;;
        --protect-mgmt) MGMT_MODE="protect" ;;
        --allow-mgmt)   MGMT_MODE="allow" ;;
        --list-backups) ACTION="list" ;;
        --rollback)
            ACTION="rollback"
            # Optional argument: a snapshot name, but not the next flag.
            case "${2:-}" in -*|"") ;; *) ROLLBACK_NAME="$2"; shift ;; esac
            ;;
        -h|--help)      usage ;;
        *) echo "unknown option: $1 (try --help)" >&2; exit 1 ;;
    esac
    shift
done

if [ "$PORT_SET" -eq 1 ]; then
    [ "$ACTION" = "install" ] || { echo "error: --port only applies to an install or upgrade" >&2; exit 1; }
    case "$PORT_ARG" in
        ""|*[!0-9]*) echo "error: --port needs a number, got '${PORT_ARG}'" >&2; exit 1 ;;
    esac
    PORT_ARG=$((10#$PORT_ARG))
    if [ "$PORT_ARG" -lt "$PORT_MIN" ] || [ "$PORT_ARG" -gt "$PORT_MAX" ]; then
        echo "error: --port must be between ${PORT_MIN} and ${PORT_MAX}" >&2; exit 1
    fi
fi

[ "$(id -u)" -eq 0 ] || { echo "error: run this as root (sudo bash setup.sh)" >&2; exit 1; }

# ip, tc and bridge live in /usr/sbin. Root's secure_path has it, but `sudo -E`
# hands over the calling user's PATH, which does not — so put them back.
case ":${PATH}:" in *:/usr/sbin:*) ;; *) PATH="${PATH}:/usr/sbin:/sbin" ;; esac
export PATH

[ "${STATE_DIR}" != "${INSTALL_DIR}" ] || {
    echo "error: TC_LAB_STATE_DIR must not be the install directory" >&2; exit 1; }

# ── Service user, state directory, unit ────────────────────────────────────
# Runtime state files. Before v9.3 they lived in the install directory; from
# v9.3 on they live in STATE_DIR. (Plus users.json.*.bak, *.log and profiles/.)
STATE_FILES="users.json users.json.bak secret_key.txt cert.pem key.pem
             state.json network_config.json labels.json config.json"

ensure_service_user() {
    id -u "${SVC_USER}" >/dev/null 2>&1 && return 0
    useradd --system --user-group --no-create-home --home-dir /nonexistent \
            --shell /usr/sbin/nologin "${SVC_USER}"
    echo "[*] Created system user ${SVC_USER}"
}

# The service must own its state; nobody else may read it (password hashes,
# the session-signing key and the TLS private key are in there).
own_state() {
    chown -R "${SVC_USER}:" "${STATE_DIR}"
    chmod -R go-rwx "${STATE_DIR}"
}

write_unit() {
    mkdir -p "${UNIT_DIR}"
    local out="${UNIT_DIR}/${SERVICE}.service"
    sed -e "s|/opt/tc_lab|${INSTALL_DIR}|g" \
        -e "s|/var/lib/tc_lab|${STATE_DIR}|g" \
        -e "s|^User=tc-lab\$|User=${SVC_USER}|" \
        -e "s|^Group=tc-lab\$|Group=$(id -gn "${SVC_USER}" 2>/dev/null || echo "${SVC_USER}")|" \
        "${INSTALL_DIR}/tc_lab.service" > "$out"
    case "${INSTALL_DIR}:${STATE_DIR}" in
        /home/*|/root/*|*:/home/*|*:/root/*)
            # ProtectHome=yes would hide the directory from its own service
            sed -i 's/^ProtectHome=yes/ProtectHome=no/' "$out"
            echo "[!] Install or state is under a home directory — ProtectHome disabled in the unit"
            ;;
    esac
    echo "[*] Service file written to $out"
}

# ── Snapshots / rollback ───────────────────────────────────────────────────
# A snapshot is the install directory minus venv and __pycache__, plus the
# state directory — code AND state, so restoring one returns accounts,
# certificate, topology and saved impairments to exactly what they were. venv
# is excluded because it is large and rebuilt from the restored requirements.txt.
#
# Layout: the code sits at the top of the archive (the layout every version
# reads); the state directory is stored under SNAP_STATE. Snapshots taken
# before v9.3 have no SNAP_STATE — their state is inside the code, where
# those versions kept it.
SNAP_STATE=".tc-lab-state"

snap_list() {
    [ -d "${BACKUP_DIR}" ] || return 0
    find "${BACKUP_DIR}" -maxdepth 1 -name 'tc_lab-*.tgz' -printf '%f\n' 2>/dev/null | sort -r
}

snap_create() {
    mkdir -p "${BACKUP_DIR}"; chmod 700 "${BACKUP_DIR}"
    local name="tc_lab-$(date +%Y%m%d-%H%M%S).tgz"
    # Record the running version so --list-backups is readable.
    local ver
    ver=$(head -1 "${INSTALL_DIR}/app.py" 2>/dev/null | grep -oE 'v[0-9]+(\.[0-9]+)*' | head -1 || true)
    local stage; stage=$(mktemp -d)
    rsync -a --exclude=venv --exclude=__pycache__ "${INSTALL_DIR}/" "$stage/"
    if [ -d "${STATE_DIR}" ]; then
        rsync -a "${STATE_DIR}/" "$stage/${SNAP_STATE}/"
    fi
    tar czf "${BACKUP_DIR}/${name}" -C "$stage" . 2>/dev/null
    rm -rf "$stage"
    chmod 600 "${BACKUP_DIR}/${name}"
    printf '%s\n' "${ver:-unknown}" > "${BACKUP_DIR}/${name}.version"
    echo "[*] Snapshot saved: ${BACKUP_DIR}/${name}  (version ${ver:-unknown})"
    # Prune oldest beyond KEEP_BACKUPS.
    local n=0
    for f in $(snap_list); do
        n=$((n+1))
        if [ "$n" -gt "${KEEP_BACKUPS}" ]; then
            rm -f "${BACKUP_DIR}/${f}" "${BACKUP_DIR}/${f}.version"
            echo "[*] Pruned old snapshot: ${f}"
        fi
    done
}

snap_restore() {
    local name="$1"
    local arch="${BACKUP_DIR}/${name}"
    [ -f "$arch" ] || { echo "error: no such snapshot: ${name}" >&2; exit 1; }

    echo "[*] Rolling back to ${name} ..."
    systemctl stop "${SERVICE}" 2>/dev/null || true

    # Stage first: a corrupt archive must not leave a half-restored install.
    local stage; stage=$(mktemp -d)
    trap 'rm -rf "$stage"' EXIT
    tar xzf "$arch" -C "$stage" || { echo "error: snapshot is unreadable; nothing changed" >&2; exit 1; }
    [ -f "$stage/app.py" ] || { echo "error: snapshot has no app.py; nothing changed" >&2; exit 1; }

    # Mirror the code over the install, leaving venv alone. For a pre-v9.3
    # snapshot this also brings back the state that lived inside the code.
    rsync -a --delete --exclude=venv --exclude=__pycache__ --exclude="/${SNAP_STATE}" \
        "$stage/" "${INSTALL_DIR}/"
    chown -R root:root "${INSTALL_DIR}"; chmod -R go-w "${INSTALL_DIR}"
    chmod +x "${INSTALL_DIR}/restore_network.sh" "${INSTALL_DIR}/restore_helper.py" \
             "${INSTALL_DIR}/tc-lab" "${INSTALL_DIR}/cli.py" 2>/dev/null || true

    # The restored unit says which layout this snapshot is: v9.3+ runs as its
    # own user with state in STATE_DIR; before that, as root with the state
    # inside the code (already restored above).
    if grep -q '^User=' "${INSTALL_DIR}/tc_lab.service" 2>/dev/null; then
        if [ -d "$stage/${SNAP_STATE}" ]; then
            ensure_service_user
            mkdir -p "${STATE_DIR}"
            rsync -a --delete "$stage/${SNAP_STATE}/" "${STATE_DIR}/"
            own_state
        fi
    else
        echo "[*] This snapshot predates v9.3: TC Lab runs as root again, with its"
        echo "    state in ${INSTALL_DIR}. ${STATE_DIR} is not used by it."
    fi
    rm -rf "$stage"; trap - EXIT

    # Dependencies may differ between versions; the unit may too.
    if [ -x "${INSTALL_DIR}/venv/bin/pip" ]; then
        "${INSTALL_DIR}/venv/bin/pip" install --quiet -r "${INSTALL_DIR}/requirements.txt" || true
    fi
    if [ -f "${INSTALL_DIR}/tc_lab.service" ]; then
        write_unit
    fi
    systemctl daemon-reload
    systemctl start "${SERVICE}" || true
    sleep 2
    if systemctl is-active --quiet "${SERVICE}"; then
        echo "[*] Rolled back and running. Hard-refresh the browser (Ctrl-Shift-R)."
    else
        echo "[!] Rolled back, but the service did not start. Check:"
        echo "      journalctl -u ${SERVICE} -n 50"
    fi
}

# ── Moving pre-v9.3 state out of the install directory ─────────────────────
has_legacy_state() {
    local f
    for f in ${STATE_FILES}; do [ -e "${INSTALL_DIR}/${f}" ] && return 0; done
    return 1
}

# Before v9.3 the unit had no User= (it ran as root, state in the install dir).
installed_unit_is_legacy() {
    [ ! -f "$EXISTING_UNIT" ] || ! grep -q '^User=' "$EXISTING_UNIT"
}

# Before v9.3 the service ran as root and kept its state inside the install
# directory. Copy it to STATE_DIR, verify every file, then remove the originals
# (a snapshot of both was taken first). Runs before the code is copied, so
# user-created profiles are still there next to the shipped ones.
migrate_legacy_state() {
    has_legacy_state || return 0
    if ! installed_unit_is_legacy; then
        # e.g. app.py run by hand from the install directory: not the
        # service's state, which is in STATE_DIR. Never let it replace that.
        echo "[!] ${INSTALL_DIR} holds state files the service does not use (its"
        echo "    state is in ${STATE_DIR}). Left as they are; delete them when sure."
        return 0
    fi
    echo "[*] Moving TC Lab's state from ${INSTALL_DIR} to ${STATE_DIR}"
    if [ -d "${STATE_DIR}" ] && [ -n "$(ls -A "${STATE_DIR}" 2>/dev/null)" ]; then
        # Only after rolling back to a pre-v9.3 snapshot and upgrading again:
        # the files in the install directory are the ones that were in use.
        local old="${STATE_DIR}.replaced-$(date +%Y%m%d-%H%M%S)"
        mv "${STATE_DIR}" "$old"; chmod 700 "$old"
        echo "[!] ${STATE_DIR} held older state; moved it to ${old}"
        echo "    (not used any more — delete it once you are happy)"
    fi
    mkdir -p "${STATE_DIR}/profiles"; chmod 700 "${STATE_DIR}"

    local moved=() f
    for f in ${STATE_FILES}; do
        [ -f "${INSTALL_DIR}/${f}" ] && moved+=("$f")
    done
    for f in "${INSTALL_DIR}"/users.json.*.bak "${INSTALL_DIR}"/*.log; do
        [ -f "$f" ] && moved+=("$(basename "$f")")
    done
    for f in "${moved[@]}"; do
        cp -p "${INSTALL_DIR}/${f}" "${STATE_DIR}/${f}"
    done
    for f in "${INSTALL_DIR}"/profiles/*.json; do
        [ -f "$f" ] && cp -p "$f" "${STATE_DIR}/profiles/"
    done
    for f in "${moved[@]}"; do
        cmp -s "${INSTALL_DIR}/${f}" "${STATE_DIR}/${f}" || {
            echo "error: copy of ${f} did not verify; nothing removed from ${INSTALL_DIR}" >&2
            exit 1; }
    done
    for f in "${moved[@]}"; do rm -f "${INSTALL_DIR}/${f}"; done
    echo "[*] Moved ${#moved[@]} file(s) and the profiles to ${STATE_DIR}"
}

if [ "$ACTION" = "list" ]; then
    found=0
    for f in $(snap_list); do
        found=1
        v=$(cat "${BACKUP_DIR}/${f}.version" 2>/dev/null || echo "unknown")
        printf '  %-34s  version %-8s  %s\n' "$f" "$v" \
               "$(du -h "${BACKUP_DIR}/${f}" | cut -f1)"
    done
    [ "$found" -eq 1 ] || echo "  (no snapshots in ${BACKUP_DIR})"
    exit 0
fi

if [ "$ACTION" = "rollback" ]; then
    if [ -z "$ROLLBACK_NAME" ]; then
        ROLLBACK_NAME=$(snap_list | head -1)
        [ -n "$ROLLBACK_NAME" ] || { echo "error: no snapshots in ${BACKUP_DIR}" >&2; exit 1; }
        echo "[*] Most recent snapshot: ${ROLLBACK_NAME}"
    fi
    snap_restore "$ROLLBACK_NAME"
    exit 0
fi


USERS_FILE="${STATE_DIR}/users.json"
# The store that is in use right now. A pre-v9.3 install keeps it in the
# install directory; if one is there it is the current one (see
# migrate_legacy_state), otherwise it is in STATE_DIR.
CUR_USERS="${USERS_FILE}"
if [ -f "${INSTALL_DIR}/users.json" ] && installed_unit_is_legacy; then
    CUR_USERS="${INSTALL_DIR}/users.json"
fi
IS_UPGRADE=0
[ -f "${INSTALL_DIR}/app.py" ] && IS_UPGRADE=1

# The port the install uses now (config.json in either layout; 5000 if none).
current_port() {
    local f
    for f in "${INSTALL_DIR}/config.json" "${STATE_DIR}/config.json"; do
        [ -f "$f" ] && { grep -oP '"port"\s*:\s*\K[0-9]+' "$f" 2>/dev/null && return 0; }
    done
    echo 5000
}
if [ "$PORT_SET" -eq 1 ] && [ "$PORT_ARG" != "$(current_port | head -1)" ] \
   && command -v ss >/dev/null 2>&1 \
   && [ -n "$(ss -Hltn "sport = :${PORT_ARG}" 2>/dev/null)" ]; then
    echo "error: something is already listening on port ${PORT_ARG}; nothing was changed" >&2
    exit 1
fi

if [ "$IS_UPGRADE" -eq 1 ]; then
    echo "[*] Existing install detected at ${INSTALL_DIR} — upgrading."
else
    echo "[*] Installing TC Lab to ${INSTALL_DIR} ..."
fi

# ── 0. Decide what to do with existing accounts — asked up front, before any
#       long-running step, so nothing blocks half way through the install ─────
if [ -f "$CUR_USERS" ]; then
    ACCOUNTS=$(grep -c '"hash"' "$CUR_USERS" 2>/dev/null || true)
    ACCOUNTS=${ACCOUNTS:-0}
    if [ "$USERS_MODE" = "ask" ]; then
        if [ -r /dev/tty ]; then
            echo ""
            echo "  Found an existing account store with ${ACCOUNTS} account(s):"
            echo "    ${CUR_USERS}"
            echo ""
            echo "    [K] Keep them   — everyone signs in with their current password (default)"
            echo "    [R] Reset them  — delete all accounts; a fresh admin/tclab123 is created"
            echo ""
            printf "  Keep existing accounts? [K/r] "
            read -r reply < /dev/tty || reply=""
            case "${reply}" in
                [Rr]*) USERS_MODE="reset" ;;
                *)     USERS_MODE="keep"  ;;
            esac
            echo ""
        else
            # Non-interactive (piped, CI, unattended): never destroy accounts
            # silently. Use --reset-users if that is genuinely what you want.
            USERS_MODE="keep"
            echo "[!] Not running interactively — keeping the ${ACCOUNTS} existing account(s)."
            echo "[!] Use --reset-users to wipe them instead."
        fi
    fi
else
    USERS_MODE="fresh"     # nothing to keep; first start creates admin/tclab123
fi

# ── 0b. The management interface — also asked up front ─────────────────────
# The interface this host is managed through (the dashboard, SSH). Protected,
# TC Lab refuses VLANs on it, bridge membership and bringing it down; either
# way nothing involving it is kept after a reboot (see mgmt_guard.py). Asked
# once: when the config does not name one yet, or when a flag says so.
detect_mgmt() {
    # The interface this admin's SSH session arrives on; else the default route's.
    local ip="${SSH_CONNECTION:-}" dev=""      # unset when run from a console
    ip="${ip%% *}"
    [ -n "$ip" ] || ip=$(who -m 2>/dev/null | grep -oP '\(\K[0-9a-fA-F.:]+(?=\))' | head -1 || true)
    [ -n "$ip" ] && dev=$(ip route get "$ip" 2>/dev/null | grep -oP ' dev \K\S+' | head -1 || true)
    if [ -z "$dev" ] || [ "$dev" = "lo" ]; then
        dev=$(ip route show default 2>/dev/null | grep -oP ' dev \K\S+' | head -1 || true)
    fi
    echo "$dev"
}
config_mgmt() {
    local f
    for f in "${INSTALL_DIR}/config.json" "${STATE_DIR}/config.json"; do
        [ -f "$f" ] || continue
        python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("management_interface") or "")' \
            "$f" 2>/dev/null && return 0
    done
}
MGMT_SET=""; MGMT_LOCK=""
EXISTING_MGMT=$(config_mgmt | head -1 || true)
if [ -n "$MGMT_IFACE_ARG" ] || [ -n "$MGMT_MODE" ] || [ -z "$EXISTING_MGMT" ]; then
    MGMT_SET="${MGMT_IFACE_ARG:-${EXISTING_MGMT:-$(detect_mgmt)}}"
    if [ -z "$MGMT_SET" ]; then
        echo "[!] Could not detect the management interface — choose it later in"
        echo "    Settings → Management Interface."
    elif [ -z "$MGMT_MODE" ]; then
        MGMT_MODE="protect"             # the default, and the answer when nobody is there
        if [ -r /dev/tty ]; then
            echo ""
            echo "  Management interface: ${MGMT_SET}  (the one this host is reached through)"
            echo ""
            echo "    Protect it (recommended): TC Lab will not use it for VLANs or bridges,"
            echo "    or bring it down — any of those can cut off your access to this host."
            echo "    Either way, nothing involving it is kept after a reboot."
            echo ""
            printf "  Protect %s? [Y/n] " "${MGMT_SET}"
            read -r reply < /dev/tty || reply=""
            case "${reply}" in [Nn]*) MGMT_MODE="allow" ;; esac
            echo ""
        fi
    fi
    [ -n "$MGMT_SET" ] && { [ "$MGMT_MODE" = "allow" ] && MGMT_LOCK=false || MGMT_LOCK=true; }
fi

# ── 1. System dependencies ─────────────────────────────────────────────────
# Debian/Ubuntu only. The app itself is distribution-agnostic, but this
# installer is not and does not pretend to be.
if ! command -v apt-get >/dev/null 2>&1; then
    echo "error: this installer requires apt (Debian / Ubuntu)." >&2
    echo "       See docs/deployment.md for running TC Lab elsewhere." >&2
    exit 1
fi
apt-get update -qq
apt-get install -y python3 python3-pip python3-venv iproute2 bridge-utils rsync

# ── 2. Copy the application ────────────────────────────────────────────────
# Snapshot before anything is written, so a bad upgrade is one command to undo.
if [ "$IS_UPGRADE" -eq 1 ] && [ "$DO_BACKUP" -eq 1 ]; then
    snap_create
elif [ "$IS_UPGRADE" -eq 1 ]; then
    echo "[!] --no-backup: no snapshot taken, rollback will not be possible"
fi

ensure_service_user
migrate_legacy_state

# Runtime state is excluded so that a checkout the app has been run from (see
# the "run it manually" option in docs/deployment.md) never copies its own
# accounts, certificate or topology into the install.
#
# --delete removes files that are no longer shipped (an upgrade used to leave
# them behind forever) — including user profiles from before v9.3, which
# migrate_legacy_state has already copied to STATE_DIR.
mkdir -p "${INSTALL_DIR}"
rsync -a --delete \
    --exclude=venv --exclude=__pycache__ --exclude='*.pyc' \
    --exclude=.git --exclude=.pytest_cache --exclude=_preview.html \
    --exclude=users.json --exclude=users.json.bak --exclude=secret_key.txt \
    --exclude=cert.pem --exclude=key.pem \
    --exclude=state.json --exclude=network_config.json --exclude=labels.json \
    --exclude='*.log' --exclude=state \
    --exclude=config.json \
    "${SRC_DIR}/" "${INSTALL_DIR}/"

mkdir -p "${STATE_DIR}/profiles"

# Shipped profiles are added to the state directory when missing. One that is
# already there is never overwritten, so edits survive upgrades (a deleted one
# comes back, as it always has).
for f in "${INSTALL_DIR}"/profiles/*.json; do
    [ -f "$f" ] || continue
    [ -e "${STATE_DIR}/profiles/$(basename "$f")" ] || cp "$f" "${STATE_DIR}/profiles/"
done

# config.json holds operator settings (bind_address, port, idle timeout), so it
# is written only when absent — an upgrade must not reset it. Generated here
# rather than copied, so the installer does not depend on a file that a
# checkout may legitimately not have.
if [ ! -f "${STATE_DIR}/config.json" ]; then
    cat > "${STATE_DIR}/config.json" <<'JSON'
{
  "idle_timeout_minutes": 30,
  "bind_address": "0.0.0.0",
  "port": 5000
}
JSON
    echo "[*] Default config.json written (edit bind_address to restrict the UI)"
else
    echo "[*] Keeping existing config.json"
fi
if [ "$PORT_SET" -eq 1 ]; then
    if python3 - "${STATE_DIR}/config.json" "$PORT_ARG" <<'PY'
import json, sys
path, port = sys.argv[1], int(sys.argv[2])
with open(path) as f:
    cfg = json.load(f)
cfg["port"] = port
with open(path, "w") as f:
    json.dump(cfg, f, indent=2)
PY
    then
        echo "[*] Dashboard port set to ${PORT_ARG}"
    else
        echo "[!] Could not update the port in ${STATE_DIR}/config.json — it is not"
        echo "    valid JSON. Fix the file, then: sudo tc-lab set-port ${PORT_ARG}"
    fi
fi
if [ -n "$MGMT_SET" ]; then
    python3 - "${STATE_DIR}/config.json" "$MGMT_SET" "$MGMT_LOCK" <<'PY' \
      && echo "[*] Management interface: ${MGMT_SET} ($([ "$MGMT_LOCK" = true ] && echo protected || echo 'NOT protected'))" \
      || echo "[!] Could not record the management interface in config.json"
import json, sys
path, iface, lock = sys.argv[1], sys.argv[2], sys.argv[3] == "true"
with open(path) as f:
    cfg = json.load(f)
cfg["management_interface"], cfg["protect_management"] = iface, lock
with open(path, "w") as f:
    json.dump(cfg, f, indent=2)
PY
fi
CFG_PORT=$(grep -oP '"port"\s*:\s*\K[0-9]+' "${STATE_DIR}/config.json" 2>/dev/null || echo 5000)
if [ "$CFG_PORT" -lt "$PORT_MIN" ]; then
    echo "[!] config.json sets port ${CFG_PORT}. TC Lab no longer runs as root, so it"
    echo "    cannot listen below ${PORT_MIN}; it will use 5000 instead. Choose another"
    echo "    port with: sudo bash setup.sh --port <port>  (or sudo tc-lab set-port <port>)"
fi

# ── 3. Virtualenv ──────────────────────────────────────────────────────────
[ -d "${INSTALL_DIR}/venv" ] || python3 -m venv "${INSTALL_DIR}/venv"
"${INSTALL_DIR}/venv/bin/pip" install --quiet --upgrade pip
"${INSTALL_DIR}/venv/bin/pip" install --quiet -r "${INSTALL_DIR}/requirements.txt"

# ── 4. TLS certificate (kept if one already exists) ────────────────────────
if [ ! -f "${STATE_DIR}/cert.pem" ]; then
    echo "[*] Generating self-signed TLS cert..."
    (cd "${INSTALL_DIR}" && TC_LAB_STATE_DIR="${STATE_DIR}" venv/bin/python ssl_gen.py)
else
    echo "[*] Keeping existing TLS certificate"
fi

# ── 5. Apply the account decision from step 0 ──────────────────────────────
case "$USERS_MODE" in
    keep)
        echo "[*] Keeping ${ACCOUNTS} existing account(s) — passwords unchanged"
        chmod 600 "$USERS_FILE" 2>/dev/null || true
        ;;
    reset)
        BACKUP="${USERS_FILE}.$(date +%Y%m%d-%H%M%S).bak"
        cp -a "$USERS_FILE" "$BACKUP" && chmod 600 "$BACKUP"
        rm -f "$USERS_FILE"
        echo "[*] Accounts reset. Previous store backed up to:"
        echo "    ${BACKUP}"
        echo "    A fresh admin/tclab123 will be created on first start."
        ;;
    fresh)
        echo "[*] No existing accounts — admin/tclab123 will be created on first start"
        ;;
esac

# Stale bytecode: __pycache__ is excluded from the transfer (so rsync will not
# delete it either), and a leftover .pyc for a module that no longer exists can
# still be imported. Clear it outright.
find "${INSTALL_DIR}" -name __pycache__ -type d -prune -exec rm -rf {} + 2>/dev/null || true

# ── 6. Ownership ───────────────────────────────────────────────────────────
# Code: root's, and not writable by the service or anyone else. rsync -a
# (-rlptgoD) preserves the checkout's owner when it runs as root, so a normal
# "git clone && sudo bash setup.sh" would otherwise leave the service's code
# owned and writable by the user who cloned it. Take ownership explicitly and
# drop group/other write.
chown -R root:root "${INSTALL_DIR}"
chmod -R go-w "${INSTALL_DIR}"
# State: the service's own, private to it.
own_state

# ── 7. Executable bits + CLI ───────────────────────────────────────────────
chmod +x "${INSTALL_DIR}/restore_network.sh" "${INSTALL_DIR}/restore_helper.py"
chmod +x "${INSTALL_DIR}/tc-lab" "${INSTALL_DIR}/cli.py"
mkdir -p "${BIN_DIR}"
ln -sf "${INSTALL_DIR}/tc-lab" "${BIN_DIR}/tc-lab"
echo "[*] CLI installed: sudo tc-lab reset-admin-password"

# ── 8. systemd unit ────────────────────────────────────────────────────────
# Installed from the tracked tc_lab.service so the sandboxing options and the
# ExecStartPre topology restore stay in one place (an earlier version of this
# script wrote a stripped-down unit inline and silently dropped both).
write_unit

# ── 9. Enable and start ────────────────────────────────────────────────────
systemctl daemon-reload
systemctl enable "${SERVICE}" >/dev/null 2>&1
systemctl restart "${SERVICE}"
sleep 2

IP=$(hostname -I | awk '{print $1}')
PORT="$CFG_PORT"; [ "$PORT" -ge "$PORT_MIN" ] || PORT=5000
echo ""
echo "============================================================"
if systemctl is-active --quiet "${SERVICE}"; then
    echo " TC Lab is running."
else
    echo " WARNING: the service did not start. Check:"
    echo "   journalctl -u ${SERVICE} -n 50"
fi
echo " Installed to:  ${INSTALL_DIR}"
echo " State:         ${STATE_DIR}  (runs as user ${SVC_USER})"
echo " Service:       systemctl status ${SERVICE}"
echo " Open:          https://${IP}:${PORT}"
if [ "$USERS_MODE" = "keep" ]; then
    echo " Login:         your existing accounts (passwords unchanged)"
else
    echo " Login:         admin / tclab123   (change it after signing in)"
fi
echo " Lost the admin password?   sudo tc-lab reset-admin-password"
if [ "$IS_UPGRADE" -eq 1 ] && [ "$DO_BACKUP" -eq 1 ]; then
    echo " Undo this upgrade:         sudo bash setup.sh --rollback"
fi
echo "============================================================"
echo ""
if [ "$IS_UPGRADE" -eq 1 ]; then
    echo "Upgraded — hard-refresh your browser (Ctrl-Shift-R) so the page picks"
    echo "up a fresh CSRF token, otherwise every action returns a token error."
    echo ""
fi
echo "To trust the cert in Chrome: chrome://settings/certificates"
echo "  Authorities -> Import ${STATE_DIR}/cert.pem -> Trust for HTTPS"
