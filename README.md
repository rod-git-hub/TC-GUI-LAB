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
- Role-based access — **admin** manages interfaces / bridges / VLANs and user accounts,
  **user** changes impairments
- **User management in the dashboard** (admin-only) + `sudo tc-lab reset-admin-password` recovery
- Runs as a sandboxed systemd service, confined to 2 of root's 40 capabilities

---

## 📋 Requirements

| Requirement | Version |
|---|---|
| Linux | Debian 12 / 13, Ubuntu 22.04 / 24.04 — the installer uses `apt` |
| Init system | systemd |
| Python | 3.9 or newer (installed for you) |
| Privileges | Root (required for tc, ip, bridge) |

---

## 🚀 Quick Start

```bash
# 1. Clone or download the zip and extract
cd tc-lab

# 2. Run the installer (requires root)
sudo bash setup.sh
```

Full instructions — installation, configuration, service control, logs and
uninstall — are in **[docs/deployment.md](docs/deployment.md)**.
Already running an older version? Follow **[docs/upgrading.md](docs/upgrading.md)**.

`setup.sh` will:
- Install all dependencies (`requirements.txt`)
- Copy files to `/opt/tc_lab`
- Create a Python virtualenv
- Generate a self-signed TLS cert
- Install and **start the `tc_lab` systemd service automatically**

Open **https://your-server-ip:5000** in your browser.

> Running the tests: `pip install -r requirements-dev.txt && python -m pytest -q`

> Chrome will warn about the self-signed certificate.
> Click **Advanced → Proceed** to continue, or import `cert.pem` permanently
> via `chrome://settings/certificates` → Authorities → Import → Trust for HTTPS.

**Default credentials:** `admin` / `tclab123`
⚠️ Change your password immediately after first login (Settings → Change Password).

---

## 📚 Documentation

| Document | What it covers |
|---|---|
| [RELEASE_NOTES.md](RELEASE_NOTES.md) | What is new in this version, and what to know before upgrading |
| [docs/user-guide.md](docs/user-guide.md) | **Using TC Lab** — every page of the dashboard, with screenshots |
| [docs/deployment.md](docs/deployment.md) | Installation, **configuration** (`config.json`, TLS, installer options), service control, logs, uninstall |
| [docs/upgrading.md](docs/upgrading.md) | **Upgrading** from v9.x, verifying, and rolling back |
| [docs/users-and-security.md](docs/users-and-security.md) | Accounts, roles, password handling, hardening |
| [SECURITY.md](SECURITY.md) | Security model, fixes, and known limitations |
| [CHANGELOG.md](CHANGELOG.md) | Detailed change history, every version |
| [CONTRIBUTING.md](CONTRIBUTING.md) | Working on TC Lab: tests, screenshots, release checklist |

On the host, `tc-lab --help` lists the administration commands.

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

### Account recovery

If no admin can sign in, reset the admin password from a shell on the host:

```bash
sudo tc-lab reset-admin-password
```

Prompts for the new password without echoing it, updates only the `admin`
account, and leaves every other account untouched. `sudo tc-lab list-users`
shows accounts and roles (never hashes).

---

## 🔐 How the service is confined

TC Lab has to run as root — `tc`, `ip` and `bridge` need it — so the systemd unit
limits what that root can do:

| | |
|---|---|
| **Capabilities** | `CAP_NET_ADMIN` and `CAP_NET_RAW` only — 2 of root's 40. No `CAP_SYS_ADMIN`, `CAP_SYS_PTRACE`, `CAP_DAC_OVERRIDE`, `CAP_SETUID` or the rest. |
| **Filesystem** | `ProtectSystem=full`, `ProtectHome=yes`, writable only under `/opt/tc_lab` |
| **Process** | `NoNewPrivileges`, `PrivateTmp`, `MemoryDenyWriteExecute`, `RestrictSUIDSGID`, … |
| **Install ownership** | `/opt/tc_lab` is owned by root and not group/other-writable |

Check it on a running install:

```bash
grep CapEff /proc/$(systemctl show tc_lab -p MainPID --value)/status
```

`0000000000003000` means exactly those two capabilities. Kernel modules such as
`8021q` and `sch_htb` are still loaded on demand — by the kernel, not by TC Lab.

---

## 🐳 Docker / containers

**Not supported.** TC Lab installs and runs as a systemd service only; there is no
container image. A container build was prototyped during v9.2 and dropped before
release, for three reasons:

- **There is nothing for a container to isolate.** TC Lab's whole job is to change
  the *host's* real interfaces, so a container would have to share the host's
  network (`--network host`). It gets no network isolation.
- **Its one real benefit is already here.** Containers are safer mainly because
  they drop root's capabilities. The systemd unit does that itself — down to the
  same two a container would keep ([details](#-how-the-service-is-confined)).
- **Installing Docker changes the host networking TC Lab depends on.** Docker loads
  `br_netfilter`, which sends *bridged* frames through iptables, and sets the
  iptables `FORWARD` policy to `DROP`. On a machine whose job is bridging lab
  traffic, that can silently stop traffic crossing your bridges while everything
  still looks correctly configured.

If Docker is already on the host for something else, TC Lab ignores its bridges
(`docker0`, `br-…`) — they never enter saved topology or config exports. Check
whether bridged traffic is being filtered:

```bash
sysctl net.bridge.bridge-nf-call-iptables
```

`1` means it is. `sudo sysctl -w net.bridge.bridge-nf-call-iptables=0` stops it
(add it to a file in `/etc/sysctl.d/` to survive a reboot). If the key does not
exist, `br_netfilter` is not loaded and there is nothing to do.

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

Every page of the dashboard — profiles, export/import, users, settings, roles — is
described step by step, with screenshots, in the
**[user guide](docs/user-guide.md)**.

---

## 📦 Included Profiles

| Profile | Simulates | Latency | Jitter | Loss | Duplicate | Corrupt | Rate |
|---|---|--:|--:|--:|--:|--:|--:|
| `good_link` | a near-clean baseline | 5 ms | 1 ms | — | — | — | — |
| `mpls_good` | a good MPLS circuit | 10 ms | 2 ms | — | — | — | 100 mbit |
| `broadband` | typical broadband | 20 ms | 8 ms | 0.1% | — | — | 50 mbit |
| `high_latency_wan` | a slow, distant WAN | 150 ms | 20 ms | 0.5% | — | — | 10 mbit |
| `lte_congested` | congested LTE | 80 ms | 30 ms | 1.5% | 0.2% | — | 2 mbit |
| `satellite_link` | a satellite link | 600 ms | 50 ms | 2% | — | — | 5 mbit |
| `packet_loss` | a lossy but otherwise normal link | 30 ms | 5 ms | 5% | 0.5% | 0.1% | — |
| `wan_degraded` | a badly degraded WAN | 200 ms | 80 ms | 8% | 1% | 0.5% | 1 mbit |

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
- The service runs with 2 of root's 40 capabilities — see
  [How the service is confined](#-how-the-service-is-confined)

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
├── restore_network.sh  # Called by systemd ExecStartPre
├── setup.sh            # systemd installer (deploys to /opt/tc_lab)
├── tc_lab.service      # systemd unit (sandboxed)
├── cli.py              # `tc-lab` CLI — admin password recovery
├── tc-lab              # CLI wrapper, symlinked to /usr/local/bin by setup.sh
├── requirements.txt    # Pinned runtime deps  (requirements-dev.txt adds pytest)
├── RELEASE_NOTES.md    # What's new in this version, upgrade notes
├── CHANGELOG.md        # Full change history
├── profiles/           # Default JSON impairment profiles (seed data)
├── templates/          # HTML templates (index.html, login.html)
├── tools/              # ui-preview.py, capture-screenshots.py (dev helpers)
├── docs/               # deployment, upgrading, users & security, screenshots
├── tests/              # pytest suite (security, users, managers)
└── <STATE_DIR>/        # Writable state — defaults to the app dir; set
    ├── config.json         #   TC_LAB_STATE_DIR to move onto a volume.
    ├── network_config.json #   All auto-managed. Never commit these.
    ├── state.json          #   Saved impairments, replayed on boot
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

### TC Emulation — impairments per interface or per bridge
![TC Emulation](docs/img/02-tc-emulation.png)

### Member controls — fine-tune each side of a bridge
![Member controls](docs/img/09-member-controls.png)

### Interfaces & VLANs — physical NICs with their 802.1Q sub-interfaces
![Interfaces and VLANs](docs/img/03-interfaces-vlans.png)

### Bridge Manager — group interfaces into a path
![Bridge Manager](docs/img/04-bridge-manager.png)

### Profiles & lab config — presets, export and import
![Profiles and lab config](docs/img/07-profiles.png)

### Live tc statistics
![Interface statistics](docs/img/10-interface-stats.png)

### User Management — admin-only accounts and roles
![User Management](docs/img/05-user-management.png)

### The same page for a `user` — structural controls hidden
![Bridge Manager as a user](docs/img/11-user-role.png)

### Settings — password, idle timeout, theme
![Settings](docs/img/08-settings.png)

### Sign in
![Sign in](docs/img/01-login.png)

### Light theme
![Light theme](docs/img/06-light-theme.png)

<sub>Screenshots are generated from the UI itself, with demo interfaces, by
<code>python3 tools/capture-screenshots.py</code> — re-run it after any UI change
so they never go stale.</sub>

### Reference topology
![Design Sample Diagram](https://github.com/user-attachments/assets/f0ad6610-5d49-46e8-9d68-17c4d95112ad)

---

## 🤝 Contributing

Pull requests welcome. For major changes, open an issue first. Before you start,
read **[CONTRIBUTING.md](CONTRIBUTING.md)** — how to run the tests, regenerate the
screenshots, and what never goes into a commit.

1. Fork the repo
2. Create a feature branch (`git checkout -b feature/my-feature`)
3. Commit your changes (`git commit -m 'Add my feature'`)
4. Push to the branch (`git push origin feature/my-feature`)
5. Open a Pull Request

---

## 📄 License

[MIT](LICENSE) — free to use, modify, and distribute.
