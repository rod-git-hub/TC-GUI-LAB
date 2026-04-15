# Security Policy

## Intended Use

TC Lab is a **lab tool** designed for isolated network testing environments.
It is **not hardened for production or internet-facing deployment**.

## Supported Versions

| Version | Supported |
|---|---|
| v8.x (latest) | ✅ |
| older | ❌ |

## Known Limitations

| Risk | Severity | Notes |
|---|---|---|
| Runs as root | High | Required for tc/ip commands. Limit network access. |
| Flask dev server | Medium | Not suitable for production. Use Gunicorn + Nginx for hardening. |
| No CSRF tokens | Medium | Mitigated by TLS. Avoid using on untrusted networks. |
| No login rate limiting | Medium | Add Flask-Limiter for shared environments. |
| Self-signed TLS | Low | Encrypts traffic; provides no identity verification. |

## Recommended Deployment

- Run on a **dedicated lab VM** or isolated management network
- Firewall port 5000 to your admin workstation IP only
- Change the default `admin / tclab123` password immediately on first run
- Do not expose to the internet under any circumstances

## Reporting a Vulnerability

Open a GitHub Issue marked **[SECURITY]**.
Please do not disclose vulnerabilities publicly until a fix is available.
