#!/bin/sh
# Run a build command, trusting an optional extra CA only for its duration.
#
# Some build environments reach the internet through a TLS-intercepting proxy. Its CA is
# passed as the BuildKit secret "proxy_ca" (never a build arg, never COPY), installed here,
# used by apt/pip for this one RUN step, and removed again before the layer is committed, so
# no image ever trusts it. Without the secret this script just runs the command.
set -eu
ca=/run/secrets/proxy_ca
cleanup() {
    rm -f /usr/local/share/ca-certificates/afid-build-proxy.crt /etc/apt/apt.conf.d/99afid-proxy
    update-ca-certificates --fresh >/dev/null 2>&1 || true
}
if [ -s "$ca" ]; then
    trap cleanup EXIT
    cp "$ca" /usr/local/share/ca-certificates/afid-build-proxy.crt
    update-ca-certificates >/dev/null 2>&1
    export PIP_CERT=/etc/ssl/certs/ca-certificates.crt
    export SSL_CERT_FILE=/etc/ssl/certs/ca-certificates.crt
    export GIT_SSL_CAINFO=/etc/ssl/certs/ca-certificates.crt
    if [ -n "${HTTPS_PROXY:-}" ]; then
        printf 'Acquire::https::Proxy "%s";\n' "$HTTPS_PROXY" > /etc/apt/apt.conf.d/99afid-proxy
    fi
fi
"$@"
