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
| Self-service password change | ✅ supported |
| Session cookies: `Secure`, `HttpOnly`, `SameSite=Strict` | ✅ supported |
| CSRF protection on every state-changing request | ✅ supported |
| Login rate limiting (5/min) | ✅ supported |
| Idle session timeout | ✅ supported |
| HTTPS with auto-generated certificate | ✅ supported |
| **Web UI to create/delete users** | ❌ edit `users.json` by hand |
| **Self-service password reset ("forgot password")** | ❌ admin intervention |
| **LDAP / Active Directory / SAML / OAuth / SSO** | ❌ requires development |
| **Multi-factor authentication** | ❌ requires development |
| **Account lockout, password complexity policy** | ❌ requires development |
| **Audit log of who changed what** | ❌ partial (see §8) |

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

### Change your own password — supported in the UI

Settings (gear icon) → **Change Password**. Requires the current password;
minimum 8 characters; the new password must differ from the old one.

### Add a user — manual, requires root

There is no user-management UI. Generate a hash and add an entry:

```bash
cd /opt/tc_lab
# 1. generate a bcrypt hash (you will be prompted; input is not echoed)
sudo venv/bin/python -c "import bcrypt,getpass; \
print(bcrypt.hashpw(getpass.getpass('New password: ').encode(), bcrypt.gensalt(12)).decode())"

# 2. add the account
sudo nano users.json          # add a "username": {"hash": "...", "role": "user"} entry
sudo chmod 600 users.json
sudo systemctl restart tc_lab
```

Roles are read fresh on every request, so a role change takes effect on the
user's next action — no restart needed for that.

### Delete a user

Remove their object from `users.json`. They are signed out on their next request.

### Reset a forgotten password

Two options, both requiring root on the host:

```bash
# A. set a new hash for that one user — follow "Add a user" above and replace
#    the existing "hash" value.

# B. nuclear: reset everything to the default admin account
sudo systemctl stop tc_lab
sudo rm /opt/tc_lab/users.json
sudo systemctl start tc_lab      # recreates admin / tclab123
```

Option B deletes **all** accounts.

> **Requires development:** a user-management page, an admin-initiated password
> reset, and a "forgot password" flow. All three are straightforward additions on
> top of the existing `auth.py` — the storage format already supports multiple
> users and roles; only the UI and routes are missing.

---

## 5. Roles and permissions

Two roles, enforced **server-side** on every request. The UI also hides controls
a role cannot use, but that is only decluttering — the server returns HTTP 403
regardless of what the browser sends.

| Action | `admin` | `user` |
|---|:---:|:---:|
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
— but cannot alter the lab's physical topology or import a configuration bundle.
Give day-to-day operators `user` and keep `admin` for whoever owns the rig.

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
| Lifetime | 12 hours |
| Idle timeout | configurable, default 30 min, with a 60-second warning |
| "Keep me signed in" | extends the session via a `remember` cookie (same flags) |

`HttpOnly` blocks JavaScript from reading the cookie; `Secure` stops it ever being
sent over plain HTTP; `SameSite=Strict` means another site cannot cause your
browser to send it. If `secret_key.txt` is deleted, all sessions are invalidated
(everyone must sign in again) — a quick way to force a global sign-out.

---

## 7. Securing the deployment

TC Lab reconfigures live networking as root. Treat access to it as equivalent to
root shell access on that host.

**Do these:**

1. **Change the default password** on first login.
2. **Bind to the management interface only.** In `config.json`:
   ```json
   { "bind_address": "192.168.10.5" }
   ```
   Otherwise the UI listens on every interface — including the lab NICs.
3. **Firewall the port** to your admin workstations:
   ```bash
   sudo apt install -y nftables
   sudo nft add rule inet filter input tcp dport 5000 ip saddr != 192.168.10.0/24 drop
   ```
   (or the equivalent `ufw`/`iptables` rule for your setup)
4. **Use the container deployment** where you can — it bounds the process to
   `CAP_NET_ADMIN` + `CAP_NET_RAW` on a read-only filesystem, instead of
   unconfined root.
5. **Give operators the `user` role**, not `admin`.
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
| Runs as root | a compromise means host control | container deployment; isolated lab network |
| Werkzeug's built-in server | not built for hostile networks | fine for a single operator on a trusted LAN; put a reverse proxy in front for anything larger |
| Self-signed certificate | encrypts, but proves no identity | import as trusted, or install a real certificate |
| No audit trail of *who* did what | applied commands are logged, but not the username | journal + `restore_network.log` give the *what*, not the *who* |
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
