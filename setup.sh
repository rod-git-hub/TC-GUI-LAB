#!/usr/bin/env bash
set -euo pipefail
apt-get update -qq
apt-get install -y python3 python3-pip python3-venv iproute2 bridge-utils
python3 -m venv venv && source venv/bin/activate
pip install --quiet flask flask-login bcrypt cryptography
echo "[+] Done. Run: sudo venv/bin/python app.py"
echo "    Open: https://<ip>:5000"
echo "    Login: admin / tclab123"
echo ""
echo "To trust the cert in Chrome (skip warning permanently):"
echo "  chrome://settings/certificates -> Authorities -> Import cert.pem -> Trust for HTTPS"
