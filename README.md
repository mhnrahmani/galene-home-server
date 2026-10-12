# Galene in Docker

A small Docker setup for self-hosting [Galene](https://galene.org) (v1.2.1), a
videoconferencing server. Galene is built from source, and the container:

- creates the server config and an admin user on the first start,
- runs Galene's built-in TURN server, so calls work behind NAT without a
  separate coturn,
- ships `galenectl` preconfigured, so you can manage groups and users with
  `docker exec`.

Rooms are then available at `https://<your-host>:<port>/group/<group>/`.

## Requirements

- Docker with the Compose plugin, on Linux (the container uses host networking).
- A host name that resolves to the server's public IP.
- Open ports. If the server is behind a router, forward them to it:

  | Port (default) | Protocol | Purpose |
  |---|---|---|
  | 8443 | TCP | Web UI and signalling |
  | 1194 | TCP + UDP | Built-in TURN server (media relay) |

- Optional but recommended: a TLS certificate for the host name, for example
  from Let's Encrypt. Without one, Galene uses a self-signed certificate and
  browsers show a warning.

## Layout

| What | Where |
|---|---|
| Server config, admin user | `data/config.json` |
| TLS certificate | `data/cert.pem` (full chain), `data/key.pem` |
| `galenectl` config (admin credentials) | `data/galene/galenectl.json` |
| Groups (rooms) and their users | `groups/<name>.json` |
| Recordings | `recordings/` |

These directories are bind-mounted into the container and ignored by git.

## Setup

1. Copy the example settings and edit them:

   ```sh
   cp .env.example .env
   ```

   Set at least `GALENE_HOST` (your public host name) and `ADMIN_PASSWORD`.

2. Put your certificate in `data/cert.pem` and the key in `data/key.pem`.
   If you use acme.sh, for example:

   ```sh
   acme.sh --install-cert -d meet.example.com \
       --fullchain-file "$PWD/data/cert.pem" \
       --key-file       "$PWD/data/key.pem"
   ```

   Galene picks up renewed files automatically.

3. Build and start:

   ```sh
   docker compose up -d --build
   ```

   On the first start, the container creates `data/config.json` with the admin
   user. After that, `ADMIN_PASSWORD` is no longer needed and you can remove
   it from `.env`.

A healthy start logs `Relay test successful`.

The container runs as root by default, so it can read a root-only `key.pem`.
If your key is readable by others, you can remove the `user:` line from
`compose.yaml` and the container will run as an unprivileged user.

## Running the server

```sh
docker compose up -d --build       # build (first time / after changes) and start
docker compose logs -f             # follow logs
docker compose restart             # restart (e.g. after the public IP changed)
docker compose down                # stop
```

**Updating Galene:** change `GALENE_VERSION` in the `Dockerfile` (a tag from
https://github.com/jech/galene/tags), then run `docker compose up -d --build`.

## Configuration

All settings go in `.env`:

| Variable | Default | Meaning |
|---|---|---|
| `GALENE_HOST` | (required) | Public host name of the server |
| `GALENE_HTTP_PORT` | `8443` | Port for the web UI (TCP) |
| `GALENE_TURN_PORT` | `1194` | Port for the TURN server (TCP and UDP) |
| `GALENE_TURN` | `GALENE_HOST:GALENE_TURN_PORT` | Public TURN address, if different |
| `ADMIN_USER` | `admin` | Admin user name (first start only) |
| `ADMIN_PASSWORD` | | Admin password (first start only) |

`GALENE_HOST` and `GALENE_HTTP_PORT` are written to `canonicalHost` in
`data/config.json` on the first start. If you change them later, update
`canonicalHost` there too.

## Managing groups and users

`galenectl` is preconfigured inside the container with the admin credentials.
All changes take effect immediately, with no restart.

> Use `docker exec -it` for any command that asks for a password interactively.
> Without `-it`, it fails with `inappropriate ioctl for device`.

```sh
alias gctl='docker exec -it galene galenectl'   # optional shortcut
```

### Groups

```sh
gctl list-groups
gctl create-group -group friends
gctl show-group   -group friends
gctl delete-group -group friends
```

Room URL: `https://<your-host>:8443/group/friends/`

### Named users

Permissions: `op` (moderator), `present` (camera/mic/chat), `message` (chat
only), `observe` (watch only).

```sh
gctl create-user  -group friends -user alice -permissions op
gctl set-password -group friends -user alice          # prompts for a password
gctl set-password -group friends -user alice -password 'secret'   # non-interactive
gctl update-user  -group friends -user alice -permissions present
gctl list-users   -group friends -l
gctl delete-user  -group friends -user alice
```

### Shared login for guests (wildcard user)

Guests type any name they like and use one shared password. Named users keep
their own passwords, so nobody can sign in as `alice` with the shared password.

```sh
gctl create-user  -group friends -wildcard -permissions present
gctl set-password -group friends -wildcard
```

To lock guests out, change the shared password.

### Invite links (optional)

To create a link that logs someone in without a password and expires:

```sh
gctl create-token -group friends -duration 48h -permissions present
```

## Changing the admin password

1. `docker exec galene galenectl hash-password -password 'new-password'`
2. Put the JSON output as `users.admin.password` in `data/config.json`.
3. Put the plain password as `admin-password` in `data/galene/galenectl.json`.

## Troubleshooting

- **The link doesn't open from inside the server's own network.** Many routers
  don't loop requests to their public IP back into the LAN (no NAT
  hairpinning). Test from another network, such as mobile data, or add a local
  DNS entry (on the router, or in `/etc/hosts` on the client) that points your
  host name to the server's LAN address.
- **Login fails.** The user probably has no password
  (`gctl list-users -group <g> -l`).
- **Video doesn't connect, or `Relay test failed` in the logs.** Check that the
  TURN port is open for both TCP and UDP and forwarded to the server. The host
  name is resolved once at startup, so if the public IP changed, run
  `docker compose restart`.
- **Redirect to a URL without the port.** `canonicalHost` in
  `data/config.json` must include the port, e.g. `meet.example.com:8443`.

## License

This repository is released under the MIT license; see [LICENSE](LICENSE).
Galene itself is distributed under the MIT license by its authors; see
https://github.com/jech/galene.
