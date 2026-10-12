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

Choose with `ADMIN_GUI_LISTEN` in `.env`:

| | `127.0.0.1` (default) | `0.0.0.0` |
|---|---|---|
| Reachable from | the server only | the network / internet |
| Protocol | HTTP | HTTPS, with Galene's certificate |
| Login | none | Galene admin account |

**Localhost mode** is the safer choice. To use it from your computer, open an
SSH tunnel to the server and browse to http://localhost:8444:

```sh
ssh -L 8444:localhost:8444 user@your-server
```

**Exposed mode** serves HTTPS with `data/cert.pem` and `data/key.pem`, and
reloads them automatically when they are renewed. Log in with the admin user
and password from the first start (`ADMIN_USER` / `ADMIN_PASSWORD` in the
main `.env`). After 5 failed logins, an address is blocked for 5 minutes.
Open `ADMIN_GUI_PORT` (TCP) in your firewall or router.

## Settings

| Variable | Default | Meaning |
|---|---|---|
| `ADMIN_GUI_LISTEN` | `127.0.0.1` | Host address to listen on, see above |
| `ADMIN_GUI_PORT` | `8444` | Port of the GUI |
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
Keep the default localhost mode unless you need it, and use a strong admin
password in exposed mode.

## Commands

```sh
docker compose up -d --build       # build and start
docker compose logs -f             # follow logs
docker compose down                # stop and remove (Galene keeps running)
```
