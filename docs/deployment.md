# Installation & Operation

TC Lab is a Flask web app that drives the Linux traffic-control stack. It shells
out to `tc`, `ip` and `bridge`, so it **must run as root on a Linux host** — there
is no way around that, but the container option bounds what "root" can do.

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

Three supported ways to run it. Pick one.

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
| `apt-get update && apt-get install …` | installs the system packages listed above |
| `rsync` to `/opt/tc_lab` | the app's permanent home |
| `python3 -m venv venv` + `pip install -r requirements.txt` | dependencies isolated from system Python |
| `venv/bin/python ssl_gen.py` | generates `cert.pem` / `key.pem` if missing |
| `rm -f users.json` | forces the default admin account on first start |
| writes `/etc/systemd/system/tc_lab.service` | the unit definition |
| `systemctl enable --now tc_lab` | starts it and enables start-at-boot |

Then open **`https://<server-ip>:5000`** and sign in with `admin` / `tclab123`.
Change that password immediately.

> Your browser will warn about the self-signed certificate — expected. Click
> **Advanced → Proceed**, or import `/opt/tc_lab/cert.pem` as a trusted authority.

### Option B — container (recommended when you want the privileges bounded)

The container still manages the host's real interfaces (it shares the host
network namespace), but it runs with **only `CAP_NET_ADMIN` and `CAP_NET_RAW`**
instead of unconfined root, on a read-only filesystem, with `no-new-privileges`.

Host prerequisites — the container cannot load kernel modules itself:

```bash
sudo cp modules-load.d/tc-lab.conf /etc/modules-load.d/
sudo modprobe 8021q sch_netem br_netfilter
echo 1 | sudo tee /proc/sys/net/ipv4/ip_forward
```

Then:

```bash
sudo docker compose up -d --build     # build image and start
sudo docker compose logs -f           # follow logs
sudo docker compose down              # stop and remove the container
```

State (accounts, TLS cert, profiles, topology) lives in the `tc-lab-state`
Docker volume and survives `down`/`up` and image rebuilds.

### Option C — run it manually (development / one-off)

No install, no service. Runs in the foreground, stops on Ctrl-C.

```bash
cd TC-GUI-LAB
python3 -m venv venv
./venv/bin/pip install -r requirements.txt
sudo ./venv/bin/python app.py
```

State files are written **into the current directory** rather than `/opt/tc_lab`.
Use this for development or a quick trial; use A or B for anything lasting.

### Comparison

| | A · systemd | B · container | C · manual |
|---|---|---|---|
| Survives reboot | yes | yes (`restart: unless-stopped`) | no |
| Privileges | unconfined root | root limited to `NET_ADMIN`+`NET_RAW` | unconfined root |
| Filesystem | read-write | read-only + state volume | read-write |
| Host prerequisites | apt packages | Docker + kernel modules | Python 3.9+ |
| Upgrade | re-run `setup.sh` | `compose up -d --build` | `git pull` |
| Best for | dedicated lab appliance | shared/hardened host | development |

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
variable — that is how the container keeps its root filesystem read-only. Set it
in the unit file:

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

Environment variables (set in the unit file or the container):

| Variable | Effect |
|---|---|
| `TC_LAB_STATE_DIR` | directory for all writable state (default: working directory) |
| `TC_LAB_SKIP_RESTORE` | start without rebuilding topology or re-applying `tc`. **Only** for a second instance on a host whose interfaces another process owns — never for the real service |

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

Container:

```bash
sudo docker compose logs -f
```

The one file-based log is `restore_network.log` in the state directory, written
by the boot-time topology restore. Check it when bridges or VLANs do not come
back after a reboot.

Every applied `tc` command is logged, so the journal doubles as a record of what
was changed.

---

## 7. Upgrading

**Option A (systemd)** — back up first; state files are preserved:

```bash
sudo systemctl stop tc_lab
sudo cp -a /opt/tc_lab /opt/tc_lab.bak-$(date +%F)
cd /path/to/TC-GUI-LAB && git pull
sudo bash setup.sh
sudo systemctl status tc_lab
```

`setup.sh` is safe to re-run: it refreshes code and dependencies. It does delete
`users.json`, so **back it up first if you have accounts you want to keep**:

```bash
sudo cp /opt/tc_lab/users.json /root/users.json.bak
# ...after setup.sh...
sudo cp /root/users.json.bak /opt/tc_lab/users.json && sudo chmod 600 /opt/tc_lab/users.json
```

**Option B (container)**:

```bash
git pull && sudo docker compose up -d --build
```

After any upgrade, **hard-refresh the browser** (Ctrl-Shift-R). A cached older
page can hold a stale CSRF token, and every action then fails with
*"The CSRF token is missing."*

Rolling back = restoring the backup directory and restarting.

> Migrating an existing v9.x install to v9.2 has extra steps —
> see [upgrade-to-9.2.md](upgrade-to-9.2.md).

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

# 3. remove the application
sudo rm -rf /opt/tc_lab

# 4. clear any impairments still in the kernel (per interface)
sudo tc qdisc del dev <iface> root

# 5. remove bridges / VLANs it created, if you no longer want them
sudo ip link del <bridge>
sudo ip link del <vlan>
```

Container:

```bash
sudo docker compose down -v      # -v also deletes the state volume
sudo docker rmi tc-lab:latest
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
