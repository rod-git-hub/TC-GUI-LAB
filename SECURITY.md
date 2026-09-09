# Security Policy

## Intended Use

TC Lab is a **lab tool** for isolated network testing environments. It is **not hardened
for internet-facing deployment** and by design manipulates the host's live network stack.

## Supported Versions

| Version | Supported |
|---|---|
| v9.2 (latest) | ✅ |
| v9.0 – v9.1    | ⚠️ upgrade recommended (pre-hardening) |
| older          | ❌ |

## What v9.2 addresses

| Area | Before | Now |
|---|---|---|
| Config import | Profile names used as file paths unchecked → arbitrary file write as root | Whole bundle validated (`_sanitize_bundle`); rejected on any bad name / id |
| Stored XSS | Names rendered into the DOM unescaped | `esc()` on all kernel/user strings; imported names validated |
| Argument injection | A name could start with `-` and be read as an `ip`/`tc` flag | First char must be alphanumeric, re-checked in `restore_helper.py` |
| CSRF | No tokens | Flask-WTF `CSRFProtect`; SPA sends `X-CSRFToken` |
| Cookies | Defaults (no `Secure`/`SameSite`) | `Secure` + `HttpOnly` + `SameSite=Strict`, 12 h lifetime |
| Login | No brute-force protection, timing oracle, open redirect | `5/min` limit, constant-time compare, same-host redirects only |
| Headers | None | `X-Frame-Options`, `nosniff`, `Referrer-Policy`, HSTS, CSP |
| Error handling | 500 returned the exception string | Generic message; detail in the log only |
| Deployment | Unconfined systemd root only | Sandboxed unit **or** container with `NET_ADMIN`/`NET_RAW` only, read-only rootfs |
| User management | Hand-edit `users.json` | Admin-only dashboard section; `tc-lab reset-admin-password` for recovery; `users.json` is `0600` |

## Remaining limitations

| Risk | Severity | Notes |
|---|---|---|
| Runs as root | High | Required for `tc`/`ip`/`bridge`. Use the container to bound it to `NET_ADMIN`/`NET_RAW`. |
| Built-in WSGI server | Low–Med | Werkzeug's server (threaded). Fine for a single-operator lab on a trusted network; not for many concurrent users. |
| Self-signed TLS | Low | Encrypts traffic; no identity verification. Import `cert.pem` as a trusted CA, or drop in your own cert/key. |
| Single-process rate-limit / session store | Low | In-memory; counters reset on restart. Adequate for one instance. |
| CSP allows `'unsafe-inline'` | Low | The SPA relies on inline scripts/handlers; CSP still blocks external script/resource loads and framing. |

## Recommended Deployment

- Run the **container** (`docker compose up`) or the **sandboxed systemd unit**.
- Set `bind_address` in `config.json` to your management IP; firewall port 5000 to admin
  workstations only.
- Change the default `admin / tclab123` password on first login.
- Give day-to-day operators the **`user`** role; keep **`admin`** for topology and
  account changes. Create accounts from the dashboard's Users section.
- Passwords can only ever be *reset*, never displayed — including by the CLI.
- Do not expose to the internet under any circumstances.

## Reporting a Vulnerability

Open a GitHub Issue marked **[SECURITY]**. Please do not disclose publicly until a fix is
available.
