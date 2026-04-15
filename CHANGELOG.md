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
