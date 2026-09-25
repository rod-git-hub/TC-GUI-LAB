#!/bin/bash
# restore_network.sh — re-creates VLANs, bridges, bridge members from
# network_config.json. Called by systemd ExecStartPre and by app.py on import.
# Order: VLANs first → bridges → members
# TC rules are re-applied by app.py _init() AFTER this script completes.

SCRIPT_DIR="$(cd "$(dirname "$(realpath "$0")")" && pwd)"
# State (network_config.json, logs) lives under TC_LAB_STATE_DIR when set;
# otherwise next to this script (the normal systemd install).
STATE_DIR="${TC_LAB_STATE_DIR:-$SCRIPT_DIR}"
export TC_LAB_STATE_DIR="$STATE_DIR"
CONF="${STATE_DIR}/network_config.json"
LOG="${STATE_DIR}/restore_network.log"

mkdir -p "$STATE_DIR" 2>/dev/null || true
log(){ echo "$(date '+%Y-%m-%d %H:%M:%S') $*" | tee -a "$LOG"; }

log "=== restore_network.sh START (state=$STATE_DIR) ==="

if [ ! -f "$CONF" ]; then
  log "No network_config.json at $CONF — nothing to restore."
  exit 0
fi

log "Config found: $CONF"
modprobe 8021q 2>/dev/null && log "8021q loaded" || log "8021q: already loaded or unavailable"

python3 "${SCRIPT_DIR}/restore_helper.py" 2>&1 | tee -a "$LOG"

log "=== restore_network.sh END ==="
