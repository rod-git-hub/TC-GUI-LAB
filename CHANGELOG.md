## [v9.3] - Unreleased

The service stops running as root; the dashboard port can be changed; a bridge
shows the total of its members; and the documentation is built into the
dashboard. **The state moves** from `/opt/tc_lab` to `/var/lib/tc_lab` — the
installer does it. Upgrade notes: [docs/upgrading.md](docs/upgrading.md).

### Security
- **The service runs as its own unprivileged user, `tc-lab`, not root.** It is
  handed `CAP_NET_ADMIN` alone as an ambient capability (equal to the bounding
  set, so it can never gain more) and `ProtectSystem=strict` makes the
  whole filesystem read-only to it except `/var/lib/tc_lab`, its state directory.
  Under v9.2 it ran as UID 0 with `/var` writable, so a compromised app could
  write root-owned files there that something unconfined later runs as full root
  (for example a package's install script at the next `apt upgrade`). Added:
  `PrivateDevices`, `ProtectKernelModules`, `ProtectKernelTunables`,
  `ProtectClock`, `ProtectHostname`, `ProtectProc=invisible`, `RestrictNamespaces`,
  `RestrictAddressFamilies`, `SystemCallFilter=@system-service`,
  `SystemCallArchitectures=native`, `RemoveIPC`, `UMask=0077`.
  `systemd-analyze security`: 5.9 MEDIUM → 1.8 OK.
- **`CAP_NET_RAW` removed.** Every operation TC Lab performs was run on a live lab
  host without it; nothing needs it. The service can no longer open raw or packet
  sockets.
- **Creating a bridge no longer sets `net.ipv4.ip_forward=1`.** A bridge forwards
  at layer 2 and does not need it; it turned the whole host into a router.
- **No `modprobe` calls.** The kernel loads `8021q` and the qdisc modules itself;
  the confined service could not load modules anyway.
- The CLI hands the files it writes as root (a recreated `users.json`, its backup,
  `config.json`) back to the state directory's owner, so the service can read them.

### Added
- **Service port setting.** Settings → Service Port (admins), `setup.sh --port N`,
  and `sudo tc-lab set-port N` as the way back. 1024–65535; a port something is
  listening on is refused. Settings restarts TC Lab *in place* (the same process
  re-executes itself, keeping its capabilities) and skips the topology restore and
  `tc` re-apply, so impairments are not interrupted; the page follows to the new
  address. `ports.py` holds the rules for the app and the CLI; `setup.sh` keeps a
  copy of the range, and a test keeps them equal.
- **Bridge totals.** A bridge card shows the combined impairment of its members
  (`tc_manager.combine_member_configs`, the inverse of the split: delays add,
  loss/duplication/corruption compound, the slowest rate is the bottleneck).
  `/api/interfaces` returns `totals`; apply/reset return the new total. Member tags
  show each member's latency.
- **Help and About in the dashboard.** The README, user guide, deployment,
  upgrading, users-and-security, security policy, release notes and changelog,
  rendered from the Markdown shipped with the install (`help_docs.py`): a fixed
  list of pages, raw HTML shown as text, unsafe links dropped, links between the
  documents opened in Help at GitHub's heading anchors, images only from
  `docs/img/`. About shows the running version and links to the project. New
  dependency: `Markdown==3.11`.
- **Installer:** creates the service user; moves pre-v9.3 state out of the install
  directory (copy, `cmp`, then delete); snapshots include the state directory and
  rollback restores either layout, deciding from the restored unit; an upgrade reads
  the state directory and user back from the installed unit; new
  `TC_LAB_STATE_DIR` and `TC_LAB_USER` overrides.
- Tests: 157 → 289. `tests/test_installer.py` runs the real `setup.sh` as fake root
  in a user namespace against scratch directories (fresh install, v9.2.1 → v9.3 →
  rollback → v9.3, snapshots, `--port`, stray state); `tests/test_help.py` fails if a
  link between the documents stops landing on a real heading.
- The reference topology diagram is now in the repository (`docs/img/00-topology.png`),
  so Help can show it offline. Screenshots of Help and About.

### Changed
- **State lives in `/var/lib/tc_lab`** (owned by `tc-lab`, mode 700); the code in
  `/opt/tc_lab` is owned by root and read-only to the service.
- **A bridge has at most two members** — one for each side of the lab path. A third
  is refused by the API and in imported bundles; Bridge Manager hides **+** at two.
- A bridge's own value is no longer stored in `state.json`; the members are the only
  record. Entries left by v9.2 are dropped at start-up and on import.
- Shipped profiles are added to the state directory only when missing, so your edits
  to one survive upgrades (they used to be overwritten).
- A `config.json` port below 1024 falls back to 5000 with a warning; the installer
  flags it.
- The version is written once, in `app.py`'s first line; the page, the export and
  About read it from there.
- `tc-lab` finds the state directory through the installed unit.
- Start-up warns when `CAP_NET_ADMIN` is missing, instead of when not running as root.

### Fixed
- The page redraws every 20 seconds and silently threw away impairment values typed
  but not yet applied — on a bridge card it looked as if Apply did nothing. Cards
  being edited keep their values until Apply or Reset.
- Snapshots were labelled `.v9.2.1` in `--list-backups` (the dot of "app.py").
- The deployment guide's "run it in the foreground" instructions would, from v9.3,
  have created a second, root-owned set of state files in `/opt/tc_lab`. Replaced
  with `journalctl -f`; the installer now also recognises such stray files and
  leaves the real state alone.

## [v9.2.1] - 2026-09-25

A small hardening release from a post-release review of v9.2. No data or
configuration changes. One deliberate behaviour change: "Keep me signed in" now
lasts 7 days.

### Security
- **Name validation rejects non-ASCII characters.** `_name_ok()` (and its copy in
  `restore_helper.py`) checked the charset against `s.lower()`, and `str.lower()`
  maps some non-ASCII characters onto ASCII letters — U+212A KELVIN SIGN becomes
  `k`. Such a name passed validation while the original, non-ASCII name was the one
  used, allowing look-alike interface, bridge or profile names. It could not be used
  for path traversal (no `/`) or option injection (no leading `-`). Uppercase ASCII
  remains accepted. A test now keeps the two validators in agreement.
- **Config import no longer echoes an exception's text** when the request body
  cannot be read; it returns `Invalid JSON` and logs the detail server-side.
- **"Keep me signed in" now lasts 7 days**, not 365. TC Lab never set its own limit,
  so Flask-Login's default of a year applied; the 12-hour figure in the v9.2 docs
  only ever described sessions without the box ticked. A test reads the real
  `Set-Cookie` header. The limit is the cookie's expiry date, which the browser
  enforces: cookies issued before the upgrade keep their original expiry, and the
  cookie value itself has no server-side expiry. To end every existing sign-in,
  delete `secret_key.txt` and restart — this signs everyone out.

### Added — documentation
- **`docs/user-guide.md`** — the whole dashboard, page by page, with screenshots:
  impairments and the bridge split, VLANs, bridges, profiles, export/import, users,
  settings, and a table of what each role can do.
- **`CONTRIBUTING.md`** — setup, tests (never as root), UI preview and screenshots,
  how the code is laid out, the release checklist, and the rule that nothing
  site-specific is ever committed.
- `docs/README.md`, an index of the documentation.
- Screenshots: eleven views (up from six), adding Profiles, Settings, Member
  controls, live statistics, and the Bridge Manager as a non-admin `user` sees it.
  `capture-screenshots.py` can now render any shot as either role.

### Fixed — documentation
- The included-profiles table left out values in every row — `good_link` is not a
  zero baseline (5 ms, 1 ms jitter), and most profiles also cap the rate. Rebuilt
  from the profile files.
- `SECURITY.md` asked for vulnerabilities to be reported in a public issue. It now
  points to GitHub's private vulnerability reporting.
- Name rules were described as "starting with a letter or digit"; the actual rule is
  "not starting with `-` or `.`", and names must be ASCII.

### Changed
- The config export timestamps use timezone-aware UTC (`datetime.now(timezone.utc)`)
  instead of `datetime.utcnow()`, which Python 3.12+ deprecates. The file name and
  the `exported` field are unchanged; a test now pins both formats.
- **pytest 8.3.5 → 9.1.1** (`requirements-dev.txt`) for CVE-2025-71176 /
  GHSA-6w46-j5rx-g56g (unsafe temporary-directory handling, fixed in 9.0.3).
  Test tooling only: `setup.sh` installs `requirements.txt`, so no installed
  system was ever affected. All tests pass on 9.1.1.

## [v9.2] - 2026-09-24

A security, confinement, UI and account-management release. The impairment engine
and the day-to-day workflow are unchanged. Deployment is **systemd only, on Debian
or Ubuntu** — see *Removed*. Upgrade notes: [docs/upgrading.md](docs/upgrading.md).

### Security
- **Arbitrary file write as root, via config import — fixed** (`_sanitize_bundle`).
  Profile names in an imported bundle were used as file paths unchecked, so a crafted
  "lab config" could write attacker-controlled JSON anywhere root could reach. Every
  name and id in a bundle is now validated before anything is written or replayed,
  and the whole bundle is rejected on any violation. Rejected values echoed back in
  the error message are truncated.
- **Stored XSS — fixed.** Profile names and every kernel-supplied string are
  HTML-escaped (`esc()`) before entering the DOM.
- **Argument injection — fixed.** A name can no longer start with `-` or `.`, so it can
  never be read as a flag by `ip`/`tc`. `restore_helper.py` re-checks every name.
- **Open redirect after login — fixed** (`_safe_next`). Only same-host paths are
  accepted, and backslashes and control characters are rejected outright: browsers
  follow the WHATWG URL rules, reading `\` as `/` and stripping tab/CR/LF, so
  `/\evil.example` would otherwise reach the browser as `//evil.example`.
- **CSRF protection** (Flask-WTF) on every state-changing request. The dashboard sends
  `X-CSRFToken`; the login form carries a hidden token and a strict Referer check.
- **Cookies** are `Secure` + `HttpOnly` + `SameSite=Strict`; sessions last 12 hours
  (see v9.2.1 for the "Keep me signed in" limit).
  Request bodies are capped at 512 KB.
- **Security headers** on every response: `X-Frame-Options: DENY`, `nosniff`,
  `Referrer-Policy`, HSTS and a Content-Security-Policy.
- **Login brute-force protection:** `5/min` on `/login`, `10/min` on change-password.
  Login timing is the same whether or not the username exists.
- **Capability confinement.** The unit sets
  `CapabilityBoundingSet=CAP_NET_ADMIN CAP_NET_RAW`: the service used to hold all
  **40** of root's capabilities and uses two. `CAP_SYS_MODULE` is excluded on purpose
  — it permits loading kernel code — and is not needed: when `ip` or `tc` asks for a
  module that is not loaded (`8021q`, `sch_htb`, …) the kernel loads it itself. This
  narrows a compromise rather than preventing one: the service still runs as UID 0.
- **Root-owned install.** `setup.sh` now chowns `/opt/tc_lab` to root and removes
  group/other write. `rsync -a` run as root preserves the checkout's owner, so
  `git clone && sudo bash setup.sh` used to leave root-executed code writable by the
  unprivileged user who cloned it.
- **Sandboxed unit:** `ProtectSystem=full`, `ProtectHome`, `NoNewPrivileges`,
  `PrivateTmp`, `MemoryDenyWriteExecute`, `RestrictSUIDSGID` and more.
- `users.json` is written mode `0600` (bcrypt hashes were world-readable).
- 500 responses no longer leak the exception text to the client.

### Added
- **User management in the dashboard** (admin only): create accounts, reset any
  password, change roles, delete accounts. Every `/api/users*` route is
  `@admin_required`, and responses never contain password hashes. Guard rails: you
  cannot delete your own account, drop your own admin role, or delete/demote the last
  admin. Account changes are logged with the username.
- **Roles enforced end to end.** `admin` manages interfaces, bridges, VLANs, settings,
  import and accounts; `user` changes impairments, profiles and labels. The server
  returns 403 regardless of what the page shows.
- **`tc-lab` command**, linked to `/usr/local/bin` by `setup.sh`:
  `sudo tc-lab reset-admin-password` (root only; prompts twice without echo, applies
  the dashboard's password rules, backs up the store, changes only `admin` —
  recreating it if deleted — and verifies before reporting success),
  `tc-lab list-users [--json]`, `tc-lab --help` and `tc-lab --version`. No command
  can display a password.
- **One password policy** shared by the dashboard, the self-service form and the CLI:
  8 characters minimum, 72 bytes maximum (bcrypt silently truncates beyond 72).
- **Installer snapshots and rollback.** Every upgrade snapshots the whole install —
  code *and* state — to `/var/backups/tc-lab` (five kept). `--list-backups` and
  `--rollback [NAME]` undo an upgrade; restores are staged and checked before
  anything is overwritten.
- `config.json` `port` setting (default `5000`).
- `TC_LAB_STATE_DIR` — relocate all writable state (default: the working directory).
- `TC_LAB_SKIP_RESTORE=1` — start a second instance without touching the host's
  topology or `tc` rules.
- Installer overrides: `TC_LAB_DIR`, `TC_LAB_UNIT_DIR`, `TC_LAB_BACKUP_DIR`,
  `TC_LAB_KEEP_BACKUPS`, `TC_LAB_SERVICE`, `TC_LAB_BIN_DIR`.
- Documentation: `docs/deployment.md`, `docs/upgrading.md`,
  `docs/users-and-security.md` and `RELEASE_NOTES.md`.
- A test suite (`tests/`, 128 cases) and pinned dependencies
  (`requirements.txt`, `requirements-dev.txt`).

### Changed
- **The UI is redesigned** — same features, same workflow. A top bar and left
  sidebar replace the tab strip; dark and light themes; an inline SVG icon set
  replaces emoji (no external assets, works offline); impairment fields show their
  units. The top-bar counts are now disjoint: interfaces (NICs and VLAN
  sub-interfaces) and bridges, which sum to the device count.
- **`setup.sh` is safe to re-run over a live install.** It asks before touching
  accounts (keeps them by default; `--keep-users` / `--reset-users` for unattended
  runs), never overwrites `config.json`, the TLS certificate or saved state, and
  installs the tracked `tc_lab.service` — the old inline unit had silently dropped
  both the sandboxing and the boot-time topology restore.
- **Upgrades remove files that are no longer shipped** (`rsync --delete`). State and
  user-created profiles are protected; stale `__pycache__` is cleared.
- The installer requires `apt` (Debian/Ubuntu) and says so plainly elsewhere, and
  works under `sudo -E` (it restores `/usr/sbin` to `PATH` for `ip`/`tc`/`bridge`).
- `config.json` is no longer shipped in the repository; `setup.sh` writes a default
  on first install and the app works without one.
- `capture-screenshots.py` re-encodes captures with an adaptive palette, keeping
  `docs/img` small across regenerations.

### Fixed
- **VLANs could vanish from exports.** `ip -j` omits `linkinfo` for a VLAN that is a
  bridge member, and the name-parse fallback only works for dotted names — so a
  VLAN that was both a bridge member and non-dotted (e.g. `wan1`) was silently
  dropped from every export and restore. Now falls back to the kernel's registry,
  `/proc/net/vlan/config`. Latent since v9.1.
- **Other software's bridges are no longer captured.** `docker0`, Docker's
  `br-<hex>` networks, `virbr*`, `lxcbr*` and `podman*` were saved into the topology,
  exported, and recreated on restore. They are now skipped; the UI still lists them.
- The installer's certificate step did nothing (`ssl_gen.py` had no `__main__`
  entry point).
- `loadAll()` referenced an out-of-scope variable and aborted the dashboard's start-up
  sequence part-way.
- The Reload buttons on the Interfaces and Bridge Manager sections could replace
  their own icon with text.

### Removed
- **Container deployment.** A Docker build was prototyped during this cycle and
  dropped before release. It needed `--network host`, so it offered no network
  isolation; its security benefit — dropping capabilities — the systemd unit now
  provides itself; and installing Docker loads `br_netfilter` and sets the iptables
  `FORWARD` policy to `DROP`, which can silently stop traffic across the bridges this
  tool manages. It was never part of a release.
- `bridge_setup.sh`, an unused helper superseded by the Bridge Manager.

## [v9.1] - 2026-05-14

### Fixed
- **Bridge/VLAN actions now update instantly** — Create, Delete, Add Member, Remove Member,
  Up/Down all call targeted `_refreshBr()` / `_refreshVl()` instead of full `loadAll()`.
  No more need to hit Reload after every change.
- **Reload buttons were swapped** — VLAN tab called `reloadBridges()` and Bridge tab called
  `reloadVlans()`. Fixed to correct handlers.
- **VLAN ID saved as `"?"` causing restore failure** — `ip -j` sometimes omits `info_data.id`
  when interface is a bridge member. Now falls back to parsing ID from interface name
  (e.g. `ens224.111` → `111`). `restore_helper.py` has same fallback.
- **`restore_network.sh` null bytes error** — removed broken heredoc that tried to run
  the venv Python binary as a script. Replaced with dedicated `restore_helper.py`.
- **`restore_via_script()` used relative paths** — failed when CWD was not `/opt/tc_lab`
  (e.g. systemd ExecStartPre). Now uses `Path(__file__).parent.resolve()` for absolute paths.
## [v9.0] - 2026-05-14

### Changed
- Installer (`setup.sh`) now deploys to `/opt/tc_lab` and registers as a systemd service (`tc_lab.service`) automatically
- Added `rsync` to apt dependencies to fix silent installer failure under `set -euo pipefail`
- Service file written with explicit `echo` lines — no heredoc variable expansion issues
- README updated: Quick Start reflects `/opt/tc_lab` install path and service management commands
- All version references bumped from v8 to v9

### Fixed
- `setup.sh` was failing silently before systemd steps due to missing `rsync`
- Reload button on Bridge Manager tab not refreshing — now calls `renderBrTab()` explicitly after `loadAll()`
- Reload button on Interfaces / VLANs tab had malformed async call — fixed to properly `await loadVlanTab()` + `loadAll()`
- `_init()` was defined but never called — default `users.json` was never created, making login impossible on fresh install

## [v8.6] - 2026-05-14

### Added
- **Export / Import Lab Config** (Profiles tab → Export / Import card)
  - **Export**: Downloads a single `tc_lab_config_YYYYMMDD_HHMMSS.json` bundle
    containing network topology, TC impairments, interface labels, and all profiles
  - **Import**: Upload a bundle JSON — network is recreated immediately via
    `restore_network.sh`, TC rules are re-applied, labels and profiles restored.
    Requires admin role.
  - Useful for cloning lab setups across multiple hosts or saving/restoring
    configurations between lab scenarios

## [v8.5] - 2026-05-14

### Changed
- **Persistence redesigned** — replaced fragile Python restore logic with
  `restore_network.sh`, a dedicated shell script that reads `network_config.json`
  and re-creates interfaces in the correct order: VLANs → bridges → members.
  The script runs as `ExecStartPre` in systemd BEFORE the app starts, and is
  also called by the app on startup. Output logged to `restore_network.log`.

### Fixed
- **Bridge members (sub-interfaces) not restored after reboot** — root cause was
  ordering: Python was creating bridges before VLANs existed. Shell script now
  creates VLANs first, then bridges, then assigns members.
- **↻ Reload button in Bridge Manager and VLANs tabs not working** — both tab
  Reload buttons were re-rendering from stale in-memory data. Now they call
  `loadAll()` (full server re-fetch + cache-bust) before re-rendering.

## [v8.4] - 2026-05-14

### Fixed
- **Bridge members missing after reboot** — restore order was wrong: bridges
  were created before VLANs, but members are often VLAN sub-interfaces that
  don't exist yet. New order: VLANs first → bridges → members (with 3-attempt
  retry + 1s sleep between attempts)
- **Refresh button not updating UI** — `api()` GET calls now include
  `cache:'no-store'` and a `?_=timestamp` cache-bust param so the browser
  never returns stale interface data
- **Refresh only re-rendered active tab** — `loadAll()` now always re-renders
  TC Emulation, Bridge Manager, and VLANs tabs regardless of which is active
- **No feedback on Refresh click** — button now shows "↻ …" and disables
  while loading, then restores to "↻ Refresh" when done

## [v8.3] - 2026-05-14

### Fixed
- **TC rules not re-applied after reboot** — `_init()` was loading `state.json`
  into memory but never pushing the rules back to the Linux kernel. Added
  `_reapply_tc()` which calls `apply_netem()` for every saved interface rule
  after `restore_net_config()` runs.
- **Systemd `network-online.target` unreliable** — switched to `network.target`
  (always available) plus `ExecStartPre=/bin/sleep 5` so physical NICs finish
  coming up before the app tries to restore bridges on top of them.

## [v8.2] - 2026-05-13

### Added
- **Network config persistence across reboots** (`network_config.json`)
  - Bridges, bridge members, and VLAN sub-interfaces are now saved on every change
  - On startup, `restore_net_config()` re-creates all bridges, members, and VLANs
    before scanning for live tc state — so tc rules are also re-applied correctly
- Systemd service now declares `After=network-online.target` so physical NICs
  are available before the app tries to restore bridges

### Changed
- `app.py`: `_init()` calls `restore_net_config()` before `detect_all_tc_configs()`
- `app.py`: all bridge create/delete/member and VLAN create/delete routes call
  `save_net_config()` after successful operations

# Changelog

All notable changes to TC Lab are documented here.

## [v8.0] - 2026-03-24

### Added
- Bridge member controls in a slide-out drawer (side panel)
- Bridge groups displayed 2-per-row in TC Emulation tab
- Collapsible member chip summary on bridge cards
- Light/Dark theme toggle with persistent preference

### Fixed
- Theme toggle label showed "Light / Light" in light mode
- TC active badge in header counted bridge template entries (double-count)
- TC active badge not refreshing after Apply / Reset (only updated on page load)
- VLAN parent dropdown showed bridges and sub-interfaces as valid parents
- Bridge panel background colour inconsistency in light theme

### Changed
- `vlan_manager.py`: `list_physical_interfaces()` now filters bridges via sysfs
  and VLAN sub-interfaces by name and `info_kind`
- `index.html`: extracted `updateLiveBadge()` as a standalone function
