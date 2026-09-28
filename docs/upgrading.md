# Upgrading TC Lab

For an existing v9.x install, to the latest release (**v9.3**). It takes a couple
of minutes, almost all of it package and Python dependency checks while the old
version keeps running. The service restarts once, at the end; the web UI is
unavailable for a few seconds.

> **Your impairments keep running during the upgrade.** Bridges, VLANs and `tc`
> rules live in the kernel, not in the app — restarting the service does not
> remove them.

---

## Coming from v9.2 or v9.2.1?

Upgrade the same way ([step 2](#2-upgrade)). What is different afterwards:

- **TC Lab no longer runs as root.** The service runs as its own system user,
  `tc-lab`, with only the two network capabilities it needs, and can write only
  its state directory. See [SECURITY.md](../SECURITY.md).
- **Its state moves** from `/opt/tc_lab` to **`/var/lib/tc_lab`**: accounts,
  `config.json`, certificate, saved impairments, topology, labels and profiles.
  The installer does this for you — it copies every file, checks each copy, and
  only then removes the originals (after taking a snapshot). Nothing to
  do by hand; just use the new paths from now on, for example
  `/var/lib/tc_lab/config.json`.
- **A bridge shows the total of its members.** Apply on a bridge still splits the
  value equally across its two members; set members one by one and the bridge
  shows their sum. A bridge whose members were set by hand may show a different
  number than before — the new one is the real total.
- **A bridge has at most two members** — one for each side of the lab path.
- **The port can be changed** from Settings, with `setup.sh --port`, or with
  `sudo tc-lab set-port`. See [Configuration](deployment.md#changing-the-port).
- **Help** in the sidebar has this documentation, and **About** shows the version.
- **Creating a bridge no longer turns on IP forwarding** (`net.ipv4.ip_forward`)
  for the whole host. Bridges do not need it. If you also route traffic through
  this host, set it yourself (`/etc/sysctl.d/`); a value already set stays until
  the next reboot.
- **Your edits to a shipped profile survive upgrades** (they used to be
  overwritten). A shipped profile you deleted still comes back.
- **Ports below 1024** (such as 443) cannot be used any more — the service is not
  root. If `config.json` asks for one, TC Lab uses 5000 and the installer says so.

One new Python dependency (`Markdown`) is installed for you. The
[release notes](../RELEASE_NOTES.md) list everything.

## Coming from v9.1?

v9.2 was a security, UI and account-management release, and everything in it
applies to you too, along with the v9.3 changes above. The impairment engine and
the workflow are unchanged.

- **Hardened:** CSRF tokens, `Secure`/`SameSite` cookies, security headers, login
  rate limiting, an open-redirect fix, and a fix for a config-import flaw that
  allowed writing files as root. See [SECURITY.md](../SECURITY.md).
- **Confined:** see [How the service is confined](../README.md#-how-the-service-is-confined).
  Nothing you do in the UI changes.
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

New Python dependencies (`flask-wtf`, `flask-limiter`, `Markdown`) are installed for
you.

---

## 1. Before you start (optional)

`setup.sh` takes a full snapshot — code **and** state — before it changes
anything, so no manual backup is needed.

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

Press **Enter** to keep them. (Reset writes a timestamped backup first.) From
v9.3 on, the path shown is `/var/lib/tc_lab/users.json`.

For an unattended run, skip the prompt:

```bash
sudo bash setup.sh --keep-users
```

Look for these lines in the output — the middle two only when coming from v9.2.x
or earlier:

```
[*] Snapshot saved: /var/backups/tc-lab/tc_lab-YYYYMMDD-HHMMSS.tgz  (version v9.2.1)
[*] Moving TC Lab's state from /opt/tc_lab to /var/lib/tc_lab
[*] Moved 9 file(s) and the profiles to /var/lib/tc_lab
 Undo this upgrade:         sudo bash setup.sh --rollback
```

(The number of files depends on your install.)

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
ps -o user= -p "$(systemctl show tc_lab -p MainPID --value)"
```

```bash
grep CapEff /proc/$(systemctl show tc_lab -p MainPID --value)/status
```

Expect `tc-lab`, and `CapEff: 0000000000003000` — exactly `CAP_NET_ADMIN` and
`CAP_NET_RAW`.

Then open the UI and check the TC Emulation, Interfaces/VLANs and Bridge Manager
sections show what they did before. A bridge card now shows the total of its
members: a bridge whose members each have 10 ms shows 20 ms.

### Two things that surprise people

1. **Hard-refresh your browser** (Ctrl-Shift-R) after upgrading. A cached older
   page holds a stale CSRF token, and every action fails with
   *"The CSRF token is missing."* A refresh fixes it.
2. **Coming from v9.1, the UI looks completely different.** Same features, same
   workflow — the navigation moved from a row of tabs to a sidebar on the left.

---

## 4. After it settles

- **Change the admin password** if you never did (Settings → Change Password).
- **Create `user` accounts** for day-to-day operators (Users → Create Account).
  A `user` can change impairments and profiles but cannot alter bridges, VLANs
  or accounts. See [users-and-security.md](users-and-security.md).
- **Restrict the UI to your management interface** — set `bind_address` in
  `/var/lib/tc_lab/config.json` and restart. See [Configuration](deployment.md#4-configuration).

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
snapshot is reinstalled.

**Rolling back from v9.3 to v9.2.x** brings back v9.2's layout as well: the
service runs as root again, with its state in `/opt/tc_lab` exactly as it was
before the upgrade. `/var/lib/tc_lab` is left in place but no longer used —
delete it if you stay on v9.2. If you upgrade again later, the installer moves the
state across again and sets the old `/var/lib/tc_lab` aside as
`/var/lib/tc_lab.replaced-<date>`, which you can then delete.

If bridges or VLANs were somehow lost, rebuild them from the saved topology:

```bash
cd /opt/tc_lab && sudo TC_LAB_STATE_DIR=/var/lib/tc_lab venv/bin/python restore_helper.py
```

…or import the config bundle you exported in step 1.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| Every action says *"The CSRF token is missing"* | Hard-refresh the browser (Ctrl-Shift-R) |
| Service won't start | `journalctl -u tc_lab -n 50` — usually invalid `config.json`, the port is taken, or state files not owned by `tc-lab` |
| One operation fails with *"Operation not permitted"* | Unexpected — the confined service has been validated against every operation it performs. Note the exact action, check `journalctl -u tc_lab -n 50`, and `sudo bash setup.sh --rollback` if you are blocked |
| Settings or accounts will not save | `sudo chown -R tc-lab: /var/lib/tc_lab` |
| Can't sign in after choosing "reset accounts" | Use `admin` / `tclab123`, then change it |
| Lost the admin password | `sudo tc-lab reset-admin-password` |
| Dashboard unreachable after changing the port | `sudo tc-lab set-port 5000`, then `sudo systemctl restart tc_lab` |
| Bridges/VLANs missing after a reboot | Check `/var/lib/tc_lab/restore_network.log` |
| `setup.sh` says it requires apt | TC Lab's installer supports Debian and Ubuntu only |
