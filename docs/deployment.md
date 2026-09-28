# Installation & Operation

TC Lab is a Flask web app that drives the Linux traffic-control stack. It shells
out to `tc` and `ip`, which need **network-admin rights** (`CAP_NET_ADMIN`) on the
host. Installed as a service, it runs as its own unprivileged user, `tc-lab`, that
holds exactly those rights and can write only its own state directory.

> **Deploy it on a dedicated lab machine or VM.** It reconfigures live network
> interfaces. Never expose the dashboard port (5000 by default) to an untrusted
> network.

---

## 1. Requirements

| | Minimum | Notes |
|---|---|---|
| OS | Debian 12/13, Ubuntu 22.04/24.04 | the installer uses `apt` and systemd |
| Kernel | modules `sch_netem`, `sch_htb`, `8021q`, `bridge` | standard in distro kernels, loaded by the kernel when needed |
| Python | 3.9+ | 3.11+ recommended; tested on 3.13 |
| Privileges | root to install | the service itself runs as the `tc-lab` user |
| Network | a **second** NIC for the lab path | keep management traffic on its own NIC |

**System packages** (installed for you by `setup.sh`):

| Package | Why |
|---|---|
| `python3`, `python3-venv`, `python3-pip` | run the app in an isolated virtualenv |
| `iproute2` | provides `tc` and `ip` — the entire engine |
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
| `Markdown` | shows this documentation inside the dashboard (Help) |

Nothing is fetched from the internet at runtime — no CDNs, no external fonts; the
Help pages are part of the install. Once installed, TC Lab runs fully offline.

---

## 2. Installation options

Two ways to run it: installed as a service (A), or by hand for development (B).
There is no container option — see [why Docker is not offered](../README.md#-docker--containers).

### Option A — systemd install (recommended for a dedicated appliance)

One command. Installs dependencies with `apt`, copies the app to `/opt/tc_lab`,
creates the `tc-lab` service user and its state directory `/var/lib/tc_lab`,
builds a virtualenv, generates a TLS certificate, and registers and starts a
systemd service that survives reboots.

```bash
git clone https://github.com/rod-git-hub/TC-GUI-LAB.git
cd TC-GUI-LAB
sudo bash setup.sh
```

To use another port than 5000, add `--port`, for example `sudo bash setup.sh --port 8443`.

What `setup.sh` does, step by step:

| Step | Effect |
|---|---|
| checks `--port`, if given | a number from 1024 to 65535 that nothing is listening on — checked before anything changes |
| asks about existing accounts | only on an upgrade; keeps them by default |
| `apt-get update && apt-get install …` | installs the system packages listed above |
| snapshot | on an upgrade: code and state to `/var/backups/tc-lab` |
| creates the `tc-lab` user | a system user with no login shell and no home directory |
| moves state out of `/opt/tc_lab` | only when upgrading from v9.2.x or earlier — see [upgrading.md](upgrading.md) |
| `rsync` to `/opt/tc_lab` | the application code; files no longer shipped are removed |
| prepares `/var/lib/tc_lab` | adds any missing shipped profiles; writes `config.json` only if absent; applies `--port` |
| `python3 -m venv venv` + `pip install -r requirements.txt` | dependencies isolated from system Python |
| `ssl_gen.py` | generates `cert.pem` / `key.pem` in `/var/lib/tc_lab` if missing |
| ownership | code: root, not writable by anyone else; state: `tc-lab`, readable by nobody else |
| installs `/usr/local/bin/tc-lab` | the administration command |
| writes the systemd unit | from the tracked `tc_lab.service` (confinement + boot-time topology restore) |
| `systemctl enable` + `restart` | starts it and enables start-at-boot |

Then open **`https://<server-ip>:5000`** (or the port you chose) and sign in with
`admin` / `tclab123`. Change that password immediately.

> Your browser will warn about the self-signed certificate — expected. Click
> **Advanced → Proceed**, or import `/var/lib/tc_lab/cert.pem` as a trusted authority.

### Option B — run it manually (development / one-off)

No install, no service. Runs in the foreground, stops on Ctrl-C.

```bash
cd TC-GUI-LAB
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
sudo ./venv/bin/python app.py
```

State files are written **into the current directory**. Use this for development or
a quick trial; use A for anything lasting. Do not do this inside `/opt/tc_lab` on a
host where the service is installed — see [See it run live](#see-it-run-live).

### Comparison

| | A · systemd | B · manual |
|---|---|---|
| Survives reboot | yes | no |
| Runs as | the `tc-lab` user, with only `CAP_NET_ADMIN` | root, unconfined |
| Can write | only `/var/lib/tc_lab` | anything root can |
| Host prerequisites | apt packages (installed for you) | Python 3.9+, iproute2 |
| Upgrade | re-run `setup.sh` (snapshot + rollback) | `git pull` |
| Best for | the lab appliance | development |

---

## 3. Where everything lives

| Path | What |
|---|---|
| `/opt/tc_lab/` | application code — owned by root, read-only to the service |
| `/opt/tc_lab/venv/` | Python virtualenv |
| `/var/lib/tc_lab/` | **everything the service writes** — owned by `tc-lab`, mode `700` |
| `/var/lib/tc_lab/config.json` | **settings you edit** |
| `/var/lib/tc_lab/users.json` | accounts + bcrypt hashes (created on first start) |
| `/var/lib/tc_lab/secret_key.txt` | session signing key (created on first start) |
| `/var/lib/tc_lab/cert.pem`, `key.pem` | TLS certificate and key |
| `/var/lib/tc_lab/state.json` | applied impairments — replayed on boot |
| `/var/lib/tc_lab/network_config.json` | bridge/VLAN topology — rebuilt on boot |
| `/var/lib/tc_lab/labels.json` | per-interface notes |
| `/var/lib/tc_lab/profiles/*.json` | impairment presets, one file each |
| `/var/lib/tc_lab/restore_network.log` | boot-time topology restore log |
| `/etc/systemd/system/tc_lab.service` | service unit |
| `/usr/local/bin/tc-lab` | administration command |
| `/var/backups/tc-lab/` | snapshots taken before each upgrade |

To keep the state somewhere else — for example on its own mount — install with
`TC_LAB_STATE_DIR` set; the installer writes that path into the unit, and later
upgrades read it back from there:

```bash
sudo TC_LAB_STATE_DIR=/srv/tc_lab bash setup.sh
```

The `tc-lab` command also reads the state directory from the installed unit.

---

## 4. Configuration

`config.json` (in `/var/lib/tc_lab`) is the only file you normally edit. The
dashboard writes it too (Settings → Idle Timeout and Service Port), so keep it
valid JSON.

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
| `port` | `5000` | TCP port for the web UI, `1024`–`65535` |

After editing the file by hand, restart:

```bash
sudo systemctl restart tc_lab
```

### Changing the port

Any of these works. All accept `1024`–`65535`; Settings and the installer also
refuse a port something else is listening on, and `tc-lab set-port` warns about one.

| How | Notes |
|---|---|
| **Settings → Service Port** (admins) | TC Lab restarts itself on the new port within a few seconds — impairments keep running — and the page follows to the new address |
| `sudo bash setup.sh --port 8443` | during an install or upgrade |
| `sudo tc-lab set-port 8443` | then `sudo systemctl restart tc_lab`. The way back if the dashboard can no longer be reached, e.g. a firewall only allows the old port |

Ports below 1024 (such as 443) are not available: the service does not run as
root. If `config.json` asks for one — possible under v9.2, which did — TC Lab uses
5000 instead and says so in its log.

Your browser remembers the dark/light theme per address, so it may need setting
again after a port change.

### Environment variables

Set in the unit file by the installer:

| Variable | Effect |
|---|---|
| `TC_LAB_STATE_DIR` | directory for all writable state (`/var/lib/tc_lab`; when run by hand: the current directory) |
| `TC_LAB_SKIP_RESTORE` | start without rebuilding topology or re-applying `tc`. **Only** for a second instance on a host whose interfaces another process owns — never for the real service |

`setup.sh` never overwrites `config.json` on an upgrade — it writes one only when
none exists, and `--port` changes only the port.

### TLS certificate

On first start TC Lab generates a self-signed certificate for `localhost`,
`tc-lab.local`, `127.0.0.1` and the host's IP addresses, and keeps it across
upgrades. To use your own certificate instead:

```bash
sudo install -m 644 -o tc-lab -g tc-lab your-cert.pem /var/lib/tc_lab/cert.pem
```

```bash
sudo install -m 600 -o tc-lab -g tc-lab your-key.pem /var/lib/tc_lab/key.pem
```

```bash
sudo systemctl restart tc_lab
```

Both files must belong to `tc-lab`, or the service cannot read them. A certificate
with less than 30 days left is replaced by a new self-signed one on start, so
renew yours before then.

To generate a fresh self-signed one — for example after changing the host's IP —
delete both files and restart; a new pair is created on start.

### Installer options

```bash
sudo bash setup.sh --help
```

| Flag | Effect |
|---|---|
| `--port N` | set the dashboard port (1024–65535) |
| `--keep-users` | never prompt; keep existing accounts |
| `--reset-users` | never prompt; delete accounts (a backup is written first) |
| `--no-backup` | skip the pre-upgrade snapshot (rollback is then impossible) |
| `--list-backups` | list the snapshots available to roll back to |
| `--rollback [NAME]` | restore the newest snapshot, or the named one |

| Environment variable | Default | Effect |
|---|---|---|
| `TC_LAB_DIR` | `/opt/tc_lab` | where to install the code |
| `TC_LAB_STATE_DIR` | `/var/lib/tc_lab`, or the installed unit's | where the service keeps its state |
| `TC_LAB_USER` | `tc-lab`, or the installed unit's | the user the service runs as |
| `TC_LAB_BACKUP_DIR` | `/var/backups/tc-lab` | where snapshots are kept |
| `TC_LAB_KEEP_BACKUPS` | `5` | how many snapshots to keep |
| `TC_LAB_SERVICE` | `tc_lab` | systemd service name |
| `TC_LAB_UNIT_DIR` | `/etc/systemd/system` | where the unit file is written |
| `TC_LAB_BIN_DIR` | `/usr/local/bin` | where the `tc-lab` command is linked |

An install or state directory under `/home` or `/root` works; the installer then
relaxes `ProtectHome` in the unit so the service can reach it.

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

### See it run live

```bash
journalctl -u tc_lab -f
```

This shows exactly what the app prints, as it happens. Do not start
`/opt/tc_lab/app.py` by hand on an installed host: it would run as root with a
second set of state files inside `/opt/tc_lab`, separate from the service's. (If
that has happened, the installer notices those files on the next upgrade and
leaves your real state alone; delete them once you are sure.)

### Check the confinement

```bash
ps -o user= -p "$(systemctl show tc_lab -p MainPID --value)"
grep CapEff /proc/$(systemctl show tc_lab -p MainPID --value)/status
```

Expect the user `tc-lab` and `CapEff: 0000000000001000` — exactly `CAP_NET_ADMIN`.
`systemd-analyze security tc_lab` rates the unit's sandboxing.

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
accounts, TLS certificate, `config.json`, saved impairments, topology and profiles
are all kept. It refreshes only the application code, the virtualenv and the
systemd unit. Upgrading from v9.2.x also moves the state from `/opt/tc_lab` to
`/var/lib/tc_lab` — see [upgrading.md](upgrading.md).

The one thing it asks about is accounts:

```
  Found an existing account store with 3 account(s):
    /var/lib/tc_lab/users.json

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

Before changing anything, `setup.sh` snapshots the code **and** the state to
`/var/backups/tc-lab/` and keeps the five most recent. Files that are no longer
shipped are removed during the upgrade; your state files and your own profiles are
kept.

After any upgrade, **hard-refresh the browser** (Ctrl-Shift-R). A cached older
page can hold a stale CSRF token, and every action then fails with
*"The CSRF token is missing."*

To undo an upgrade:

```bash
sudo bash setup.sh --rollback
```

A rollback restores **state as well as code** — changes made after the upgrade
are undone. See [upgrading.md](upgrading.md#rolling-back) for the details, and
for the full walk-through from any v9.x release.

---

## 8. Uninstalling

```bash
# 1. stop and deregister the service
sudo systemctl disable --now tc_lab
sudo rm /etc/systemd/system/tc_lab.service
sudo systemctl daemon-reload

# 2. keep a copy of the state if you may reinstall
sudo tar czf ~/tc_lab-state.tgz -C /var/lib/tc_lab .

# 3. remove the application, its state, its command, its snapshots and its user
sudo rm -rf /opt/tc_lab /var/lib/tc_lab
sudo rm -f /usr/local/bin/tc-lab
sudo rm -rf /var/backups/tc-lab
sudo userdel tc-lab

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
| Service won't start | `journalctl -u tc_lab -n 50`; usually a bad `config.json`, a port already in use, or state files not owned by `tc-lab` |
| Dashboard unreachable after a port change | `sudo tc-lab set-port 5000`, then `sudo systemctl restart tc_lab` |
| `Operation not permitted` from `tc` or `ip` | the service is missing its capabilities — check [the confinement](#check-the-confinement); by hand, run `app.py` with `sudo` |
| Settings or accounts will not save | files in `/var/lib/tc_lab` owned by someone else (e.g. copied in as root): `sudo chown -R tc-lab: /var/lib/tc_lab` |
| VLAN creation fails | the kernel could not load `8021q`: `sudo modprobe 8021q` |
| Bridges/VLANs gone after reboot | check `restore_network.log`; confirm `ExecStartPre` is in the unit |
| Can't reach the UI | check `bind_address` and `port` in `config.json`, then the host firewall |
| Locked out after 5 bad logins | rate limit — wait 60 seconds |
