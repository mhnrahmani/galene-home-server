import hashlib
import hmac
import ipaddress
import os
import re
import secrets
import time
from datetime import timedelta, timezone
from functools import wraps

import bcrypt
from flask import (Flask, abort, flash, redirect, render_template, request,
                   session, url_for)

import galene
from galene import CommandError

MODE = os.environ.get("ADMIN_GUI_MODE", "lan")
if MODE not in ("lan", "internet"):
    raise SystemExit(f"ADMIN_GUI_MODE must be 'lan' or 'internet', not {MODE!r}.")
# lan: HTTP, no login, private client addresses only.
# internet: HTTPS and login with the Galene admin account.
EXPOSED = MODE == "internet"

# LAN mode: client networks allowed in, comma-separated.
DEFAULT_SUBNETS = "10.0.0.0/8,172.16.0.0/12,192.168.0.0/16,fc00::/7,fe80::/10"


def parse_subnets(value):
    try:
        return [ipaddress.ip_network(n.strip(), strict=False)
                for n in value.split(",") if n.strip()]
    except ValueError as e:
        raise SystemExit(f"Invalid ADMIN_GUI_SUBNETS: {e}")


def docker_gateway():
    """The container's default gateway: connections from the server itself
    (e.g. through an SSH tunnel) come from this address."""
    try:
        with open("/proc/net/route") as f:
            for line in f.readlines()[1:]:
                fields = line.split()
                if fields[1] == "00000000":
                    return ipaddress.ip_address(
                        bytes.fromhex(fields[2])[::-1])
    except (OSError, IndexError, ValueError):
        pass
    return None


SUBNETS = parse_subnets(os.environ.get("ADMIN_GUI_SUBNETS") or DEFAULT_SUBNETS)
GATEWAY = docker_gateway()

# Extra host names (comma-separated) accepted in LAN mode, besides IP
# addresses and local names.
LAN_HOSTS = {h.strip().lower()
             for h in os.environ.get("ADMIN_GUI_HOSTS", "").split(",")
             if h.strip()}
LOCAL_SUFFIXES = (".local", ".lan", ".home", ".home.arpa", ".internal")

# Optional secret path prefix: the GUI is only served under it, and every
# other path returns 404.  Not a replacement for the login; it keeps
# scanners away from the login form.
PREFIX = "/" + os.environ.get("ADMIN_GUI_PATH", "").strip().strip("/")
if PREFIX == "/":
    PREFIX = ""
elif not re.fullmatch(r"(/[A-Za-z0-9._~-]+)+", PREFIX):
    raise SystemExit("ADMIN_GUI_PATH may only contain letters, digits, "
                     "'.', '_', '~', '-' and '/'.")

app = Flask(__name__)
app.secret_key = secrets.token_bytes(32)   # sessions end on restart
app.config.update(
    SESSION_COOKIE_PATH=PREFIX or "/",
    SESSION_COOKIE_SAMESITE="Strict",
    SESSION_COOKIE_SECURE=EXPOSED,
    PERMANENT_SESSION_LIFETIME=timedelta(hours=12),
)

# Login throttling: at most MAX_FAILURES failed attempts per address in
# FAILURE_WINDOW seconds.
MAX_FAILURES = 5
FAILURE_WINDOW = 300
failures = {}


# Security checks

def allowed_client(addr):
    """Whether a client address is in ADMIN_GUI_SUBNETS, or the server
    itself."""
    try:
        ip = ipaddress.ip_address(addr)
    except ValueError:
        return False
    if ip.is_loopback or ip == GATEWAY:
        return True
    return any(ip in net for net in SUBNETS)


def local_host(host):
    """Whether a Host header names this server on the LAN.  Rejects
    public domain names, so that a web page can't reach the GUI through
    DNS rebinding."""
    host = host.lower()
    if host.startswith("["):
        host = host[1:host.find("]")]
    else:
        host = host.rsplit(":", 1)[0]
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        pass
    return ("." not in host or host.endswith(LOCAL_SUFFIXES)
            or host in LAN_HOSTS)


@app.before_request
def check_request():
    if not EXPOSED:
        # LAN mode has no login: only answer clients on the allowed
        # networks, and only under local host names.
        if not allowed_client(request.remote_addr) or \
                not local_host(request.host):
            abort(403)
    if request.method == "POST":
        token = session.get("csrf")
        if not token or not hmac.compare_digest(
                token, request.form.get("csrf", "")):
            abort(400, "Invalid form token, reload the page and try again.")


@app.context_processor
def template_globals():
    if "csrf" not in session:
        session["csrf"] = secrets.token_urlsafe(32)
    return {
        "csrf": session["csrf"],
        "exposed": EXPOSED,
        "user": session.get("user"),
        "server": galene.status(),
        "base_url": galene.base_url(),
    }


@app.after_request
def headers(resp):
    resp.headers["X-Frame-Options"] = "DENY"
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["Referrer-Policy"] = "no-referrer"
    resp.headers["Cache-Control"] = "no-store"
    # Keep the GUI out of search engines.
    resp.headers["X-Robots-Tag"] = "noindex, nofollow, noarchive"
    return resp


@app.get("/robots.txt")
def robots():
    return "User-agent: *\nDisallow: /\n", {"Content-Type": "text/plain"}


@app.template_filter("dt")
def format_time(t):
    return t.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")


def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if EXPOSED and not session.get("user"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return wrapper


def check_password(entry, password):
    """Checks a password against a Galene password entry."""
    if isinstance(entry, str):
        return hmac.compare_digest(entry.encode(), password.encode())
    if not isinstance(entry, dict):
        return False
    kind, key = entry.get("type"), entry.get("key")
    if kind == "bcrypt" and key:
        return bcrypt.checkpw(password.encode(), key.encode())
    if kind == "pbkdf2" and key and entry.get("hash") == "sha-256":
        expected = bytes.fromhex(key)
        got = hashlib.pbkdf2_hmac("sha256", password.encode(),
                                  bytes.fromhex(entry.get("salt", "")),
                                  entry.get("iterations", 0), len(expected))
        return hmac.compare_digest(expected, got)
    if kind == "plain" and key is not None:
        return hmac.compare_digest(key.encode(), password.encode())
    return False


@app.route("/login", methods=["GET", "POST"])
def login():
    if not EXPOSED:
        return redirect(url_for("index"))
    if request.method == "POST":
        addr = request.remote_addr
        now = time.monotonic()
        recent = [t for t in failures.get(addr, []) if now - t < FAILURE_WINDOW]
        if len(recent) >= MAX_FAILURES:
            flash("Too many failed attempts. Try again in a few minutes.",
                  "error")
            return render_template("login.html"), 429
        username = request.form.get("username", "")
        entry = galene.admin_password(username)
        if entry is not None and check_password(
                entry, request.form.get("password", "")):
            failures.pop(addr, None)
            session.clear()
            session.permanent = True
            session["user"] = username
            return redirect(url_for("index"))
        failures[addr] = recent + [now]
        flash("Wrong user name or password.", "error")
    return render_template("login.html")


@app.post("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# Helpers

def run(*args, json_input=None):
    """Runs a gctl command and flashes the outcome.  Returns stdout or None."""
    try:
        display, out = galene.gctl(*args, json_input=json_input)
    except CommandError as e:
        flash(f"{e.command}\n{e.message}", "error")
        return None
    except OSError as e:
        flash(f"Could not run docker: {e}", "error")
        return None
    flash(display, "ok")
    return out


def back_to_group(name):
    return redirect(url_for("group", name=name))


def get_group(name):
    desc = galene.group(name)
    if desc is None:
        abort(404)
    return desc


# Groups

@app.get("/")
@login_required
def index():
    groups = []
    for name in galene.group_names():
        desc = galene.group(name) or {}
        groups.append({
            "name": name,
            "displayName": desc.get("displayName", ""),
            "public": desc.get("public", False),
            "users": len(desc.get("users") or {}),
            "wildcard": "wildcard-user" in desc,
        })
    return render_template("index.html", groups=groups)


@app.post("/groups")
@login_required
def create_group():
    name = request.form.get("name", "").strip()
    if not galene.GROUP_NAME_RE.match(name):
        flash("Invalid group name. Use letters, digits, '.', '_' and '-'.",
              "error")
        return redirect(url_for("index"))
    if run("create-group", "-group", name) is None:
        return redirect(url_for("index"))
    return back_to_group(name)


@app.get("/groups/<path:name>")
@login_required
def group(name):
    desc = get_group(name)
    users = {u: galene.describe_user(d)
             for u, d in sorted((desc.get("users") or {}).items())}
    wildcard = desc.get("wildcard-user")
    return render_template(
        "group.html", name=name, desc=desc, users=users,
        wildcard=galene.describe_user(wildcard) if wildcard else None,
        tokens=galene.tokens(name), permissions=galene.PERMISSIONS,
    )


@app.post("/groups/<path:name>/delete")
@login_required
def delete_group(name):
    get_group(name)
    if run("delete-group", "-group", name) is None:
        return back_to_group(name)
    return redirect(url_for("index"))


TEXT_SETTINGS = ["displayName", "description", "contact", "comment"]
BOOL_SETTINGS = ["public", "allow-recording", "unrestricted-tokens",
                 "auto-subgroups", "autolock", "autokick"]
INT_SETTINGS = ["max-clients", "max-history-age"]


@app.post("/groups/<path:name>/settings")
@login_required
def group_settings(name):
    get_group(name)
    # null removes a key, so that unset options fall back to their defaults.
    data = {}
    for k in TEXT_SETTINGS:
        data[k] = request.form.get(k, "").strip() or None
    for k in BOOL_SETTINGS:
        data[k] = True if request.form.get(k) else None
    for k in INT_SETTINGS:
        v = request.form.get(k, "").strip()
        if v and not v.isdigit():
            flash(f"{k} must be a whole number.", "error")
            return back_to_group(name)
        data[k] = int(v) if v and int(v) > 0 else None
    run("update-group", "-group", name, "-json", json_input=data)
    return back_to_group(name)


# Users

def user_args(form):
    """-user NAME or -wildcard, from the form."""
    if form.get("wildcard"):
        return ["-wildcard"]
    user = form.get("user", "").strip()
    if not galene.USER_NAME_RE.match(user):
        return None
    return ["-user", user]


def permission(form):
    p = form.get("permissions", "present")
    return p if p in galene.PERMISSIONS else None


@app.post("/groups/<path:name>/users")
@login_required
def create_user(name):
    get_group(name)
    who = user_args(request.form)
    perms = permission(request.form)
    if who is None or perms is None:
        flash("Invalid user name or permissions.", "error")
        return back_to_group(name)
    if run("create-user", "-group", name, *who, "-permissions", perms) is None:
        return back_to_group(name)
    if not request.form.get("password") and \
            not request.form.get("any-password"):
        flash("No password set yet: nobody can log in as this user.", "error")
    set_password(name, who)
    return back_to_group(name)


def set_password(name, who):
    password = request.form.get("password", "")
    if request.form.get("any-password"):
        run("set-password", "-group", name, *who, "-type", "wildcard")
    elif password:
        run("set-password", "-group", name, *who, "-password", password)


@app.post("/groups/<path:name>/users/update")
@login_required
def update_user(name):
    get_group(name)
    who = user_args(request.form)
    if who is None:
        abort(400)
    if "permissions" in request.form:
        perms = permission(request.form)
        if perms is None:
            abort(400)
        run("update-user", "-group", name, *who, "-permissions", perms)
    else:
        if not request.form.get("password") and \
                not request.form.get("any-password"):
            flash("Enter a password.", "error")
        set_password(name, who)
    return back_to_group(name)


@app.post("/groups/<path:name>/users/delete")
@login_required
def delete_user(name):
    get_group(name)
    who = user_args(request.form)
    if who is None:
        abort(400)
    run("delete-user", "-group", name, *who)
    return back_to_group(name)


# Invite links

@app.post("/groups/<path:name>/tokens")
@login_required
def create_token(name):
    get_group(name)
    duration = request.form.get("duration", "24h").strip()
    perms = permission(request.form)
    user = request.form.get("user", "").strip()
    if not galene.DURATION_RE.match(duration) or perms is None:
        flash("Invalid duration or permissions.", "error")
        return back_to_group(name)
    args = ["create-token", "-group", name, "-duration", duration,
            "-permissions", perms]
    if user:
        if not galene.USER_NAME_RE.match(user):
            flash("Invalid user name.", "error")
            return back_to_group(name)
        args += ["-user", user]
    token = run(*args)
    base = galene.base_url()
    if token and base:
        flash(f"Invite link: {base}/group/{name}/?token={token}", "ok")
    return back_to_group(name)


@app.post("/groups/<path:name>/tokens/<action>")
@login_required
def token_action(name, action):
    get_group(name)
    if action not in ("revoke", "delete"):
        abort(404)
    token = request.form.get("token", "")
    if not token.replace("-", "").replace("_", "").isalnum():
        abort(400)
    run(f"{action}-token", "-group", name, "-token", token)
    return back_to_group(name)


# Server

@app.get("/server")
@login_required
def server():
    return render_template("server.html", logs=galene.logs())


@app.post("/server/<action>")
@login_required
def server_control(action):
    if action not in ("start", "stop", "restart"):
        abort(404)
    try:
        flash(galene.control(action), "ok")
    except CommandError as e:
        flash(f"{e.command}\n{e.message}", "error")
    return redirect(url_for("server"))


# Path prefix

ROBOTS_HEADERS = [("X-Robots-Tag", "noindex, nofollow, noarchive"),
                  ("Cache-Control", "no-store")]


def application(environ, start_response):
    """The WSGI entry point: serves the app under PREFIX only."""
    if not PREFIX:
        return app(environ, start_response)
    path = environ.get("PATH_INFO", "")
    if path.startswith(PREFIX + "/"):
        environ["SCRIPT_NAME"] = environ.get("SCRIPT_NAME", "") + PREFIX
        environ["PATH_INFO"] = path[len(PREFIX):]
        return app(environ, start_response)
    if path == PREFIX:
        start_response("301 Moved Permanently",
                       [("Location", PREFIX + "/")] + ROBOTS_HEADERS)
        return [b""]
    if path == "/robots.txt":
        start_response("200 OK",
                       [("Content-Type", "text/plain")] + ROBOTS_HEADERS)
        return [b"User-agent: *\nDisallow: /\n"]
    start_response("404 Not Found",
                   [("Content-Type", "text/plain")] + ROBOTS_HEADERS)
    return [b"Not Found\n"]
