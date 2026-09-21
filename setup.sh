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
#   sudo bash setup.sh --list-backups   # show snapshots available to roll back to
#   sudo bash setup.sh --rollback       # restore the most recent snapshot
#   sudo bash setup.sh --rollback NAME  # restore a specific one (see --list-backups)
#   sudo bash setup.sh --help
#
# Every upgrade snapshots the whole install first (code AND state: accounts,
# certificate, topology, saved impairments) to TC_LAB_BACKUP_DIR, default
# /var/backups/tc-lab. The five most recent are kept.
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
# Where the tc-lab CLI symlink goes. Override for packaging or scratch installs.
BIN_DIR="${TC_LAB_BIN_DIR:-/usr/local/bin}"
KEEP_BACKUPS="${TC_LAB_KEEP_BACKUPS:-5}"
SRC_DIR="$(dirname "$(realpath "$0")")"
USERS_MODE="ask"
DO_BACKUP=1
ACTION="install"
ROLLBACK_NAME=""

usage() {
    sed -n '3,20p' "$0" | sed 's/^# \{0,1\}//'
    exit 0
}

while [ $# -gt 0 ]; do
    case "$1" in
        --keep-users)   USERS_MODE="keep"  ;;
        --reset-users)  USERS_MODE="reset" ;;
        --no-backup)    DO_BACKUP=0 ;;
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

[ "$(id -u)" -eq 0 ] || { echo "error: run this as root (sudo bash setup.sh)" >&2; exit 1; }

# ── Snapshots / rollback ───────────────────────────────────────────────────
# A snapshot is the whole install directory minus venv and __pycache__ — code
# AND state, so restoring one returns accounts, certificate, topology and saved
# impairments to exactly what they were. venv is excluded because it is large
# and rebuilt from the restored requirements.txt.

snap_list() {
    [ -d "${BACKUP_DIR}" ] || return 0
    find "${BACKUP_DIR}" -maxdepth 1 -name 'tc_lab-*.tgz' -printf '%f\n' 2>/dev/null | sort -r
}

snap_create() {
    mkdir -p "${BACKUP_DIR}"; chmod 700 "${BACKUP_DIR}"
    local name="tc_lab-$(date +%Y%m%d-%H%M%S).tgz"
    # Record the running version so --list-backups is readable.
    local ver
    ver=$(head -1 "${INSTALL_DIR}/app.py" 2>/dev/null | tr -cd 'v0-9.' || true)
    tar czf "${BACKUP_DIR}/${name}" -C "${INSTALL_DIR}" \
        --exclude=venv --exclude=__pycache__ . 2>/dev/null
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

    # Mirror the snapshot over the install, leaving venv alone.
    rsync -a --delete --exclude=venv --exclude=__pycache__ "$stage/" "${INSTALL_DIR}/"
    rm -rf "$stage"; trap - EXIT

    chown -R root:root "${INSTALL_DIR}"; chmod -R go-w "${INSTALL_DIR}"
    chmod +x "${INSTALL_DIR}/restore_network.sh" "${INSTALL_DIR}/restore_helper.py" \
             "${INSTALL_DIR}/tc-lab" "${INSTALL_DIR}/cli.py" 2>/dev/null || true

    # Dependencies may differ between versions; the unit may too.
    if [ -x "${INSTALL_DIR}/venv/bin/pip" ]; then
        "${INSTALL_DIR}/venv/bin/pip" install --quiet -r "${INSTALL_DIR}/requirements.txt" || true
    fi
    if [ -f "${INSTALL_DIR}/tc_lab.service" ]; then
        mkdir -p "${UNIT_DIR}"
        sed "s|/opt/tc_lab|${INSTALL_DIR}|g" "${INSTALL_DIR}/tc_lab.service" > "${UNIT_DIR}/${SERVICE}.service"
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


USERS_FILE="${INSTALL_DIR}/users.json"
IS_UPGRADE=0
[ -f "${INSTALL_DIR}/app.py" ] && IS_UPGRADE=1

if [ "$IS_UPGRADE" -eq 1 ]; then
    echo "[*] Existing install detected at ${INSTALL_DIR} — upgrading."
else
    echo "[*] Installing TC Lab to ${INSTALL_DIR} ..."
fi

# ── 0. Decide what to do with existing accounts — asked up front, before any
#       long-running step, so nothing blocks half way through the install ─────
if [ -f "$USERS_FILE" ]; then
    ACCOUNTS=$(grep -c '"hash"' "$USERS_FILE" 2>/dev/null || true)
    ACCOUNTS=${ACCOUNTS:-0}
    if [ "$USERS_MODE" = "ask" ]; then
        if [ -r /dev/tty ]; then
            echo ""
            echo "  Found an existing account store with ${ACCOUNTS} account(s):"
            echo "    ${USERS_FILE}"
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

# ── 1. System dependencies ─────────────────────────────────────────────────
apt-get update -qq
apt-get install -y python3 python3-pip python3-venv iproute2 bridge-utils rsync

# ── 2. Copy the application ────────────────────────────────────────────────
# Snapshot before anything is written, so a bad upgrade is one command to undo.
if [ "$IS_UPGRADE" -eq 1 ] && [ "$DO_BACKUP" -eq 1 ]; then
    snap_create
elif [ "$IS_UPGRADE" -eq 1 ]; then
    echo "[!] --no-backup: no snapshot taken, rollback will not be possible"
fi

# Runtime state is excluded so that running the app from a checkout (see the
# "run it manually" option in docs/deployment.md) can never overwrite the
# installed instance's accounts, certificate or saved topology.
#
# --delete removes files that are no longer shipped (an upgrade used to leave
# them behind forever). rsync protects --exclude'd paths on the receiver, so
# every state file above survives; profiles/ is protected explicitly because it
# holds user-created presets alongside the shipped ones and cannot be told apart.
mkdir -p "${INSTALL_DIR}"
rsync -a --delete \
    --filter='protect profiles/***' \
    --exclude=venv --exclude=__pycache__ --exclude='*.pyc' \
    --exclude=.git --exclude=.pytest_cache --exclude=_preview.html \
    --exclude=users.json --exclude=users.json.bak --exclude=secret_key.txt \
    --exclude=cert.pem --exclude=key.pem \
    --exclude=state.json --exclude=network_config.json --exclude=labels.json \
    --exclude='*.log' --exclude=state \
    --exclude=config.json \
    "${SRC_DIR}/" "${INSTALL_DIR}/"

# config.json holds operator settings (bind_address, port, idle timeout), so it
# is written only when absent — an upgrade must not reset it. Generated here
# rather than copied, so the installer does not depend on a file that a
# checkout may legitimately not have.
if [ ! -f "${INSTALL_DIR}/config.json" ]; then
    cat > "${INSTALL_DIR}/config.json" <<'JSON'
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

# ── 3. Virtualenv ──────────────────────────────────────────────────────────
[ -d "${INSTALL_DIR}/venv" ] || python3 -m venv "${INSTALL_DIR}/venv"
"${INSTALL_DIR}/venv/bin/pip" install --quiet --upgrade pip
"${INSTALL_DIR}/venv/bin/pip" install --quiet -r "${INSTALL_DIR}/requirements.txt"

# ── 4. TLS certificate (kept if one already exists) ────────────────────────
if [ ! -f "${INSTALL_DIR}/cert.pem" ]; then
    echo "[*] Generating self-signed TLS cert..."
    (cd "${INSTALL_DIR}" && venv/bin/python ssl_gen.py)
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
# The unit has no User=, so the app runs as root. rsync -a (-rlptgoD) preserves
# the checkout's owner when it runs as root, so a normal "git clone && sudo bash
# setup.sh" would otherwise leave root-executed code owned and writable by the
# unprivileged user who cloned it — a local privilege-escalation path. Take
# ownership explicitly and drop group/other write.
chown -R root:root "${INSTALL_DIR}"
chmod -R go-w "${INSTALL_DIR}"

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
mkdir -p "${UNIT_DIR}"
SERVICE_FILE="${UNIT_DIR}/${SERVICE}.service"
sed "s|/opt/tc_lab|${INSTALL_DIR}|g" "${INSTALL_DIR}/tc_lab.service" > "${SERVICE_FILE}"
case "${INSTALL_DIR}" in
    /home/*|/root/*)
        # ProtectHome=yes would hide the install directory from its own service
        sed -i 's/^ProtectHome=yes/ProtectHome=no/' "${SERVICE_FILE}"
        echo "[!] Install is under a home directory — ProtectHome disabled in the unit"
        ;;
esac
echo "[*] Service file written to ${SERVICE_FILE}"

# ── 9. Enable and start ────────────────────────────────────────────────────
systemctl daemon-reload
systemctl enable "${SERVICE}" >/dev/null 2>&1
systemctl restart "${SERVICE}"
sleep 2

IP=$(hostname -I | awk '{print $1}')
PORT=$(grep -oP '"port"\s*:\s*\K[0-9]+' "${INSTALL_DIR}/config.json" 2>/dev/null || echo 5000)
echo ""
echo "============================================================"
if systemctl is-active --quiet "${SERVICE}"; then
    echo " TC Lab is running."
else
    echo " WARNING: the service did not start. Check:"
    echo "   journalctl -u ${SERVICE} -n 50"
fi
echo " Installed to:  ${INSTALL_DIR}"
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
echo "  Authorities -> Import ${INSTALL_DIR}/cert.pem -> Trust for HTTPS"
