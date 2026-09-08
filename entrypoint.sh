#!/bin/bash
# Container entrypoint — mirrors tc_lab.service (ExecStartPre + ExecStart).
set -e

STATE_DIR="${TC_LAB_STATE_DIR:-/opt/tc_lab/state}"
mkdir -p "$STATE_DIR/profiles"

# Seed default impairment profiles on first run (empty volume).
if [ -d /opt/tc_lab/profiles.default ] && [ -z "$(ls -A "$STATE_DIR/profiles" 2>/dev/null)" ]; then
    cp /opt/tc_lab/profiles.default/*.json "$STATE_DIR/profiles/" 2>/dev/null || true
    echo "[entrypoint] seeded default profiles into $STATE_DIR/profiles"
fi

# Recreate saved VLAN / bridge / member topology before the app re-applies tc.
bash /opt/tc_lab/restore_network.sh || true

exec python /opt/tc_lab/app.py
