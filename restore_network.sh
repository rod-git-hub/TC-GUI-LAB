#!/bin/bash
# restore_network.sh — re-creates VLANs, bridges, bridge members from
# network_config.json. Called by systemd ExecStartPre and by app.py on import.
# Order: VLANs first → bridges → members
# TC rules are re-applied by app.py _init() AFTER this script completes.

INSTALL_DIR="/opt/tc_lab"
CONF="${INSTALL_DIR}/network_config.json"
LOG="${INSTALL_DIR}/restore_network.log"

log(){ echo "$(date '+%Y-%m-%d %H:%M:%S') $*" | tee -a "$LOG"; }

log "=== restore_network.sh START ==="

if [ ! -f "$CONF" ]; then
  log "No network_config.json at $CONF — nothing to restore."
  exit 0
fi

log "Config found: $CONF"
modprobe 8021q 2>/dev/null && log "8021q loaded" || log "8021q: already loaded"

python3 /opt/tc_lab/restore_helper.py 2>&1 | tee -a "$LOG"

log "=== restore_network.sh END ==="
