# Upgrading to v9.2

For an existing v9.x install. Takes about five minutes, with roughly two minutes
of web-UI downtime.

> **Your impairments keep running during the upgrade.** Bridges, VLANs and `tc`
> rules live in the kernel, not in the app — stopping the service does not remove
> them. Only the web UI is unavailable while the service restarts.

---

## What changes

v9.2 is a security, UI and account-management release. The impairment engine and
the workflow are unchanged.

- Hardened: CSRF tokens, `Secure`/`SameSite` cookies, security headers, login
  rate limiting, and a fix for a config-import flaw that allowed writing files
  as root. See [SECURITY.md](../SECURITY.md).
- Rebuilt UI — same features, modern look, light/dark themes.
- **New:** admin-only user management in the dashboard, plus a
  `sudo tc-lab reset-admin-password` recovery command.
- **New:** roles are enforced. Existing accounts are all `admin`, so nothing
  changes until you create `user` accounts.
- **New:** the service runs with a capability bounding set and a root-owned install.

New Python dependencies (`flask-wtf`, `flask-limiter`) are installed for you.

---

## 1. Back up

Cheap insurance. Takes a second.

```bash
sudo systemctl stop tc_lab
sudo cp -a /opt/tc_lab /opt/tc_lab.bak-$(date +%F)
```

Also record what your lab looks like right now, so you can confirm nothing moved:

```bash
tc qdisc show   | tee /tmp/before-tc.txt
bridge link     | tee /tmp/before-bridges.txt
```

Optionally, export a config bundle from the running v9.1 UI first
(Profiles → **Export Config**). It is a clean restore point.

---

## 2. Upgrade

```bash
cd /path/to/TC-GUI-LAB
git pull
sudo bash setup.sh
```

`setup.sh` detects the existing install and **preserves your accounts, TLS
certificate, `config.json`, saved impairments and topology**. It refreshes only
the code, the virtualenv and the systemd unit.

It asks one question:

```
  Found an existing account store with 2 account(s):
    /opt/tc_lab/users.json

    [K] Keep them   — everyone signs in with their current password (default)
    [R] Reset them  — delete all accounts; a fresh admin/tclab123 is created

  Keep existing accounts? [K/r]
```

Press **Enter** to keep them. (Reset writes a timestamped backup first, so it is
recoverable either way.)

For an unattended run, skip the prompt:

```bash
sudo bash setup.sh --keep-users
```

---

## 3. Verify

```bash
systemctl status tc_lab --no-pager
journalctl -u tc_lab -n 40 --no-pager
```

The log should show `restore_network.sh` reporting your bridges and VLANs as
"already exists — brought up", then `tc restored:` lines for each impaired
interface.

Compare against the snapshot from step 1:

```bash
diff <(tc qdisc show)  /tmp/before-tc.txt
diff <(bridge link)    /tmp/before-bridges.txt
```

> `tc qdisc show` will differ in one harmless way: each netem qdisc gets a new
> random `seed` value. That only affects jitter/loss randomisation — a fixed
> delay is identical. Everything else should match.

Then open the UI and check the TC Emulation, Interfaces/VLANs and Bridge Manager
tabs show what they did before.

### Two things that surprise people

1. **Hard-refresh your browser** (Ctrl-Shift-R) after upgrading. A cached v9.1
   page has no CSRF token, and every action fails with
   *"The CSRF token is missing."* This is the single most common post-upgrade
   report, and a refresh fixes it.

2. **The UI looks completely different.** Same tabs, same workflow — the
   navigation moved from a row of tabs at the top to a sidebar on the left.

---

## 4. After it settles

Once you are happy it is working:

```bash
sudo rm -rf /opt/tc_lab.bak-*
```

Worth doing now that you have them:

- **Change the admin password** if you never did (Settings → Change Password).
- **Create `user` accounts** for day-to-day operators (Users → Create Account).
  A `user` can change impairments and profiles but cannot alter bridges, VLANs
  or accounts. See [users-and-security.md](users-and-security.md).
- **Restrict the UI to your management interface** — set `bind_address` in
  `/opt/tc_lab/config.json` and restart.

---

## Rolling back

The kernel topology never went away, so a rollback is just code plus a restart:

```bash
sudo systemctl stop tc_lab
sudo rm -rf /opt/tc_lab
sudo mv /opt/tc_lab.bak-YYYY-MM-DD /opt/tc_lab
sudo systemctl start tc_lab
```

v9.1 used a simpler systemd unit. If you rolled back and want that exact unit
too, it is in the backup at `/opt/tc_lab.bak-*/tc_lab.service`.

If bridges or VLANs were somehow lost, rebuild them from the saved topology:

```bash
cd /opt/tc_lab && sudo venv/bin/python restore_helper.py
```

...or import the config bundle you exported in step 1.

---

## Troubleshooting

| Symptom | Fix |
|---|---|
| Every action says *"The CSRF token is missing"* | Hard-refresh the browser (Ctrl-Shift-R) |
| Service won't start | `journalctl -u tc_lab -n 50` — usually invalid `config.json` or the port is taken |
| Can't sign in after choosing "reset accounts" | Use `admin` / `tclab123`, then change it |
| Lost the admin password | `sudo tc-lab reset-admin-password` |
| Bridges/VLANs missing after a reboot | Check `/opt/tc_lab/restore_network.log` |
