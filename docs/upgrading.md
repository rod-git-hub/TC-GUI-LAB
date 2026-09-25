# Upgrading TC Lab

For an existing v9.x install, to the latest release (**v9.2.1**). It takes a couple
of minutes, almost all of it package and Python dependency checks while the old
version keeps running. The service restarts once, at the end; the web UI is
unavailable for a few seconds.

> **Your impairments keep running during the upgrade.** Bridges, VLANs and `tc`
> rules live in the kernel, not in the app — restarting the service does not
> remove them.

---

## Coming from v9.2?

Upgrade to v9.2.1 the same way ([step 2](#2-upgrade)). It is a small hardening
release — stricter name checks and a quieter error message — with no configuration
or data changes, so everything below about what changes does not apply to you.
The [release notes](../RELEASE_NOTES.md) list the details.

## What changes from v9.1

v9.2 is a security, UI and account-management release. The impairment engine and
the workflow are unchanged.

- **Hardened:** CSRF tokens, `Secure`/`SameSite` cookies, security headers, login
  rate limiting, an open-redirect fix, and a fix for a config-import flaw that
  allowed writing files as root. See [SECURITY.md](../SECURITY.md).
- **Confined:** the service now runs with **2 of root's 40 capabilities**
  (`CAP_NET_ADMIN`, `CAP_NET_RAW`) and a root-owned install directory. Nothing
  you do in the UI changes; see [How the service is confined](../README.md#-how-the-service-is-confined).
- **Rebuilt UI** — same features, modern look, light/dark themes.
- **New:** admin-only user management in the dashboard, and the `tc-lab`
  command (`sudo tc-lab reset-admin-password`, `tc-lab --help`).
- **New:** roles are enforced. Existing accounts are all `admin`, so nothing
  changes until you create `user` accounts.
- **New:** `setup.sh` snapshots the install before every upgrade and can roll one
  back (`--rollback`). Files that are no longer shipped are removed on upgrade;
  your state and your own profiles are kept.
- **systemd only.** There is no container image — see
  [why Docker is not offered](../README.md#-docker--containers).

New Python dependencies (`flask-wtf`, `flask-limiter`) are installed for you.

---

## 1. Before you start (optional)

`setup.sh` takes a full snapshot of the install — code **and** state — before it
changes anything, so no manual backup is needed.

It is still worth recording what your lab looks like now, so you can confirm
afterwards that nothing moved:

```bash
tc qdisc show | tee /tmp/before-tc.txt
```

```bash
bridge link | tee /tmp/before-bridges.txt
```

A config bundle exported from the running UI (Profiles → **Export Config**) is a
second, portable restore point.

---

## 2. Upgrade

```bash
cd /path/to/TC-GUI-LAB && git pull && sudo bash setup.sh
```

`setup.sh` detects the existing install and **preserves your accounts, TLS
certificate, `config.json`, saved impairments, topology, labels and profiles**. It
refreshes the code, the virtualenv and the systemd unit.

It asks one question:

```
  Found an existing account store with 2 account(s):
    /opt/tc_lab/users.json

    [K] Keep them   — everyone signs in with their current password (default)
    [R] Reset them  — delete all accounts; a fresh admin/tclab123 is created

  Keep existing accounts? [K/r]
```

Press **Enter** to keep them. (Reset writes a timestamped backup first.)

For an unattended run, skip the prompt:

```bash
sudo bash setup.sh --keep-users
```

Look for these two lines in the output:

```
[*] Snapshot saved: /var/backups/tc-lab/tc_lab-YYYYMMDD-HHMMSS.tgz
 Undo this upgrade:         sudo bash setup.sh --rollback
```

---

## 3. Verify

```bash
systemctl status tc_lab --no-pager
```

```bash
journalctl -u tc_lab -n 40 --no-pager
```

The log should show `restore_network.sh` reporting your bridges and VLANs as
"already exists — brought up", then a `tc restored:` line for each impaired
interface.

Compare against what you recorded in step 1:

```bash
diff <(tc qdisc show) /tmp/before-tc.txt
```

```bash
diff <(bridge link) /tmp/before-bridges.txt
```

> `tc qdisc show` will differ in one harmless way: each netem qdisc gets a new
> random `seed`. That only affects jitter/loss randomisation — a fixed delay is
> identical. Everything else should match.

Confirm the version and the confinement:

```bash
tc-lab --version
```

```bash
grep CapEff /proc/$(systemctl show tc_lab -p MainPID --value)/status
```

`CapEff: 0000000000003000` means the service holds exactly `CAP_NET_ADMIN` and
`CAP_NET_RAW`.

Then open the UI and check the TC Emulation, Interfaces/VLANs and Bridge Manager
sections show what they did before.

### Two things that surprise people

1. **Hard-refresh your browser** (Ctrl-Shift-R) after upgrading. A cached older
   page holds a stale CSRF token, and every action fails with
   *"The CSRF token is missing."* A refresh fixes it.
2. **The UI looks completely different.** Same features, same workflow — the
   navigation moved from a row of tabs to a sidebar on the left.

---

## 4. After it settles

- **Change the admin password** if you never did (Settings → Change Password).
- **Create `user` accounts** for day-to-day operators (Users → Create Account).
  A `user` can change impairments and profiles but cannot alter bridges, VLANs
  or accounts. See [users-and-security.md](users-and-security.md).
- **Restrict the UI to your management interface** — set `bind_address` in
  `/opt/tc_lab/config.json` and restart. See [Configuration](deployment.md#4-configuration).

The five most recent snapshots are kept automatically in `/var/backups/tc-lab`;
older ones are pruned. There is nothing to clean up by hand.

---

## Rolling back

```bash
sudo bash setup.sh --rollback
```

This restores the most recent snapshot and restarts the service. To pick a
specific one:

```bash
sudo bash setup.sh --list-backups
```

```bash
sudo bash setup.sh --rollback tc_lab-YYYYMMDD-HHMMSS.tgz
```

> ⚠️ **A rollback restores state as well as code.** Accounts, `config.json`,
> saved impairments, topology, labels and profiles all go back to how they were
> when the snapshot was taken. Anything you changed *after* the upgrade — a new
> account, a new profile, a changed impairment — is undone. Export a config
> bundle first if you want to keep those changes.

The restore is staged and checked before anything is overwritten, so a damaged
snapshot changes nothing. Your virtualenv is kept, and the systemd unit from the
snapshot is reinstalled — rolling back to v9.1 installs the unit file that shipped
with v9.1, unconfined as before.

If bridges or VLANs were somehow lost, rebuild them from the saved topology:

```bash
cd /opt/tc_lab && sudo venv/bin/python restore_helper.py
```

…or import the config bundle you exported in step 1.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| Every action says *"The CSRF token is missing"* | Hard-refresh the browser (Ctrl-Shift-R) |
| Service won't start | `journalctl -u tc_lab -n 50` — usually invalid `config.json` or the port is taken |
| One operation fails with *"Operation not permitted"* | Unexpected — the confined service has been validated against every operation it performs. Note the exact action, check `journalctl -u tc_lab -n 50`, and `sudo bash setup.sh --rollback` if you are blocked |
| Can't sign in after choosing "reset accounts" | Use `admin` / `tclab123`, then change it |
| Lost the admin password | `sudo tc-lab reset-admin-password` |
| Bridges/VLANs missing after a reboot | Check `/opt/tc_lab/restore_network.log` |
| `setup.sh` says it requires apt | TC Lab's installer supports Debian and Ubuntu only |
