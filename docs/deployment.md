# Installation & Operation

TC Lab is a Flask web app that drives the Linux traffic-control stack. It shells
out to `tc`, `ip` and `bridge`, so it **must run as root on a Linux host** — there
is no way around that, but the systemd unit bounds what that root can do.

> **Deploy it on a dedicated lab machine or VM.** It reconfigures live network
> interfaces. Never expose port 5000 to an untrusted network.

---

## 1. Requirements

| | Minimum | Notes |
|---|---|---|
| OS | Debian 12/13, Ubuntu 22.04/24.04 | Any systemd Linux with iproute2 works |
| Kernel | modules `sch_netem`, `8021q`, `bridge` | Standard in distro kernels |
| Python | 3.9+ | 3.11+ recommended; tested on 3.13 |
| Privileges | root | for `tc` / `ip` / `bridge` / `modprobe` |
| Network | a **second** NIC for the lab path | keep management traffic on its own NIC |

**System packages** (installed for you by `setup.sh`):

| Package | Why |
|---|---|
| `python3`, `python3-venv`, `python3-pip` | run the app in an isolated virtualenv |
| `iproute2` | provides `tc`, `ip`, `bridge` — the entire engine |
| `bridge-utils` | bridge helpers |
| `rsync` | used by the installer to copy files |

**Python packages** (pinned in `requirements.txt`, installed into a venv):

| Package | Why |
|---|---|
| `Flask` | web framework |
| `Flask-Login` | session/authentication |
| `Flask-WTF` | CSRF protection |
| `Flask-Limiter` | login rate limiting |
| `bcrypt` | password hashing |
| `cryptography` | self-signed TLS certificate generation |

Nothing is fetched from the internet at runtime — no CDNs, no external fonts.
Once installed, TC Lab runs fully offline.

---

## 2. Installation options

Two ways to run it: installed as a service (A), or by hand for development (B).
There is no container option — see [why Docker is not offered](../README.md#-docker--containers).

### Option A — systemd install (recommended for a dedicated appliance)

One command. Installs dependencies with `apt`, copies the app to `/opt/tc_lab`,
builds a virtualenv, generates a TLS certificate, and registers + starts a
systemd service that survives reboots.

```bash
git clone https://github.com/rod-git-hub/TC-GUI-LAB.git
cd TC-GUI-LAB
sudo bash setup.sh
```

What `setup.sh` does, step by step:

| Step | Effect |
|---|---|
| asks about existing accounts | only on an upgrade; keeps them by default |
| `apt-get update && apt-get install …` | installs the system packages listed above |
| `rsync` to `/opt/tc_lab` | the app's permanent home — runtime state is excluded, so this never overwrites accounts, certs or saved topology |
| writes `config.json` | only if absent; an existing one is left alone |
| `python3 -m venv venv` + `pip install -r requirements.txt` | dependencies isolated from system Python |
| `venv/bin/python ssl_gen.py` | generates `cert.pem` / `key.pem` if missing |
| installs `/usr/local/bin/tc-lab` | the recovery CLI |
| writes the systemd unit | from the tracked `tc_lab.service` (sandboxing + boot-time topology restore) |
| `systemctl enable --now tc_lab` | starts it and enables start-at-boot |

Useful overrides:

| Variable | Effect |
|---|---|
| `TC_LAB_DIR` | install somewhere other than `/opt/tc_lab` (the unit is rewritten to match; `ProtectHome` is relaxed automatically for a home-directory install) |
| `TC_LAB_UNIT_DIR` | write the systemd unit somewhere other than `/etc/systemd/system` |

Then open **`https://<server-ip>:5000`** and sign in with `admin` / `tclab123`.
Change that password immediately.

> Your browser will warn about the self-signed certificate — expected. Click
> **Advanced → Proceed**, or import `/opt/tc_lab/cert.pem` as a trusted authority.

### Option B — run it manually (development / one-off)

No install, no service. Runs in the foreground, stops on Ctrl-C.

```bash
cd TC-GUI-LAB
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
sudo ./venv/bin/python app.py
```

State files are written **into the current directory** rather than `/opt/tc_lab`.
Use this for development or a quick trial; use A for anything lasting.

### Comparison

| | A · systemd | B · manual |
|---|---|---|
| Survives reboot | yes | no |
| Privileges | root bounded to 2 capabilities, sandboxed | unconfined root |
| Filesystem | read-only outside `/opt/tc_lab` | read-write |
| Host prerequisites | apt packages (installed for you) | Python 3.9+, iproute2 |
| Upgrade | re-run `setup.sh` (snapshot + rollback) | `git pull` |
| Best for | the lab appliance | development |

---

## 3. Where everything lives

| Path | What |
|---|---|
| `/opt/tc_lab/` | application code (Option A) |
| `/opt/tc_lab/venv/` | Python virtualenv |
| `/etc/systemd/system/tc_lab.service` | service unit |
| `/opt/tc_lab/config.json` | **settings you edit** |
| `/opt/tc_lab/users.json` | accounts + bcrypt hashes (created on first run) |
| `/opt/tc_lab/secret_key.txt` | session signing key (created on first run, `0600`) |
| `/opt/tc_lab/cert.pem`, `key.pem` | TLS certificate and key |
| `/opt/tc_lab/state.json` | applied impairments — replayed on boot |
| `/opt/tc_lab/network_config.json` | bridge/VLAN topology — rebuilt on boot |
| `/opt/tc_lab/labels.json` | per-interface notes |
| `/opt/tc_lab/profiles/*.json` | impairment presets, one file each |
| `/opt/tc_lab/restore_network.log` | boot-time topology restore log |

All writable state can be relocated with the **`TC_LAB_STATE_DIR`** environment
variable — for example onto its own mount. Set it in the unit file:

```ini
Environment=TC_LAB_STATE_DIR=/var/lib/tc_lab
```

---

## 4. Configuration

`config.json` is the only file you normally edit. It is also written by the UI
(Settings → Idle Timeout), so keep it valid JSON.

```json
{
  "idle_timeout_minutes": 30,
  "bind_address": "0.0.0.0",
  "port": 5000
}
```

| Key | Default | Meaning |
|---|---|---|
| `idle_timeout_minutes` | `30` | auto sign-out after inactivity; `0` disables |
| `bind_address` | `0.0.0.0` | **set this to your management IP** to stop the UI listening on the lab NICs |
| `port` | `5000` | TCP port for the web UI |

Changes require a restart:

```bash
sudo systemctl restart tc_lab
```

Environment variables (set in the unit file):

| Variable | Effect |
|---|---|
| `TC_LAB_STATE_DIR` | directory for all writable state (default: working directory) |
| `TC_LAB_SKIP_RESTORE` | start without rebuilding topology or re-applying `tc`. **Only** for a second instance on a host whose interfaces another process owns — never for the real service |

`setup.sh` never overwrites `config.json` on an upgrade — it writes one only when
none exists.

### TLS certificate

On first start TC Lab generates a self-signed certificate for `localhost`,
`tc-lab.local`, `127.0.0.1` and the host's IP addresses, and keeps it across
upgrades. To use your own certificate instead:

```bash
sudo install -m 644 -o root -g root your-cert.pem /opt/tc_lab/cert.pem
```

```bash
sudo install -m 600 -o root -g root your-key.pem /opt/tc_lab/key.pem
```

```bash
sudo systemctl restart tc_lab
```

To generate a fresh self-signed one — for example after changing the host's IP —
delete both files and restart; a new pair is created on start.

### Installer options

```bash
sudo bash setup.sh --help
```

| Flag | Effect |
|---|---|
| `--keep-users` | never prompt; keep existing accounts |
| `--reset-users` | never prompt; delete accounts (a backup is written first) |
| `--no-backup` | skip the pre-upgrade snapshot (rollback is then impossible) |
| `--list-backups` | list the snapshots available to roll back to |
| `--rollback [NAME]` | restore the newest snapshot, or the named one |

| Environment variable | Default | Effect |
|---|---|---|
| `TC_LAB_DIR` | `/opt/tc_lab` | where to install |
| `TC_LAB_BACKUP_DIR` | `/var/backups/tc-lab` | where snapshots are kept |
| `TC_LAB_KEEP_BACKUPS` | `5` | how many snapshots to keep |
| `TC_LAB_SERVICE` | `tc_lab` | systemd service name |
| `TC_LAB_UNIT_DIR` | `/etc/systemd/system` | where the unit file is written |
| `TC_LAB_BIN_DIR` | `/usr/local/bin` | where the `tc-lab` command is linked |

The installer supports **Debian and Ubuntu** (it uses `apt`) and exits with a
clear message elsewhere.

---

## 5. Running it

### Service control (Option A)

```bash
sudo systemctl start tc_lab        # start
sudo systemctl stop tc_lab         # stop (impairments stay in the kernel)
sudo systemctl restart tc_lab      # restart after a config change
sudo systemctl status tc_lab       # state, PID, recent log lines
```

> **Stopping the service does not remove impairments.** Bridges, VLANs and `tc`
> rules live in the kernel and keep working while the UI is down. To actually
> clear them, use Reset in the UI or `tc qdisc del dev <iface> root`.

### Start at boot

`setup.sh` already enables this. To verify or change:

```bash
systemctl is-enabled tc_lab        # expect: enabled
sudo systemctl enable tc_lab       # start automatically at boot
sudo systemctl disable tc_lab      # do not start at boot
```

On boot the unit runs `restore_network.sh` **before** the app (`ExecStartPre`),
recreating VLANs → bridges → members from `network_config.json`; the app then
re-applies `tc` rules from `state.json`.

### Run in the foreground (debugging)

```bash
sudo systemctl stop tc_lab
cd /opt/tc_lab && sudo venv/bin/python app.py
```

Logs stream to the terminal. Ctrl-C to stop, then `systemctl start tc_lab`.

---

## 6. Logs

The app logs to stdout, which systemd captures — there is no application log file.

```bash
journalctl -u tc_lab -n 100          # last 100 lines
journalctl -u tc_lab -f              # follow live
journalctl -u tc_lab --since today   # today only
journalctl -u tc_lab -p err          # errors only
```

The one file-based log is `restore_network.log` in the state directory, written
by the boot-time topology restore. Check it when bridges or VLANs do not come
back after a reboot.

Every applied `tc` command is logged, so the journal doubles as a record of what
was changed.

---

## 7. Upgrading

**Option A (systemd)**:

```bash
cd /path/to/TC-GUI-LAB && git pull
sudo bash setup.sh
sudo systemctl status tc_lab
```

`setup.sh` detects an existing install and **preserves your runtime state** —
accounts, TLS certificate, `config.json`, saved impairments and topology are all
kept. It refreshes only the application code, the virtualenv and the systemd unit.

The one thing it asks about is accounts:

```
  Found an existing account store with 3 account(s):
    /opt/tc_lab/users.json

    [K] Keep them   — everyone signs in with their current password (default)
    [R] Reset them  — delete all accounts; a fresh admin/tclab123 is created

  Keep existing accounts? [K/r]
```

Answer with Enter to keep them. Choosing reset writes a timestamped backup
(`users.json.<date>.bak`) before deleting, so it is recoverable.

To skip the prompt — required for unattended runs:

```bash
sudo bash setup.sh --keep-users      # never prompt, keep accounts
sudo bash setup.sh --reset-users     # never prompt, wipe accounts
```

With no TTY and no flag it defaults to **keeping** accounts and says so.

Before changing anything, `setup.sh` snapshots the whole install — code **and**
state — to `/var/backups/tc-lab/` and keeps the five most recent. Files that are no
longer shipped are removed during the upgrade; your state files and your own
profiles are kept.

After any upgrade, **hard-refresh the browser** (Ctrl-Shift-R). A cached older
page can hold a stale CSRF token, and every action then fails with
*"The CSRF token is missing."*

To undo an upgrade:

```bash
sudo bash setup.sh --rollback
```

A rollback restores **state as well as code** — changes made after the upgrade
are undone. See [upgrading.md](upgrading.md#rolling-back) for the details, and
for the full v9.1 → v9.2 walk-through.

---

## 8. Uninstalling

```bash
# 1. stop and deregister the service
sudo systemctl disable --now tc_lab
sudo rm /etc/systemd/system/tc_lab.service
sudo systemctl daemon-reload

# 2. keep a copy of the config if you may reinstall
sudo tar czf ~/tc_lab-state.tgz -C /opt/tc_lab \
  users.json config.json state.json network_config.json labels.json profiles

# 3. remove the application, its command and its upgrade snapshots
sudo rm -rf /opt/tc_lab
sudo rm -f /usr/local/bin/tc-lab
sudo rm -rf /var/backups/tc-lab

# 4. clear any impairments still in the kernel (per interface)
sudo tc qdisc del dev <iface> root

# 5. remove bridges / VLANs it created, if you no longer want them
sudo ip link del <bridge>
sudo ip link del <vlan>
```

The apt packages (`iproute2`, `bridge-utils`, …) are standard system tools —
leave them installed.

---

## 9. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| *"The CSRF token is missing"* on every action | cached old page — hard-refresh (Ctrl-Shift-R) |
| Service won't start | `journalctl -u tc_lab -n 50`; usually a bad `config.json` or a port already in use |
| `Operation not permitted` from `tc` | not running as root |
| VLAN creation fails | `sudo modprobe 8021q` |
| Bridges/VLANs gone after reboot | check `restore_network.log`; confirm `ExecStartPre` is in the unit |
| Can't reach the UI | check `bind_address` in `config.json`, then the host firewall |
| Locked out after 5 bad logins | rate limit — wait 60 seconds |
