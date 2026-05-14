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
