#!/usr/bin/env bash
set -euo pipefail

INSTALL_DIR="/opt/tc_lab"
SERVICE="tc_lab"

echo "[*] Installing TC Lab to ${INSTALL_DIR} ..."

# 1. System deps (including rsync)
apt-get update -qq
apt-get install -y python3 python3-pip python3-venv iproute2 bridge-utils rsync

# 2. Copy files
mkdir -p "${INSTALL_DIR}"
rsync -a --exclude=venv --exclude=__pycache__ --exclude='*.pyc' \
    "$(dirname "$(realpath "$0")")/" "${INSTALL_DIR}/"

# 3. Virtualenv
python3 -m venv "${INSTALL_DIR}/venv"
"${INSTALL_DIR}/venv/bin/pip" install --quiet flask flask-login bcrypt cryptography

# 4. Generate TLS cert if missing
if [ ! -f "${INSTALL_DIR}/cert.pem" ]; then
    echo "[*] Generating self-signed TLS cert..."
    cd "${INSTALL_DIR}" && venv/bin/python ssl_gen.py
fi

# 5. Drop users.json so default admin/tclab123 is created on first start
rm -f "${INSTALL_DIR}/users.json"

# 6. Make restore scripts executable
chmod +x "${INSTALL_DIR}/restore_network.sh"
chmod +x "${INSTALL_DIR}/restore_helper.py"

# 7. Install systemd service directly (no heredoc variable expansion issues)
SERVICE_FILE="/etc/systemd/system/${SERVICE}.service"
echo "[Unit]"                                                      >  "${SERVICE_FILE}"
echo "Description=TC Lab WAN Emulator"                            >> "${SERVICE_FILE}"
echo "After=network.target"                                        >> "${SERVICE_FILE}"
echo ""                                                            >> "${SERVICE_FILE}"
echo "[Service]"                                                   >> "${SERVICE_FILE}"
echo "Type=simple"                                                 >> "${SERVICE_FILE}"
echo "WorkingDirectory=${INSTALL_DIR}"                             >> "${SERVICE_FILE}"
echo "ExecStart=${INSTALL_DIR}/venv/bin/python ${INSTALL_DIR}/app.py" >> "${SERVICE_FILE}"
echo "Restart=on-failure"                                          >> "${SERVICE_FILE}"
echo "RestartSec=5"                                                >> "${SERVICE_FILE}"
echo ""                                                            >> "${SERVICE_FILE}"
echo "[Install]"                                                   >> "${SERVICE_FILE}"
echo "WantedBy=multi-user.target"                                  >> "${SERVICE_FILE}"

echo "[*] Service file written to ${SERVICE_FILE}"
cat "${SERVICE_FILE}"

# 8. Enable and start
systemctl daemon-reload
systemctl enable "${SERVICE}"
systemctl restart "${SERVICE}"

IP=$(hostname -I | awk '{print $1}')
echo ""
echo "============================================================"
echo " TC Lab installed to: ${INSTALL_DIR}"
echo " Service:             systemctl status ${SERVICE}"
echo " Open:                https://${IP}:5000"
echo " Login:               admin / tclab123  (change after login)"
echo "============================================================"
echo ""
echo "To trust cert in Chrome: chrome://settings/certificates"
echo "  Authorities -> Import ${INSTALL_DIR}/cert.pem -> Trust for HTTPS"
