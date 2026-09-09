# TC Lab — WAN Emulator for SD-WAN / Network Labs

A browser-based tool to apply real Linux **tc/netem** impairments to network
interfaces. Built for Fortinet SD-WAN, SASE, and general network lab testing.

![Python](https://img.shields.io/badge/python-3.9%2B-blue)
![Platform](https://img.shields.io/badge/platform-Linux-lightgrey)
![License](https://img.shields.io/badge/license-MIT-green)

---

## ✨ Features

- Apply **latency, jitter, packet loss, duplication, corruption, and rate limiting**
  to any interface in real time
- **Bridge grouping** — control member interfaces together or individually
- **802.1Q VLAN** sub-interface management
- **Impairment profiles** — save and load presets (satellite, LTE, MPLS, etc.)
- HTTPS with auto-generated self-signed TLS
- CSRF protection, hardened session cookies, security headers, login rate-limiting
- Light / Dark theme
- Configurable idle session timeout
- Role-based access — **admin** manages interfaces / bridges / VLANs, **user** changes impairments
- Runs under systemd **or** as a hardened container

---

## 📋 Requirements

| Requirement | Version |
|---|---|
| Linux | Debian 12 / Ubuntu 22.04 / 24.04 |
| Python | 3.9 or newer |
| Privileges | Root (required for tc, ip, bridge) |

---

## 🚀 Quick Start

```bash
# 1. Clone or download the zip and extract
cd tc-lab

# 2. Run the installer (requires root)
sudo bash setup.sh
```

Full instructions — all three install methods, configuration, service control,
logs, upgrade and uninstall — are in **[docs/deployment.md](docs/deployment.md)**.

`setup.sh` will:
- Install all dependencies (`requirements.txt`)
- Copy files to `/opt/tc_lab`
- Create a Python virtualenv
- Generate a self-signed TLS cert
- Install and **start the `tc_lab` systemd service automatically**

Open **https://your-server-ip:5000** in your browser.

> Prefer containers? See [Run as a container](#-run-as-a-container-alternative-to-systemd) below.
> Running the tests: `pip install -r requirements-dev.txt && python -m pytest -q`

> Chrome will warn about the self-signed certificate.
> Click **Advanced → Proceed** to continue, or import `cert.pem` permanently
> via `chrome://settings/certificates` → Authorities → Import → Trust for HTTPS.

**Default credentials:** `admin` / `tclab123`
⚠️ Change your password immediately after first login (Settings → Change Password).

---

## 🔧 Service Management

```bash
# Status
sudo systemctl status tc_lab

# Start / Stop / Restart
sudo systemctl restart tc_lab

# Logs
journalctl -u tc_lab -n 100

# Install path
ls /opt/tc_lab/
```

---

## 🐳 Run as a container (alternative to systemd)

The app has to manage the **host's** real interfaces, so the container shares the host
network namespace — but runs with only `NET_ADMIN`/`NET_RAW`, `no-new-privileges`, and a
read-only root filesystem instead of as unconfined host root.

**Host prerequisites** (the container can't load kernel modules itself under host networking):

```bash
sudo cp modules-load.d/tc-lab.conf /etc/modules-load.d/
sudo modprobe 8021q sch_netem br_netfilter
echo 1 | sudo tee /proc/sys/net/ipv4/ip_forward      # for bridged / routed labs
```

**Start:**

```bash
docker compose up -d --build
```

Open **https://your-host-ip:5000** (same default login). State (users, TLS cert, profiles,
topology) lives in the `tc-lab-state` volume and survives `docker compose down`.

| | systemd | Container |
|---|---|---|
| Manages host interfaces | yes | yes (`--network host`) |
| Privileges | unconfined root | root limited to `NET_ADMIN` + `NET_RAW` |
| Filesystem | read-write | read-only + state volume |

---

# Configuration

## Create an 🔌 SubInterfaces / VLANs
1.  Physical Interfaces & VLAN Sub-interfaces
    - Make sure your physical interfaces are listed here.
    - Create your SubInterface and VLANs to be used later by a Bridge.


## Create a 🌉 via Bridge Manager
1.  Using the SubInterfaces created in the 🔌 Interfaces / VLANs
    - Pair them with a Bridge; that bridge interface will be configured later with your traffic control.
    - Optionally, you can bridge whole interfaces if you want.


## 🎛  Applying TC Impairments
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

## 📦 Included Profiles

| Profile | Description |
|---|---|
| `good_link` | Clean baseline |
| `mpls_good` | Low-latency MPLS (10ms, 100mbit) |
| `broadband` | Typical broadband (20ms, 50mbit, 0.1% loss) |
| `high_latency_wan` | Slow WAN (150ms, 20ms jitter, 0.5% loss) |
| `lte_congested` | Congested LTE (80ms, 30ms jitter, 1.5% loss) |
| `satellite_link` | Satellite (600ms, 50ms jitter, 2% loss) |
| `packet_loss` | High loss scenario (5% loss, 0.5% dup) |
| `wan_degraded` | Degraded WAN (200ms, 80ms jitter, 8% loss) |

---

## 🔒 Security Notes

> **This tool runs as root. Do NOT expose port 5000 to the public internet.**
> Intended for **isolated lab environments only.**

- Passwords are bcrypt-hashed; login is rate-limited
- Transport is TLS-encrypted (self-signed cert); cookies are `Secure` + `SameSite=Strict`
- CSRF tokens on every state-changing request; security headers + CSP on every response
- Config-import bundles are fully validated before anything is written or replayed
- Change the default password immediately
- Bind to your management IP (`bind_address` in `config.json`) and firewall port 5000
- Prefer the container deployment — it drops all capabilities except `NET_ADMIN`/`NET_RAW`

See [SECURITY.md](SECURITY.md) for the security model and known limitations,
and [docs/users-and-security.md](docs/users-and-security.md) for how accounts,
password hashing, roles and hardening actually work.

---

## 🗂 Project Structure

```
tc-lab/
├── app.py              # Main Flask application (routes, validation, CSRF, headers)
├── auth.py             # Auth: login, users, roles, rate-limiter, decorators
├── tc_manager.py       # tc/netem interface (apply, reset, scan)
├── bridge_manager.py   # Linux bridge management
├── vlan_manager.py     # 802.1Q VLAN sub-interface management
├── ssl_gen.py          # Self-signed TLS certificate generator
├── restore_helper.py   # Network restore logic (VLANs → bridges → members)
├── restore_network.sh  # Called by systemd ExecStartPre / container entrypoint
├── setup.sh            # systemd installer (deploys to /opt/tc_lab)
├── tc_lab.service      # systemd unit (sandboxed)
├── Dockerfile          # Container image
├── docker-compose.yml  # Hardened container deployment
├── entrypoint.sh       # Container entrypoint (restore + run)
├── requirements.txt    # Pinned runtime deps  (requirements-dev.txt adds pytest)
├── profiles/           # Default JSON impairment profiles (seed data)
├── templates/          # HTML templates (index.html, login.html)
├── tools/ui-preview.py # Render the UI against a fixture, no backend needed
├── docs/               # deployment, users & security, upgrade guides
├── tests/              # pytest security regression suite
└── <STATE_DIR>/        # Writable state — defaults to the app dir; set
    ├── network_config.json #   TC_LAB_STATE_DIR to move onto a volume.
    ├── state.json          #   Auto-managed. Never commit these.
    ├── users.json          #   bcrypt hashes, created on first run
    ├── secret_key.txt      #   Flask session key
    └── cert.pem / key.pem  #   self-signed TLS
```

---

## 🧪 Tested Use Cases

- Fortinet SD-WAN SLA threshold testing
- FortiGate dual-WAN failover and load balancing validation
- Application performance under degraded WAN conditions
- QoS policy validation (voice, video, critical data)
- SASE / SSE latency impact testing

---

## Screenshots

![TC login](https://github.com/user-attachments/assets/d63dbd0b-c29a-48d1-b8aa-14f37926ef4d)


![TC Traffic Emulation Control](https://github.com/user-attachments/assets/d3ba2b8d-0ca2-4216-9d9f-7ce2920ec7c8)


![TC Bridge Manager](https://github.com/user-attachments/assets/633ea034-63b9-49b8-a4ef-0a4484ae61bb)


![TC Interface Manager](https://github.com/user-attachments/assets/80ba48c4-5f8b-4d48-a630-149d0a0579ab)


![Design Sample Diagram](https://github.com/user-attachments/assets/f0ad6610-5d49-46e8-9d68-17c4d95112ad)

---

## 🤝 Contributing

Pull requests welcome. For major changes, open an issue first.

1. Fork the repo
2. Create a feature branch (`git checkout -b feature/my-feature`)
3. Commit your changes (`git commit -m 'Add my feature'`)
4. Push to the branch (`git push origin feature/my-feature`)
5. Open a Pull Request

---

## 📄 License

[MIT](LICENSE) — free to use, modify, and distribute.
