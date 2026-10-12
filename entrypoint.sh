#!/bin/sh
set -eu

cd /galene

if [ -z "${GALENE_HOST:-}" ]; then
    echo "GALENE_HOST is not set (the server's public host name)." >&2
    exit 1
fi

# First run: create data/config.json with an admin user, and the matching
# galenectl configuration, so that `docker exec galene galenectl ...` works.
if [ ! -f data/config.json ]; then
    if [ -z "${ADMIN_PASSWORD:-}" ]; then
        echo "data/config.json not found and ADMIN_PASSWORD not set." >&2
        echo "Set ADMIN_PASSWORD for the first run." >&2
        exit 1
    fi
    rm -f data/galene/galenectl.json
    /usr/local/libexec/galenectl \
        -server "https://localhost:${GALENE_HTTP_PORT}" \
        -admin-username "$ADMIN_USER" -admin-password "$ADMIN_PASSWORD" \
        initial-setup -config data/config.json.tmp >/dev/null
    # Must include the port: Galene compares it with the Host header and
    # redirects (to the bare host name) on mismatch.
    CANON="$GALENE_HOST"
    [ "$GALENE_HTTP_PORT" = 443 ] || CANON="$GALENE_HOST:$GALENE_HTTP_PORT"
    jq --arg h "$CANON" '.canonicalHost = $h' data/config.json.tmp \
        > data/config.json
    rm data/config.json.tmp
    chmod 600 data/config.json 2>/dev/null || true
    echo "Created data/config.json with admin user '$ADMIN_USER'."
fi

if [ ! -f data/cert.pem ] || [ ! -f data/key.pem ]; then
    echo "WARNING: data/cert.pem or data/key.pem missing;" \
         "Galene will use a self-signed certificate." >&2
fi

# Tell the built-in TURN server which public address clients will see
# (needed when the server is behind NAT).  The hostname is resolved once, at startup; restart the
# container if the public IP changes.
TURN="${GALENE_TURN:-${GALENE_HOST}:${GALENE_TURN_PORT}}"

exec galene \
    -http ":${GALENE_HTTP_PORT}" \
    -turn "$TURN" \
    "$@"
