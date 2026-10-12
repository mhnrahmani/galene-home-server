# syntax=docker/dockerfile:1

ARG GALENE_VERSION=galene-1.2.1

FROM golang:1.25-alpine AS build
ARG GALENE_VERSION
RUN apk add --no-cache git
WORKDIR /src
RUN git clone --depth 1 --branch "${GALENE_VERSION}" https://github.com/jech/galene.git .
ENV CGO_ENABLED=0
RUN go build -trimpath -ldflags='-s -w' -o /out/galene . \
 && cd galenectl && go build -trimpath -ldflags='-s -w' -o /out/galenectl .

FROM alpine:3.22
RUN apk add --no-cache ca-certificates jq tini \
 && addgroup -S galene && adduser -S -G galene -h /galene galene
WORKDIR /galene
COPY --from=build /out/galene /usr/local/bin/galene
COPY --from=build /out/galenectl /usr/local/libexec/galenectl
COPY --from=build /src/static /galene/static
COPY entrypoint.sh /usr/local/bin/entrypoint.sh
# galenectl talks to the server over localhost, where the certificate's
# hostname does not match, hence -insecure.
RUN printf '#!/bin/sh\nexec /usr/local/libexec/galenectl -insecure "$@"\n' \
      > /usr/local/bin/galenectl \
 && chmod 755 /usr/local/bin/galenectl /usr/local/bin/entrypoint.sh \
 && mkdir -p data groups recordings && chown -R galene:galene /galene

# galenectl keeps its config (incl. admin credentials) under $XDG_CONFIG_HOME
ENV XDG_CONFIG_HOME=/galene/data \
    GALENE_HOST= \
    GALENE_HTTP_PORT=8443 \
    GALENE_TURN_PORT=1194 \
    ADMIN_USER=admin

USER galene
VOLUME ["/galene/data", "/galene/groups", "/galene/recordings"]
EXPOSE 8443/tcp 1194/tcp 1194/udp
ENTRYPOINT ["/sbin/tini", "--", "/usr/local/bin/entrypoint.sh"]
