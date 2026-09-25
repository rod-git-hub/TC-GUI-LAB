# Security Policy

## Intended Use

TC Lab is a **lab tool** for isolated network testing environments. It is **not hardened
for internet-facing deployment** and by design manipulates the host's live network stack.

## Supported Versions

| Version | Supported |
|---|---|
| v9.2.1 (latest) | ✅ |
| v9.2            | ✅ — upgrading to v9.2.1 is recommended |
| v9.0 – v9.1     | ⚠️ upgrade recommended (before the security hardening) |
| older           | ❌ |

## What v9.2 and v9.2.1 address

| Area | Before | Now |
|---|---|---|
| Config import | Profile names used as file paths unchecked → arbitrary file write as root | Whole bundle validated (`_sanitize_bundle`); rejected on any bad name / id |
| Stored XSS | Names rendered into the DOM unescaped | `esc()` on all kernel/user strings; imported names validated |
| Argument injection | A name could start with `-` and be read as an `ip`/`tc` flag | Names cannot start with `-` or `.`; re-checked in `restore_helper.py` |
| Look-alike names *(v9.2.1)* | Some Unicode characters passed validation because the check lower-cased first (the Kelvin sign `K` became `k`) | Names must be plain ASCII |
| CSRF | No tokens | Flask-WTF `CSRFProtect`; SPA sends `X-CSRFToken` |
| Cookies | Defaults (no `Secure`/`SameSite`); "Keep me signed in" lasted 365 days | `Secure` + `HttpOnly` + `SameSite=Strict`; 12 h sessions; "Keep me signed in" capped at 7 days *(v9.2.1)* |
| Login | No brute-force protection, timing oracle, open redirect | `5/min` limit, constant-time compare, same-host redirects only (including browser URL-parsing quirks such as `/\evil`) |
| Headers | None | `X-Frame-Options`, `nosniff`, `Referrer-Policy`, HSTS, CSP |
| Error handling | 500 returned the exception string; import echoed exception text *(fixed in v9.2.1)* | Generic messages; detail in the log only |
| Deployment | Unconfined systemd root (all 40 capabilities); install owned by the cloning user | Sandboxed unit confined to `CAP_NET_ADMIN` + `CAP_NET_RAW`; install owned by root |
| User management | Hand-edit `users.json` | Admin-only dashboard section; `tc-lab reset-admin-password` for recovery; `users.json` is `0600` |

## Remaining limitations

| Risk | Severity | Notes |
|---|---|---|
| Runs as root | High | Required for `tc`/`ip`/`bridge`. The unit bounds it to 2 capabilities (`NET_ADMIN`, `NET_RAW`) — no module loading, no `ptrace`, no permission overrides. But it still runs as UID 0, and `ProtectSystem=full` leaves `/var` writable, so it can write root-owned files there. Capability bounding narrows a compromise; it is not a hard boundary. Keep it on an isolated lab network. |
| Built-in WSGI server | Low–Med | Werkzeug's server (threaded). Fine for a single-operator lab on a trusted network; not for many concurrent users. |
| Self-signed TLS | Low | Encrypts traffic; no identity verification. Import `cert.pem` as a trusted CA, or drop in your own cert/key. |
| Single-process rate-limit / session store | Low | In-memory; counters reset on restart. Adequate for one instance. |
| "Keep me signed in" has no server-side expiry | Low | The 7-day limit is the cookie's expiry, enforced by the browser; the value is signed, not timed (Flask-Login's design). A copied cookie stays valid until the signing key changes. Leave the box unticked on shared machines; delete `secret_key.txt` and restart to sign everyone out. |
| CSP allows `'unsafe-inline'` | Low | The SPA relies on inline scripts/handlers; CSP still blocks external script/resource loads and framing. |

## Recommended Deployment

- Install with `setup.sh`, which deploys the sandboxed, capability-bounded systemd unit.
- Set `bind_address` in `config.json` to your management IP; firewall port 5000 to admin
  workstations only.
- Change the default `admin / tclab123` password on first login.
- Give day-to-day operators the **`user`** role; keep **`admin`** for topology and
  account changes. Create accounts from the dashboard's Users section.
- Passwords can only ever be *reset*, never displayed — including by the CLI.
- Do not expose to the internet under any circumstances.

## Reporting a Vulnerability

**Please report privately — do not open a public issue.** On GitHub, go to the
repository's **Security** tab and choose **Report a vulnerability**. Only the
maintainer can see the report.

Include what you found, how to reproduce it, and the version (`tc-lab --version`).
Please allow time for a fix before disclosing it publicly.

## How this project watches for problems

- **Code scanning (CodeQL)** runs on every pull request and on `main`. Each alert is
  either fixed or dismissed with a written reason.
- **Dependabot** watches the pinned dependencies in `requirements.txt` and
  `requirements-dev.txt` and opens a pull request when one needs a security update.
