"""auth.py v9 — local JSON user store, bcrypt hashing, admin-managed accounts.

No database, no external identity provider. Accounts live in users.json; the
plaintext password is never stored or recoverable, only replaced. Account
management is admin-only (see the /api/users routes in app.py); emergency
admin recovery is the `tc-lab reset-admin-password` CLI in cli.py.
"""
import json,logging,os,secrets
from functools import wraps
from pathlib import Path
from urllib.parse import urlparse
from flask import Blueprint,request,redirect,url_for,render_template,flash,jsonify
from flask_login import (LoginManager,UserMixin,login_user,logout_user,login_required,current_user)
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import bcrypt
_SD=Path(os.environ.get("TC_LAB_STATE_DIR","."))
_SD.mkdir(parents=True,exist_ok=True)
USERS_FILE=_SD/"users.json"; SECRET_FILE=_SD/"secret_key.txt"
logger=logging.getLogger(__name__)
login_manager=LoginManager()
login_manager.login_view="auth.login"
login_manager.login_message=""
limiter=Limiter(key_func=get_remote_address, default_limits=[], storage_uri="memory://")
# Fixed-cost hash so a login attempt takes the same time whether or not the
# username exists (defeats user enumeration by timing).
_DUMMY_HASH=bcrypt.hashpw(b"x",bcrypt.gensalt(rounds=12)).decode()

def _safe_next(target):
    """Only allow same-host relative redirects after login (no open redirect).

    urlparse follows RFC 3986, but browsers follow the WHATWG URL rules: they
    read "\\" as "/" and strip tab/CR/LF before parsing. So "/\\evil.example"
    and "/<TAB>/evil.example" both reach the browser as "//evil.example" -- a
    different host -- while urlparse reports an innocent relative path. Reject
    those characters outright rather than trying to normalise them.
    """
    if not target or not isinstance(target,str): return None
    if any(c=="\\" or ord(c)<0x20 or ord(c)==0x7f for c in target): return None
    if not target.startswith("/") or target.startswith("//"): return None
    u=urlparse(target)
    return target if (not u.scheme and not u.netloc) else None
class User(UserMixin):
    def __init__(self,username,role="user"): self.id=username; self.role=role
def _load_users():
    try: return json.loads(USERS_FILE.read_text()) if USERS_FILE.exists() else {}
    except: return {}
def _save_users(u):
    USERS_FILE.write_text(json.dumps(u,indent=2))
    try: USERS_FILE.chmod(0o600)          # bcrypt hashes — not world-readable
    except OSError: pass
def get_or_create_secret():
    if SECRET_FILE.exists(): return SECRET_FILE.read_text().strip()
    key=secrets.token_hex(32); SECRET_FILE.write_text(key); SECRET_FILE.chmod(0o600); return key
def ensure_default_user():
    users=_load_users()
    if not users:
        users["admin"]={"hash":hash_password("tclab123"),"role":"admin"}; _save_users(users)
        logger.warning("="*58)
        logger.warning("  FIRST RUN -- admin / tclab123 -- change after login!")
        logger.warning("="*58)

# ── Password policy & hashing ──────────────────────────────────────────────
# One definition, used by the dashboard, the self-service change form and the
# recovery CLI, so the rule can never drift between them.
MIN_PASSWORD_LEN=8
MAX_PASSWORD_BYTES=72        # bcrypt silently truncates beyond 72 bytes

def validate_password(pw):
    """Return an error message, or None if the password is acceptable."""
    if not isinstance(pw,str) or not pw:
        return "Password is required"
    if len(pw)<MIN_PASSWORD_LEN:
        return f"Password must be at least {MIN_PASSWORD_LEN} characters"
    if len(pw.encode("utf-8"))>MAX_PASSWORD_BYTES:
        return f"Password must be at most {MAX_PASSWORD_BYTES} bytes"
    return None

def hash_password(pw):
    """bcrypt, cost 12, unique per-password salt. One-way — never reversible."""
    return bcrypt.hashpw(pw.encode("utf-8"),bcrypt.gensalt(rounds=12)).decode()

def check_password(pw,stored_hash):
    try: return bcrypt.checkpw(pw.encode("utf-8"),stored_hash.encode())
    except (ValueError,AttributeError): return False

VALID_ROLES=("admin","user")

# ── Account store operations ───────────────────────────────────────────────
# Every function here returns (ok, message). They never return or log a hash.

def list_users():
    """Accounts without any secret material — safe to send to the dashboard."""
    return [{"username":n,"role":r.get("role","user")}
            for n,r in sorted(_load_users().items())]

def count_admins(users=None):
    u=users if users is not None else _load_users()
    return sum(1 for r in u.values() if r.get("role")=="admin")

def create_user(username,password,role="user"):
    users=_load_users()
    if username in users: return False,f"User {username!r} already exists"
    if role not in VALID_ROLES: return False,"Invalid role"
    err=validate_password(password)
    if err: return False,err
    users[username]={"hash":hash_password(password),"role":role}
    _save_users(users)
    logger.info("User created: %s (role=%s)",username,role)
    return True,f"User {username!r} created"

def delete_user(username,acting_user=None):
    users=_load_users()
    if username not in users: return False,f"No such user: {username!r}"
    if acting_user and username==acting_user: return False,"You cannot delete your own account"
    if users[username].get("role")=="admin" and count_admins(users)<=1:
        return False,"Cannot delete the last admin account"
    del users[username]; _save_users(users)
    logger.info("User deleted: %s",username)
    return True,f"User {username!r} deleted"

def set_password(username,password):
    users=_load_users()
    if username not in users: return False,f"No such user: {username!r}"
    err=validate_password(password)
    if err: return False,err
    users[username]["hash"]=hash_password(password)
    _save_users(users)
    logger.info("Password reset for user: %s",username)
    return True,f"Password updated for {username!r}"

def set_role(username,role,acting_user=None):
    users=_load_users()
    if username not in users: return False,f"No such user: {username!r}"
    if role not in VALID_ROLES: return False,"Invalid role"
    if (users[username].get("role")=="admin" and role!="admin"
            and count_admins(users)<=1):
        return False,"Cannot remove the last admin account"
    if acting_user and username==acting_user and role!="admin":
        return False,"You cannot remove your own admin role"
    users[username]["role"]=role; _save_users(users)
    logger.info("Role changed: %s -> %s",username,role)
    return True,f"{username!r} is now {role}"
def admin_required(f):
    @wraps(f)
    def d(*a,**kw):
        if not current_user.is_authenticated or current_user.role!="admin":
            return jsonify({"ok":False,"error":"Admin required"}),403
        return f(*a,**kw)
    return d

def role_required(*roles):
    """Allow the route only for the listed roles (e.g. @role_required("admin","user"))."""
    def wrap(f):
        @wraps(f)
        def d(*a,**kw):
            if not current_user.is_authenticated or current_user.role not in roles:
                return jsonify({"ok":False,"error":"Insufficient role"}),403
            return f(*a,**kw)
        return d
    return wrap
@login_manager.user_loader
def load_user(username):
    u=_load_users()
    if username in u: return User(username,u[username].get("role","user"))
    return None
auth_bp=Blueprint("auth",__name__)
@auth_bp.route("/login",methods=["GET","POST"])
@limiter.limit("5 per minute",methods=["POST"])
def login():
    if request.method=="POST":
        username=request.form.get("username","").strip()
        password=request.form.get("password","")
        users=_load_users()
        rec=users.get(username)
        hash_to_check=rec["hash"] if rec else _DUMMY_HASH
        if check_password(password,hash_to_check) and rec:
            login_user(User(username,rec.get("role","user")),
                       remember=bool(request.form.get("remember")))
            return redirect(_safe_next(request.args.get("next")) or url_for("index"))
        flash("Invalid username or password")
    return render_template("login.html")
@auth_bp.route("/logout")
@login_required
def logout():
    logout_user(); return redirect(url_for("auth.login"))
@auth_bp.route("/api/auth/change-password",methods=["POST"])
@login_required
@limiter.limit("10 per minute")
def change_password():
    data=request.get_json(silent=True) or {}
    cur=data.get("current",""); new_pw=data.get("new","")
    err=validate_password(new_pw)
    if err: return jsonify({"ok":False,"error":err})
    users=_load_users(); username=current_user.id
    rec=users.get(username)
    if not rec or not check_password(cur,rec["hash"]):
        return jsonify({"ok":False,"error":"Current password incorrect"})
    if check_password(new_pw,rec["hash"]):
        return jsonify({"ok":False,"error":"New password must differ from current"})
    users[username]["hash"]=hash_password(new_pw)
    _save_users(users)
    logger.info("Password changed by user: %s",username)
    return jsonify({"ok":True})
@auth_bp.route("/api/auth/whoami")
@login_required
def whoami():
    return jsonify({"username":current_user.id,"role":current_user.role})
