"""auth.py v7"""
import json,logging,secrets
from functools import wraps
from pathlib import Path
from flask import Blueprint,request,redirect,url_for,render_template,flash,jsonify
from flask_login import (LoginManager,UserMixin,login_user,logout_user,login_required,current_user)
import bcrypt
USERS_FILE=Path("users.json"); SECRET_FILE=Path("secret_key.txt")
logger=logging.getLogger(__name__)
login_manager=LoginManager()
login_manager.login_view="auth.login"
login_manager.login_message=""
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
@login_manager.user_loader
def load_user(username):
    u=_load_users()
    if username in u: return User(username,u[username].get("role","user"))
    return None
auth_bp=Blueprint("auth",__name__)
@auth_bp.route("/login",methods=["GET","POST"])
def login():
    if request.method=="POST":
        username=request.form.get("username","").strip()
        password=request.form.get("password","").encode()
        users=_load_users()
        if username in users and bcrypt.checkpw(password,users[username]["hash"].encode()):
            login_user(User(username,users[username].get("role","user")),
                       remember=bool(request.form.get("remember")))
            return redirect(request.args.get("next") or url_for("index"))
        flash("Invalid username or password")
    return render_template("login.html")
@auth_bp.route("/logout")
@login_required
def logout():
    logout_user(); return redirect(url_for("auth.login"))
@auth_bp.route("/api/auth/change-password",methods=["POST"])
@login_required
def change_password():
    data=request.get_json(force=True) or {}
    cur=data.get("current","").encode(); new_pw=data.get("new","").encode()
    if len(new_pw)<8: return jsonify({"ok":False,"error":"Min 8 characters"})
    users=_load_users(); username=current_user.id
    if not bcrypt.checkpw(cur,users[username]["hash"].encode()):
        return jsonify({"ok":False,"error":"Current password incorrect"})
    users[username]["hash"]=bcrypt.hashpw(new_pw,bcrypt.gensalt(rounds=12)).decode()
    _save_users(users); return jsonify({"ok":True})
@auth_bp.route("/api/auth/whoami")
@login_required
def whoami():
    return jsonify({"username":current_user.id,"role":current_user.role})
