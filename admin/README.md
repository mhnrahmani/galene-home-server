# Galene admin GUI (optional)

A small web interface for the Galene server in the parent directory. It
doesn't replace the `gctl` commands: it runs the same `galenectl` commands
inside the Galene container, and shows each command it ran. Anything you do
on the command line shows up in the GUI, and the other way round.

It can:

- list, create and delete groups, and edit their settings (display name,
  description, public, recording, max. participants, ...);
- add, change and delete users, set passwords, and enable or disable the
  shared guest login;
- create, copy, revoke and delete invite links;
- start, stop and restart the Galene container, and show its logs.

## Setup

The Galene server must be set up first (see the [main README](../README.md)).
Then, in this directory:

```sh
cp .env.example .env              # adjust if needed
docker compose up -d --build
```

## Two modes

Choose with `ADMIN_GUI_MODE` in `.env`:

| | `lan` (default) | `internet` |
|---|---|---|
| Reachable from | devices on your local network | anywhere |
| Address | `http://<server LAN IP>:8444` | `https://<your-host>:8444` |
| Login | none | Galene admin account |

**LAN mode** answers only clients whose address is in `ADMIN_GUI_SUBNETS`
(default: all private networks, such as `192.168.0.0/16`), plus the server
itself. It also refuses requests made under public domain names, so a web
page can't reach the GUI through your browser (DNS rebinding). IP addresses
and local names (no dot, or ending in `.local`, `.lan`, `.home`,
`.home.arpa`, `.internal`) work; add other names to `ADMIN_GUI_HOSTS`.
Don't forward the port on your router in this mode. Anyone on the allowed
networks can use the GUI without a password, so narrow `ADMIN_GUI_SUBNETS`
if your network has untrusted devices (guest Wi-Fi, for example). From
outside, you can still use an SSH tunnel:

```sh
ssh -L 8444:localhost:8444 user@your-server    # then open http://localhost:8444
```

**Internet mode** serves HTTPS with `data/cert.pem` and `data/key.pem`, and
reloads them automatically when they are renewed. Log in with the admin user
and password from the first start (`ADMIN_USER` / `ADMIN_PASSWORD` in the
main `.env`). After 5 failed logins, an address is blocked for 5 minutes.
Search engines are asked not to index the GUI (`robots.txt`, an
`X-Robots-Tag` header and a robots meta tag).
Forward or open `ADMIN_GUI_PORT` (TCP).

**Secret path (optional, both modes).** With `ADMIN_GUI_PATH` set, the GUI
is only served at `https://<your-host>:8444/<ADMIN_GUI_PATH>/`, and every
other path returns 404. Scanners that probe `/`, `/login` and so on then
never see the login form. Use a long random string
(`openssl rand -hex 16`) and keep it to yourself. It is an extra filter, not
a replacement for the password.

In both modes, `ADMIN_GUI_LISTEN` decides which host address the port is
opened on. Docker-published ports bypass host firewalls such as ufw, so
binding to the server's LAN IP (instead of `0.0.0.0`) is a useful extra
guard in LAN mode.

## Settings

| Variable | Default | Meaning |
|---|---|---|
| `ADMIN_GUI_MODE` | `lan` | `lan` or `internet`, see above |
| `ADMIN_GUI_LISTEN` | `0.0.0.0` | Host address to listen on, e.g. the server's LAN IP |
| `ADMIN_GUI_PORT` | `8444` | Port of the GUI |
| `ADMIN_GUI_PATH` | | Optional secret path prefix, see above |
| `ADMIN_GUI_SUBNETS` | private networks | LAN mode: allowed client networks, comma-separated, e.g. `192.168.1.0/24` |
| `ADMIN_GUI_HOSTS` | | LAN mode: extra host names to accept, comma-separated |
| `GALENE_CONTAINER` | `galene` | Name of the Galene container |

## How it works

- Changes run as `docker exec galene galenectl ...`, through the Docker
  socket mounted into the container.
- Server control uses `docker start|stop|restart galene` and
  `docker logs galene`.
- To display users and invite links, the GUI reads `../groups/*.json` and
  `../data/var/tokens.jsonl` (read-only), because `galenectl` doesn't show
  everything (for example whether a user has a password).
- Invite and room links are built from `canonicalHost` in
  `../data/config.json`.
- Changing groups and users needs Galene to be running. The GUI shows a
  warning when it isn't.

**Security note:** access to the Docker socket is equivalent to root access
on the host. Anyone who can use the GUI can control Docker on the server.
Keep `ADMIN_GUI_SUBNETS` as narrow as you can in LAN mode, and use a strong
admin password in internet mode.

## Commands

```sh
docker compose up -d --build       # build and start
docker compose logs -f             # follow logs
docker compose down                # stop and remove (Galene keeps running)
```
