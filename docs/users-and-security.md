# Users, Authentication & Security

How TC Lab handles accounts today, and what would need building. Every section
separates **what works now** from **what requires development**, so you can plan
around it rather than discover it.

---

## 1. Summary

| Capability | Status |
|---|---|
| Local accounts, multiple users | ✅ supported |
| bcrypt password hashing (cost 12) | ✅ supported |
| Two roles: `admin`, `user`, enforced server-side | ✅ supported |
| **Admin creates / deletes accounts from the dashboard** | ✅ supported |
| **Admin resets any user's password from the dashboard** | ✅ supported |
| **CLI admin password recovery (`tc-lab reset-admin-password`)** | ✅ supported |
| Self-service password change | ✅ supported |
| Session cookies: `Secure`, `HttpOnly`, `SameSite=Strict` | ✅ supported |
| CSRF protection on every state-changing request | ✅ supported |
| Login rate limiting (5/min) | ✅ supported |
| Idle session timeout | ✅ supported |
| HTTPS with auto-generated certificate | ✅ supported |
| **Self-service password reset ("forgot my password")** | ❌ by design — ask an admin, or use the CLI |
| **LDAP / Active Directory / SAML / OAuth / SSO** | ❌ requires development |
| **Multi-factor authentication** | ❌ requires development |
| **Account lockout, password complexity policy** | ❌ requires development |
| **Audit log of who changed what** | ❌ partial (see §8) |

**The model in one line:** local JSON user store → local application accounts →
admin manages users from the dashboard → Linux CLI recovers the admin account if
its password is lost. No database, no external identity provider.

---

## 2. How accounts are stored

All accounts live in a single JSON file — `users.json` in the state directory
(`/opt/tc_lab/users.json` in a standard install):

```json
{
  "admin": {
    "hash": "$2b$12$xpeeFimMi5RJxxdaGg7ovOexZbXveSbeoTQL51y5MywzJArWz9Bwe",
    "role": "admin"
  },
  "bob": {
    "hash": "$2b$12$K8kqR2ZmR0mQ0m0Zq1u9GeM.mCr7bIeBv2Hk0hHrbz1P5S3EQ8lYS",
    "role": "user"
  }
}
```

- The JSON key is the username.
- `hash` is a bcrypt hash — **the plaintext password is never stored anywhere**.
- `role` is `admin` or `user`.
- The file is `chmod 600` (root-only) as of v9.2.

There is no database. This is deliberate: the whole tool is file-backed so a lab
can be copied, versioned, or wiped by moving files around.

### First run

If `users.json` is missing or empty when the app starts, it creates:

```
username: admin
password: tclab123
role:     admin
```

and logs a warning. **Change this password immediately** — it is public knowledge
in the README.

---

## 3. How passwords are protected

**Algorithm: bcrypt, cost factor 12** (`bcrypt.hashpw(pw, bcrypt.gensalt(rounds=12))`).

- bcrypt is a deliberately slow, salted, adaptive hash designed for passwords —
  not a general-purpose hash like SHA-256.
- Every password gets a **unique random salt**, stored inside the hash string, so
  two users with the same password produce different hashes and precomputed
  ("rainbow table") attacks do not apply.
- Cost 12 means 2¹² key-expansion rounds — roughly 250 ms per attempt on typical
  hardware, which makes brute-forcing a stolen hash file expensive.
- Verification uses `bcrypt.checkpw()`, which compares in constant time.

Hashing is **one-way**. Nobody — including you — can read an existing password
out of `users.json`; it can only be replaced.

Two related hardening details in v9.2:

- **No user enumeration.** A login attempt for a non-existent username is checked
  against a dummy hash, so failures take the same time whether or not the account
  exists.
- **Rate limiting.** 5 login attempts per minute per IP, then HTTP 429.

---

## 4. Managing users

### As an admin — dashboard → **Users**

The **Users** section appears in the sidebar for admins only. A `user` role never
sees it, and every route behind it returns HTTP 403 for them regardless of what
the browser sends.

| Task | How |
|---|---|
| **Create an account** | Users → Create Account: username, password, role |
| **Reset someone's password** | Users → the account's **Reset password** button |
| **Change someone's role** | Users → the role dropdown on their row |
| **Delete an account** | Users → the trash button on their row |

The password is set directly — an admin never needs (and can never see) the
user's existing password. Tell the person their new password over a trusted
channel; the dashboard will not show it again.

Guard rails, enforced server-side so the UI cannot be bypassed:

- You cannot delete your own account.
- You cannot remove your own admin role.
- You cannot delete or demote the **last** admin — the system can never be left
  with no way in.
- Usernames follow the same rules as every other name: 1–20 plain-ASCII
  characters — letters, digits, `.`, `_` and `-` — not starting with `-` or `.`.
  A name can therefore never be read as a path or a command flag.

Role changes take effect on the user's very next request — no restart needed.

### As any user — change your own password

Settings (gear icon) → **Change Password**. Requires your current password, a
minimum of 8 characters, and the new password must differ from the old one.

### If the admin password is lost — CLI recovery

Requires shell access and root on the host. It **resets** the admin password —
there is deliberately no command that reads or displays an existing password,
because only a one-way hash is stored.

```bash
sudo tc-lab reset-admin-password
```

It will:

1. Verify it is running as root (exit code 2 if not).
2. Prompt twice for the new password, **without echoing it**.
3. Validate it against the same policy the dashboard uses.
4. Write a backup of the account store (`users.json.bak`, mode `0600`).
5. Update **only** the `admin` account's hash — every other account, role and
   application setting is left exactly as it was.
6. Read the file back and verify the new password before reporting success.

If the `admin` account has been deleted entirely, the command recreates it with
the admin role and preserves all other accounts.

Related:

```bash
sudo tc-lab list-users        # usernames and roles — never hashes
sudo tc-lab --help
```

Under a non-standard install path, point the wrapper at it:

```bash
sudo TC_LAB_DIR=/srv/tc_lab tc-lab reset-admin-password
```

Or run the module directly:

```bash
cd /opt/tc_lab && sudo venv/bin/python cli.py reset-admin-password
```

> **Last resort** (loses every account): stop the service, delete `users.json`,
> start it again — the default `admin` / `tclab123` is recreated. Prefer the CLI.

---

## 5. Roles and permissions

Two roles, enforced **server-side** on every request. The UI also hides controls
a role cannot use, but that is only decluttering — the server returns HTTP 403
regardless of what the browser sends.

| Action | `admin` | `user` |
|---|:---:|:---:|
| **Create / delete accounts, reset others' passwords, change roles** | ✅ | ❌ |
| View interfaces, bridges, VLANs, statistics | ✅ | ✅ |
| Apply / reset impairments (`tc`) | ✅ | ✅ |
| Save, load and delete profiles | ✅ | ✅ |
| Set interface labels | ✅ | ✅ |
| Export lab config | ✅ | ✅ |
| Change own password | ✅ | ✅ |
| Create / delete **bridges**, add / remove members | ✅ | ❌ |
| Create / delete **VLANs** | ✅ | ❌ |
| Bring interfaces **up / down** | ✅ | ❌ |
| Change settings (idle timeout) | ✅ | ❌ |
| **Import** lab config | ✅ | ❌ |

The split is deliberate: `user` can run experiments — change impairments all day
— but cannot alter the lab's physical topology, import a configuration bundle, or
touch accounts. Give day-to-day operators `user` and keep `admin` for whoever
owns the rig.

Note the asymmetry on passwords: a `user` can change **their own** password (the
route reads the username from the session, never from the request body, so it
cannot be pointed at someone else's account) but only an `admin` can reset
**another** user's.

> **Requires development:** more granular authorization (e.g. per-interface
> permissions, a read-only role, or an approval workflow). The `role_required()`
> decorator in `auth.py` is the extension point.

---

## 6. Sessions

| Property | Value |
|---|---|
| Mechanism | Flask-Login, signed cookie |
| Signing key | `secret_key.txt` — 32 random bytes, `chmod 600`, generated on first run |
| Cookie flags | `Secure`, `HttpOnly`, `SameSite=Strict` |
| Session lifetime | 12 hours |
| Idle timeout | configurable, default 30 min, with a 60-second warning |
| "Keep me signed in" | a `remember` cookie (same flags) that keeps you signed in on that browser for **7 days**. Don't tick it on a shared computer. (Before v9.2.1 it lasted 365 days.) |

`HttpOnly` blocks JavaScript from reading the cookie; `Secure` stops it ever being
sent over plain HTTP; `SameSite=Strict` means another site cannot cause your
browser to send it.

The 7-day "Keep me signed in" limit is the cookie's expiry date, enforced by the
browser. The cookie's value is only signed, not timed, so a copy taken from a
browser keeps working until the signing key changes. If `secret_key.txt` is deleted, all sessions are invalidated
(everyone must sign in again) — a quick way to force a global sign-out.

---

## 7. Securing the deployment

TC Lab reconfigures live networking as root. Treat access to it as equivalent to
root shell access on that host.

**Do these:**

1. **Change the default password** on first login.
2. **Bind to the management interface only.** In `config.json`:
   ```json
   { "bind_address": "192.0.2.10" }
   ```
   (`192.0.2.x` is a documentation-only range — use your own management IP.)
   Otherwise the UI listens on every interface — including the lab NICs.
3. **Firewall the port** to your admin workstations:
   ```bash
   sudo apt install -y nftables
   sudo nft add rule inet filter input tcp dport 5000 ip saddr != 192.0.2.0/24 drop
   ```
   (or the equivalent `ufw`/`iptables` rule for your setup)
4. **Install with `setup.sh`**, which deploys the sandboxed unit: a capability
   bounding set instead of all of root's capabilities, a read-only view of the
   system outside `/opt/tc_lab`, and an install directory owned by root.
5. **Give operators the `user` role**, not `admin`. Create their accounts from
   Users → Create Account; keep the number of admins small.
6. **Trust the certificate** rather than clicking through the warning every time:
   import `cert.pem` into your browser's authority store. Or drop in a real
   cert — replace `cert.pem` / `key.pem` and restart.
7. **Keep it off the internet.** No exceptions. It is a lab tool.
8. **Back up** `users.json`, `config.json`, `network_config.json` and `profiles/`.

**Already handled for you in v9.2:** CSRF tokens, hardened session cookies,
security headers (`X-Frame-Options: DENY`, `nosniff`, CSP, HSTS), login rate
limiting, constant-time login, validated config import, HTML escaping throughout,
and a sandboxed systemd unit.

---

## 8. Known limitations

Honest accounting of what this tool does *not* do.

| Limitation | Impact | Mitigation |
|---|---|---|
| Runs as root | a compromise means host control | capability-bounded, sandboxed systemd unit; isolated lab network |
| Werkzeug's built-in server | not built for hostile networks | fine for a single operator on a trusted LAN; put a reverse proxy in front for anything larger |
| Self-signed certificate | encrypts, but proves no identity | import as trusted, or install a real certificate |
| No audit trail of *who* did what | applied commands are logged, but not the username | account changes (create/delete/role/password-reset) *are* logged with the username; impairment changes are not |
| Rate limit is per-process, in memory | counters reset when the service restarts | adequate for one instance |
| No account lockout | only per-IP rate limiting | strong passwords; restricted network access |
| No password complexity rules | 8-character minimum is the only check | policy/convention |
| CSP allows `'unsafe-inline'` | the SPA uses inline scripts and handlers | CSP still blocks external resources and framing |

---

## 9. External identity providers

**Not supported today.** There is no LDAP, Active Directory, SAML, OAuth2/OIDC,
RADIUS, TACACS+ or MFA support. Authentication is entirely local.

This is a deliberate design choice for a self-contained lab appliance with no
dependency on external infrastructure — the tool keeps working when the network
it is testing is broken.

**If you need it later**, the code is well-positioned. `auth.py` is small and
self-contained; all of authentication funnels through two functions
(`login()` and the `@login_manager.user_loader`). Realistic effort:

| Integration | Approach | Rough effort |
|---|---|---|
| LDAP / Active Directory | `python-ldap` or `ldap3`; bind against the DS in `login()`, map an LDAP group to the `admin` role, keep `users.json` as a local fallback | small — 1–2 days |
| SAML 2.0 SSO | `python3-saml`; add ACS/metadata routes, map an assertion attribute to the role | medium — 1–2 weeks |
| OAuth2 / OIDC (Entra ID, Okta, Keycloak) | `Authlib`; redirect flow, map a token claim to the role | medium — 1 week |
| TOTP MFA | `pyotp`; add a secret per user in `users.json` and a second login step | small — 2–3 days |

A sensible rule for a lab appliance: **keep at least one local admin account**
even after adding an external provider, so you can still get in when the
directory is unreachable — which, in a WAN-emulation lab, is a state you will
deliberately create.
