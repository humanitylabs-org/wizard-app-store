#!/bin/sh
set -eu
# Accept a single fixed HTTP(S) origin, not credentials, paths or nginx syntax.
case "${HERMES_BACKEND_URL:-}" in
  *[!a-zA-Z0-9.:/_-]*) printf '%s\n' 'Invalid backend origin characters.' >&2; exit 1 ;;
esac
if ! printf '%s' "${HERMES_BACKEND_URL:-}" | grep -Eq '^https?://[A-Za-z0-9][A-Za-z0-9._-]*(:[0-9]{1,5})?$'; then
  printf '%s\n' 'HERMES_BACKEND_URL must be an http(s) origin with no path or credentials.' >&2
  exit 1
fi
export HERMES_BACKEND_URL
envsubst '${HERMES_BACKEND_URL}' < /opt/frontend/nginx.conf.template > /tmp/wizard-nginx.conf
exec nginx -c /tmp/wizard-nginx.conf -g 'daemon off;'
