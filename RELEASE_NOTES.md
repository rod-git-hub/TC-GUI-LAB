# TC Lab v9.2 — Release Notes

**Released 24 September 2026**

v9.2 makes TC Lab safer to run and easier to operate. The impairment engine and
your day-to-day workflow are unchanged: the same latency, jitter, loss,
duplication, corruption and rate controls, applied the same way.

For the complete, itemised list of changes see [CHANGELOG.md](CHANGELOG.md).

---

## Highlights

- **Security fixes**, including a flaw that let a crafted config bundle write files
  as root. [Details below](#security-fixes).
- **A confined service.** TC Lab now runs with 2 of root's 40 capabilities, from a
  root-owned install, inside a sandboxed systemd unit.
- **User management in the dashboard**, with enforced `admin` / `user` roles and a
  `tc-lab` command for recovering a lost admin password.
- **A redesigned interface** — same features, a cleaner layout, dark and light themes.
- **Safer upgrades.** The installer keeps your accounts, settings and lab state,
  snapshots everything first, and can roll an upgrade back with one command.

---

## Before you upgrade

1. **Supported platform: Debian or Ubuntu, with systemd.** The installer uses `apt`
   and stops with a clear message anywhere else.
2. **There is no Docker / container option.** See [why](#not-supported-docker--containers).
3. **Hard-refresh your browser after upgrading** (Ctrl-Shift-R). A cached page from
   the old version makes every action fail with *"The CSRF token is missing."*
4. **Rolling back restores state as well as code.** Anything you change after the
   upgrade — an account, a profile, an impairment — is undone by a rollback. Export
   a config bundle first if you need to keep it.
5. **Your lab keeps running.** Bridges, VLANs and impairments live in the kernel; the
   upgrade restarts only the web service, for a few seconds.

---

## Upgrading

```bash
cd /path/to/TC-GUI-LAB && git pull && sudo bash setup.sh
```

Press **Enter** to keep your accounts when asked. Then hard-refresh your browser.

Undo it if you need to:

```bash
sudo bash setup.sh --rollback
```

The full walk-through, with verification steps, is in
[docs/upgrading.md](docs/upgrading.md).

---

## What's new

### A confined service

TC Lab has to run as root, because `tc`, `ip` and `bridge` need it. It no longer
has to run as *unrestricted* root:

| | v9.1 | v9.2 |
|---|---|---|
| Capabilities held | all 40 | 2 — `CAP_NET_ADMIN`, `CAP_NET_RAW` |
| Can load kernel modules | yes | no (the kernel loads what `ip`/`tc` need itself) |
| Install directory | owned by whoever cloned the repo | owned by root, not writable by others |
| systemd sandboxing | none | `ProtectSystem`, `NoNewPrivileges`, `PrivateTmp`, … |

Check it on your host:

```bash
grep CapEff /proc/$(systemctl show tc_lab -p MainPID --value)/status
```

`0000000000003000` means exactly those two capabilities.

This narrows what a compromised service could do; it is not a hard boundary. The
process still runs as UID 0, so keep TC Lab on an isolated lab network.

### Users and roles

- An admin-only **Users** section in the dashboard: create accounts, reset
  passwords, change roles, delete accounts.
- **Roles are enforced by the server**, not just hidden in the page. `admin`
  manages interfaces, bridges, VLANs, settings and accounts; `user` changes
  impairments, profiles and labels.
- Safety rails: you cannot delete yourself, remove your own admin role, or remove
  the last admin.
- Passwords: 8 characters minimum, 72 bytes maximum, stored only as bcrypt hashes.
  Nothing — not the dashboard, not the CLI — can display a password.

Existing accounts are all `admin`, so nothing changes until you create `user`
accounts. See [docs/users-and-security.md](docs/users-and-security.md).

### The `tc-lab` command

```bash
tc-lab --help
```

| Command | What it does |
|---|---|
| `sudo tc-lab reset-admin-password` | Set a new admin password when it has been lost |
| `sudo tc-lab list-users` | List accounts and roles (`--json` for scripts) |
| `tc-lab --version` | Show the installed version |

### The interface

- A top bar and left sidebar replace the row of tabs.
- Dark and light themes.
- A consistent icon set, bundled with the app — nothing is fetched from the internet.
- Impairment fields show their units (ms, %, mbit).
- The top-bar counts no longer double-count bridges: interfaces and bridges now
  add up to the devices on the host.

### Installation and upgrades

- **Safe to re-run.** `setup.sh` keeps your accounts (it asks first), `config.json`,
  TLS certificate, saved impairments, topology, labels and profiles.
- **Snapshots and rollback.** Each upgrade saves the whole install to
  `/var/backups/tc-lab` first; the five most recent are kept.

  | Command | Purpose |
  |---|---|
  | `sudo bash setup.sh --list-backups` | show available snapshots |
  | `sudo bash setup.sh --rollback` | restore the most recent one |
  | `sudo bash setup.sh --rollback NAME` | restore a specific one |

- **Clean upgrades.** Files that are no longer part of TC Lab are removed; your own
  profiles are kept.
- **Configurable port** — `port` in `config.json`, alongside `bind_address`.
- Configuration, TLS certificates and installer options are documented in
  [docs/deployment.md](docs/deployment.md#4-configuration).

### Fixes

- VLANs that were bridge members *and* had names without a dot (such as `wan1`)
  were silently left out of config exports, so they were not restored.
- Bridges created by other software on the host (`docker0`, libvirt, LXC, Podman)
  were saved into TC Lab's topology and recreated on restore. They are now ignored.
- The installer's certificate-generation step did nothing.
- The dashboard's start-up could stop part-way through.
- The Reload buttons could replace their own icon with text.

---

## Security fixes

| Issue | What could happen | Fixed by |
|---|---|---|
| Config import | A crafted config bundle could write files anywhere as root | Every name in a bundle is validated; a bad bundle is rejected whole |
| Stored XSS | A malicious profile name could run script in an admin's browser | All names and kernel output are escaped before display |
| Argument injection | A name starting with `-` could be read as an `ip`/`tc` option | Names can no longer start with `-` or `.` |
| Open redirect | A login link could send you to another site after signing in | Only same-site paths are accepted, including browser URL quirks |
| CSRF | Another site could trigger actions in a signed-in session | Tokens on every change, plus a strict Referer check |
| Brute force | Unlimited password guessing | 5 login attempts per minute |
| Install ownership | The user who cloned the repo could modify code that runs as root | The install is owned by root |
| Over-privilege | The service held every root capability | Bounded to 2 capabilities; sandboxed unit |

Also: secure, `HttpOnly`, `SameSite=Strict` cookies; security headers and a
Content-Security-Policy; request-size limits; the account file is readable only by
root; error pages no longer leak internal details.

The security model and the limitations that remain are described in
[SECURITY.md](SECURITY.md).

---

## Not supported: Docker / containers

TC Lab installs and runs as a systemd service only. A container build was tried
during v9.2 development and deliberately not released:

- **Nothing to isolate.** TC Lab changes the host's real network interfaces, so a
  container must share the host network (`--network host`) and gets no network
  isolation.
- **The benefit is already here.** A container's main protection is dropping root's
  capabilities. The systemd unit now does that itself, down to the same two.
- **Docker changes the host networking TC Lab depends on.** Installing it loads
  `br_netfilter` and sets the iptables `FORWARD` policy to `DROP`, which can silently
  stop traffic crossing the bridges TC Lab manages.

If Docker is already on your host for other reasons, TC Lab ignores its bridges.
The README explains [how to check](README.md#-docker--containers) whether bridged
traffic is being filtered.

Non-Debian installers are also not provided. The app itself only needs Python and
iproute2, and [docs/deployment.md](docs/deployment.md) describes running it by hand.

---

## Compatibility

- **Data carries over unchanged.** Accounts, `config.json`, saved impairments,
  topology, labels and profiles from v9.x work as-is.
- **Config bundles** exported from v9.1 import into v9.2, provided their names are
  valid. A name that starts with `-` or `.`, is longer than 20 characters, or
  contains anything other than letters, digits, `.`, `_` and `-` is now rejected,
  and the whole bundle is refused.
- **New dependencies** (`flask-wtf`, `flask-limiter`) are installed by `setup.sh`.

---

## Known limitations

Unchanged from before, and documented in [SECURITY.md](SECURITY.md):

- It runs as root (now confined — see above). Use it on an isolated lab network
  only, and never expose port 5000 to the internet.
- The built-in web server suits a single operator on a trusted network.
- The certificate is self-signed. You can
  [install your own](docs/deployment.md#tls-certificate).
- Login rate-limit counters reset when the service restarts.

---

## How this release was tested

- **128 automated tests**, covering the security fixes, account rules, the CLI,
  VLAN detection and bridge handling.
- **Production soak** on a live lab host carrying real traffic: twelve days on the
  pre-confinement build (including a host reboot for OS patching), then nearly
  three days on the build that followed it with no restarts and no warnings.
- **The confined service**, validated on that host:
  - every privileged operation TC Lab performs, run under exactly the two
    capabilities (29/29), including the kernel loading modules on its own;
  - 31 end-to-end checks through the running web service — impairments, rate
    limiting, VLANs, bridges, the per-member split, export and import, accounts
    and certificates — each confirmed in the kernel, not just in the app's reply;
  - **a cold reboot**: the service came back confined, rebuilt every VLAN and
    bridge from scratch, re-applied every impairment, and left all state files
    byte-for-byte unchanged.
