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
- Light / Dark theme
- Configurable idle session timeout
- Role-based access (admin / user)

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
# 1. Clone
git clone https://github.com/YOUR_USERNAME/tc-lab.git
cd tc-lab

# 2. Install dependencies
sudo bash setup.sh

# 3. Run
sudo venv/bin/python app.py
```

Open **https://your-server-ip:5000** in your browser.

> Chrome will warn about the self-signed certificate.
> Click **Advanced → Proceed** to continue.

**Default credentials:** `admin` / `tclab123`
⚠️ Change your password immediately after first login (Settings → Change Password).

---

## 🌉 Bridge Setup for WAN Emulation

To insert this Linux box transparently between a firewall and WAN link:

```bash
sudo bash bridge_setup.sh br0 eth0 eth1
```

This creates: `Firewall ↔ eth0 [br0] eth1 ↔ WAN`

Apply impairments to `br0` and they affect all traffic passing through.

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

- Passwords are bcrypt-hashed
- Transport is TLS-encrypted (self-signed cert)
- Change the default password immediately
- Firewall port 5000 to management workstations only

See [SECURITY.md](SECURITY.md) for the full security model and known limitations.

---

## 🗂 Project Structure

```
tc-lab/
├── app.py              # Main Flask application
├── auth.py             # Authentication (login, users, roles)
├── tc_manager.py       # tc/netem interface (apply, reset, scan)
├── bridge_manager.py   # Linux bridge management
├── vlan_manager.py     # 802.1Q VLAN sub-interface management
├── ssl_gen.py          # Self-signed TLS certificate generator
├── setup.sh            # One-shot dependency installer
├── bridge_setup.sh     # Helper to create a transparent bridge
├── tc_lab.service      # Systemd unit file
├── profiles/           # JSON impairment profiles
└── templates/          # HTML templates (index.html, login.html)
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
