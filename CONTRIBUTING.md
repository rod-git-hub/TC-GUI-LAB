# Contributing to TC Lab

Thanks for helping. This page covers how to work on TC Lab, test it, and prepare a
release.

## The one rule: nothing site-specific

**This repository is public.** Never commit anything that describes a real network:

- IP addresses, hostnames, domain names
- real interface, VLAN or bridge names, or VLAN ids from a live lab
- account files, passwords, certificates or keys (`users.json`, `secret_key.txt`,
  `cert.pem`, `key.pem`) or runtime state (`state.json`, `network_config.json`,
  `labels.json`, `config.json`) — these are already in `.gitignore`

Use generic examples in code, tests and docs: `eth0`, `eth1.100`, `br-wan1`, and the
documentation address range `192.0.2.0/24`. **Never paste output from a real machine
into a test fixture** — rewrite it with generic names first.

Deleting something in a later commit does not remove it: it stays in the history. If
something slips through, say so before the branch is merged so the history can be
cleaned.

## Getting set up

```bash
git clone https://github.com/rod-git-hub/TC-GUI-LAB.git && cd TC-GUI-LAB
```

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements-dev.txt
```

## Running the tests

```bash
.venv/bin/python -m pytest -q
```

**Run the tests as an ordinary user, never as root.** They need no lab network.
Most system calls are replaced with stand-ins, but a few permission tests go all the
way to a real `ip` or `tc` call, which fails harmlessly without root — and as root
would really change the machine (one would create a bridge named `br0`).

Add a test with any change to validation, authentication, permissions or the
installer — and check that it **fails** without your fix.

## Working on the dashboard

The UI can be rendered with demo data and no backend:

```bash
python3 tools/ui-preview.py            # or: python3 tools/ui-preview.py user
```

```bash
python3 -m http.server 8777
```

Then open `http://localhost:8777/_preview.html`. Passing `user` shows what a
non-admin sees.

After any visible change, regenerate the screenshots in `docs/img/`:

```bash
python3 tools/capture-screenshots.py
```

It needs Chromium (or Chrome), and Pillow to keep the images small.

## How the code is laid out

- `app.py` is the whole web layer. Every route validates its input, calls one
  function in a manager, and returns its result as JSON.
- The managers — `tc_manager.py`, `bridge_manager.py`, `vlan_manager.py` — are the
  only code that touches the system, and they only ever call `subprocess.run()` with
  an argument list, never through a shell.
- **Validation lives in one place**, `app.py`: `vname()` / `_name_ok()` for names,
  `vconfig()` for impairment values, `_sanitize_bundle()` for imported files.
  `restore_helper.py` keeps a copy of the name rule for boot time, and a test checks
  that the two agree — change both or neither.
- **Accounts** change only through the helpers in `auth.py`, which the dashboard and
  the `tc-lab` command share, so their rules cannot drift apart.

## Releasing a version

1. **Bump the version** in all four places: `app.py` (first line), the `"version"`
   in `api_export()`, and the `<title>` and `brand-ver` badge in
   `templates/index.html`. `tc-lab --version` follows `app.py` automatically.
2. **Update `CHANGELOG.md`** (detailed, in Security / Added / Changed / Fixed /
   Removed order) and **`RELEASE_NOTES.md`** (the plain-language summary).
3. **Regenerate the screenshots** if anything visible changed.
4. **Run the tests.**
5. **Open a pull request into `main`.** `main` is protected against force-pushes and
   deletion; changes arrive through pull requests only.
6. After merging, **tag** the merge commit (`git tag -a vX.Y.Z`), push the tag, and
   publish a GitHub Release from it.

Commits are easiest to keep private with your GitHub *noreply* address
(Settings → Emails → "Keep my email addresses private").

## Reporting a security problem

Please do not open a public issue. See [SECURITY.md](SECURITY.md#reporting-a-vulnerability).
