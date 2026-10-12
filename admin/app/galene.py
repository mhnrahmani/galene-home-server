"""Access to the Galene container.

All changes go through galenectl (`docker exec <container> galenectl ...`),
exactly like the gctl commands in the README.  Group and token files are
only read, to display details that galenectl doesn't show (wildcard user,
whether a password is set).
"""

import json
import os
import re
import shlex
import subprocess
from datetime import datetime, timezone

CONTAINER = os.environ.get("GALENE_CONTAINER", "galene")
DATA_DIR = "/galene/data"
GROUPS_DIR = "/galene/groups"

PERMISSIONS = ["op", "present", "message", "observe"]

GROUP_NAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*(/[A-Za-z0-9][A-Za-z0-9._-]*)*$")
USER_NAME_RE = re.compile(r"^[^\s/][^/]{0,63}$")
DURATION_RE = re.compile(r"^([0-9]+(\.[0-9]+)?(h|m|s))+$")


class CommandError(Exception):
    def __init__(self, command, message):
        super().__init__(message)
        self.command = command
        self.message = message


def _display(args):
    shown = list(args)
    for i, a in enumerate(shown[:-1]):
        if a == "-password":
            shown[i + 1] = "SECRET"
    return "gctl " + shlex.join(shown).replace("SECRET", "***")


def gctl(*args, json_input=None):
    """Run galenectl in the Galene container.  Returns (display, stdout)."""
    display = _display(args)
    cmd = ["docker", "exec"]
    data = None
    if json_input is not None:
        cmd.append("-i")
        data = json.dumps(json_input)
        display += " <<< '" + data + "'"
    cmd += [CONTAINER, "galenectl", *args]
    try:
        p = subprocess.run(cmd, input=data, capture_output=True, text=True,
                           timeout=30)
    except subprocess.TimeoutExpired:
        raise CommandError(display, "Timed out.")
    if p.returncode != 0:
        # galenectl uses log.Fatalf: strip the "2006/01/02 15:04:05 " prefix.
        msg = re.sub(r"^\d{4}/\d\d/\d\d \d\d:\d\d:\d\d ", "",
                     (p.stderr or p.stdout).strip(), flags=re.M)
        if "412 Precondition Failed" in msg and args[0].startswith("create-"):
            msg += " (it already exists)"
        raise CommandError(display, msg or f"Exit status {p.returncode}.")
    return display, p.stdout.strip()


def docker(*args, timeout=60):
    p = subprocess.run(["docker", *args], capture_output=True, text=True,
                       timeout=timeout)
    if p.returncode != 0:
        raise CommandError("docker " + shlex.join(args),
                           (p.stderr or p.stdout).strip())
    return p.stdout


# Server control

def status():
    """Returns a dict with 'state' (running, exited, ..., or missing)."""
    try:
        out = docker("inspect", "-f",
                     "{{.State.Status}} {{.State.StartedAt}}", CONTAINER,
                     timeout=10)
    except CommandError:
        return {"state": "missing", "started": None}
    except (OSError, subprocess.TimeoutExpired) as e:
        return {"state": "unknown", "started": None, "error": str(e)}
    state, started = out.strip().split(" ", 1)
    return {"state": state, "started": _parse_time(started)}


def control(action):
    assert action in ("start", "stop", "restart")
    docker(action, CONTAINER)
    return "docker " + action + " " + CONTAINER


def logs(lines=300):
    p = subprocess.run(["docker", "logs", "--tail", str(lines), CONTAINER],
                       stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                       text=True, timeout=30)
    return p.stdout


# Reading files

def _read_json(path):
    with open(path) as f:
        return json.load(f)


def config():
    try:
        return _read_json(os.path.join(DATA_DIR, "config.json"))
    except (OSError, ValueError):
        return {}


def admin_password(username):
    """The password entry of an admin user in data/config.json, or None."""
    user = (config().get("users") or {}).get(username)
    if not user:
        return None
    perms = user.get("permissions")
    if perms != "admin" and not (isinstance(perms, list) and "admin" in perms):
        return None
    return user.get("password")


def base_url():
    host = config().get("canonicalHost")
    return f"https://{host}" if host else None


def group_names():
    names = []
    for root, _, files in os.walk(GROUPS_DIR):
        for f in files:
            if f.endswith(".json"):
                rel = os.path.relpath(os.path.join(root, f), GROUPS_DIR)
                names.append(rel[:-5])
    return sorted(names)


def group(name):
    """The group's definition, or None if it doesn't exist."""
    if not GROUP_NAME_RE.match(name):
        return None
    try:
        return _read_json(os.path.join(GROUPS_DIR, name + ".json"))
    except OSError:
        return None


def describe_user(desc):
    perms = desc.get("permissions", "")
    if isinstance(perms, list):
        perms = "[" + ", ".join(perms) + "]"
    pw = desc.get("password")
    if pw is None:
        password = "none"
    elif isinstance(pw, dict) and pw.get("type") == "wildcard":
        password = "any"
    else:
        password = "set"
    return {"permissions": perms, "password": password}


def _parse_time(s):
    if not s:
        return None
    # Go writes up to nanoseconds; Python accepts at most microseconds.
    s = re.sub(r"(\.\d{6})\d+", r"\1", s).replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


def tokens(group_name):
    """Tokens of a group, from data/var/tokens.jsonl, newest first."""
    found = {}
    try:
        with open(os.path.join(DATA_DIR, "var", "tokens.jsonl")) as f:
            for line in f:
                try:
                    t = json.loads(line)
                except ValueError:
                    continue
                if t.get("group") == group_name:
                    found[t["token"]] = t
    except OSError:
        return []
    now = datetime.now(timezone.utc)
    result = []
    for t in found.values():
        expires = _parse_time(t.get("expires"))
        result.append({
            "token": t["token"],
            "username": t.get("username") or "",
            "permissions": ", ".join(t.get("permissions") or []),
            "expires": expires,
            "issued": _parse_time(t.get("issuedAt")),
            "valid": expires is None or expires > now,
        })
    epoch = datetime.min.replace(tzinfo=timezone.utc)
    result.sort(key=lambda t: t["issued"] or epoch, reverse=True)
    return result
