"""auth.py v8"""
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
    """Only allow same-host relative redirects after login (no open redirect)."""
    if not target: return None
    u=urlparse(target)
    return target if (not u.scheme and not u.netloc and target.startswith("/")) else None
class User(UserMixin):
    def __init__(self,username,role="user"): self.id=username; self.role=role
def _load_users():
    try: return json.loads(USERS_FILE.read_text()) if USERS_FILE.exists() else {}
    except: return {}
def _save_users(u): USERS_FILE.write_text(json.dumps(u,indent=2))
def get_or_create_secret():
    if SECRET_FILE.exists(): return SECRET_FILE.read_text().strip()
    key=secrets.token_hex(32); SECRET_FILE.write_text(key); SECRET_FILE.chmod(0o600); return key
def ensure_default_user():
    users=_load_users()
    if not users:
        pw=bcrypt.hashpw(b"tclab123",bcrypt.gensalt(rounds=12)).decode()
        users["admin"]={"hash":pw,"role":"admin"}; _save_users(users)
        logger.warning("="*58)
        logger.warning("  FIRST RUN -- admin / tclab123 -- change after login!")
        logger.warning("="*58)
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
        password=request.form.get("password","").encode()
        users=_load_users()
        rec=users.get(username)
        hash_to_check=(rec["hash"] if rec else _DUMMY_HASH).encode()
        if bcrypt.checkpw(password,hash_to_check) and rec:
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
    cur=data.get("current","").encode(); new_pw=data.get("new","").encode()
    if len(new_pw)<8: return jsonify({"ok":False,"error":"Min 8 characters"})
    users=_load_users(); username=current_user.id
    rec=users.get(username)
    if not rec or not bcrypt.checkpw(cur,rec["hash"].encode()):
        return jsonify({"ok":False,"error":"Current password incorrect"})
    if bcrypt.checkpw(new_pw,rec["hash"].encode()):
        return jsonify({"ok":False,"error":"New password must differ from current"})
    users[username]["hash"]=bcrypt.hashpw(new_pw,bcrypt.gensalt(rounds=12)).decode()
    _save_users(users); return jsonify({"ok":True})
@auth_bp.route("/api/auth/whoami")
@login_required
def whoami():
    return jsonify({"username":current_user.id,"role":current_user.role})
