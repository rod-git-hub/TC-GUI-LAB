# TC-GUI-LAB
# TC Lab v8 — WAN Emulator for SD-WAN / Network Labs

A browser-based tool to apply real Linux traffic control (tc/netem) impairments
to network interfaces. Built for Fortinet SD-WAN, SASE, and general network
lab testing.

---

## What It Does

- Apply latency, jitter, packet loss, duplication, corruption, and rate limiting
  to any interface in real time
- Group interfaces under bridges and control them together
- Manage 802.1Q VLAN sub-interfaces
- Save and load impairment profiles (satellite, LTE, MPLS, etc.)
- HTTPS with auto-generated self-signed TLS certificate
- Light / Dark theme
- Idle session timeout (configurable)
- Multi-user with role-based access (admin / user)

---

## Requirements

- Linux host (Debian, Ubuntu, or similar)
- Python 3.9+
- Root privileges (required for tc, ip, and bridge commands)
- Network interfaces to emulate (physical NICs, bridges, or VLANs)
- Port 5000 reachable from your browser

Tested on: Debian 12, Ubuntu 22.04 / 24.04

---

## Installation

### 1. Clone or extract the files

    unzip tc_lab_v8.zip
    cd tc_lab

### 2. Run the setup script (installs dependencies)

    sudo bash setup.sh

This installs: python3, python3-venv, iproute2, bridge-utils, and Python
packages: flask, flask-login, bcrypt, cryptography.

### 3. Start the application

    sudo venv/bin/python app.py

On first run it will:
  - Create the default admin account (admin / tclab123)
  - Generate a self-signed TLS certificate (cert.pem + key.pem)
  - Start HTTPS on port 5000

### 4. Open in your browser

    https://<server-ip>:5000

Chrome will show a security warning for the self-signed certificate.
Click "Advanced" -> "Proceed to <ip> (unsafe)" to continue.

To permanently trust the cert and skip the warning:
  chrome://settings/certificates -> Authorities -> Import cert.pem
  Check "Trust this certificate for identifying websites"

---

## First Login

    Username: admin
    Password: tclab123

IMPORTANT: Change your password immediately after first login.
Settings -> Change Password

---

## Running as a Systemd Service (optional)

    sudo cp tc_lab.service /etc/systemd/system/
    sudo systemctl daemon-reload
    sudo systemctl enable --now tc_lab
    sudo systemctl status tc_lab

The service file assumes the app is installed at /opt/tc_lab.
Copy the files there first:

    sudo cp -r . /opt/tc_lab

---

## Quick Bridge Setup (for WAN emulation between two firewalls)

If you want to insert this Linux box between a firewall and a WAN link:

    sudo bash bridge_setup.sh br0 eth0 eth1

This creates a transparent Layer 2 bridge: Firewall <-> eth0 [br0] eth1 <-> WAN

Then in TC Lab, apply impairments to br0 and they affect all traffic
passing through.

---

## Applying TC Impairments

1. Open the TC Emulation tab
2. Find the interface or bridge you want to impair
3. Set values (0 = disabled for all fields):
   - Latency (ms)    : one-way added delay
   - Jitter (ms)     : random variation on top of latency
   - Loss (%)        : random packet drop rate
   - Duplicate (%)   : probability of packet duplication
   - Corrupt (%)     : probability of single-bit corruption
   - Rate mbit       : bandwidth cap (0 = unlimited)
4. Click Apply
5. Click Reset to remove all impairments

For bridges: applying to the bridge card splits values across all member
interfaces. Use "Member controls" to fine-tune individual interfaces.

---

## Profiles

Pre-built profiles are included in the profiles/ folder:

  good_link        : Baseline clean link
  mpls_good        : Low-latency MPLS (10ms, 100mbit)
  broadband        : Typical broadband (20ms, 50mbit, 0.1% loss)
  high_latency_wan : Slow WAN (150ms, 20ms jitter, 0.5% loss, 10mbit)
  lte_congested    : Congested LTE (80ms, 30ms jitter, 1.5% loss, 2mbit)
  satellite_link   : Satellite (600ms, 50ms jitter, 2% loss, 5mbit)
  packet_loss      : High loss scenario (30ms, 5% loss, 0.5% dup, 0.1% corrupt)
  wan_degraded     : Degraded WAN (200ms, 80ms jitter, 8% loss, 1mbit)

You can create custom profiles from the Profiles tab.

---

## File Structure

    tc_lab/
    ├── app.py              Main Flask application
    ├── auth.py             Authentication (login, users, roles)
    ├── tc_manager.py       tc/netem interface (apply, reset, scan)
    ├── bridge_manager.py   Linux bridge management (ip link type bridge)
    ├── vlan_manager.py     VLAN sub-interface management (802.1Q)
    ├── ssl_gen.py          Self-signed TLS certificate generator
    ├── setup.sh            One-shot dependency installer
    ├── bridge_setup.sh     Helper to create a transparent bridge
    ├── tc_lab.service      Systemd unit file
    ├── profiles/           JSON impairment profiles
    ├── templates/
    │   ├── index.html      Single-page UI
    │   └── login.html      Login page
    ├── cert.pem            TLS certificate (auto-generated on first run)
    ├── key.pem             TLS private key  (auto-generated on first run)
    ├── state.json          Persisted tc state across restarts
    ├── labels.json         Interface labels/comments
    └── config.json         App config (idle timeout, etc.)

---

## Security Notes

- This tool runs as root and has full control over your network interfaces.
  Do NOT expose port 5000 to the public internet.
- Intended for isolated lab environments only.
- Change the default password immediately.
- The TLS certificate is self-signed. It encrypts traffic but provides no
  identity verification. Import cert.pem into your browser to avoid warnings.

---

## Tested Use Cases

- Fortinet SD-WAN SLA threshold testing
- FortiGate dual-WAN failover and load balancing validation
- Application performance under degraded WAN conditions
- QoS policy validation (voice, video, critical data)
- SASE / SSE latency impact testing
- General network resilience and chaos testing

---

## Troubleshooting

Problem : "Not root" warning on startup
Solution: Run with sudo: sudo venv/bin/python app.py

Problem : tc commands fail silently
Solution: Ensure iproute2 is installed: apt install iproute2

Problem : Bridge not forwarding traffic
Solution: Check STP is off and interfaces are up:
          ip link set br0 type bridge stp_state 0
          ip link set eth0 up; ip link set eth1 up; ip link set br0 up

Problem : cert.pem regenerates every restart
Solution: cert.pem and key.pem must be writable in the working directory.
          Check file permissions: ls -la cert.pem key.pem

Problem : Chrome blocks the page entirely (not just a warning)
Solution: Import cert.pem via chrome://settings/certificates -> Authorities

---

Built with Flask + Linux tc/netem + iproute2
