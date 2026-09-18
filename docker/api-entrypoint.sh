#!/bin/sh
# The api service's default command. PLAN.md:64: "the API runs under gunicorn
# with a worker count set from the host's cores".
#
# A script rather than an exec-form CMD because the count is a function of the
# host, which is not known at build time. It is CMD and not ENTRYPOINT on
# purpose: compose overrides the command for the `worker` and `migrate`
# services with ["./manage.py", ...], and an ENTRYPOINT would swallow those
# arguments into gunicorn's argv instead of running them.
set -eu

# nproc reports the host's cores. A compose `cpus:` limit is a cgroup quota and
# does not change it, which is what PLAN.md:64 asks for - but it means the
# figure is the host's, not the service's, so WEB_CONCURRENCY (gunicorn's own
# variable) overrides it on a host whose core count and api cpu limit diverge.
if [ -z "${WEB_CONCURRENCY:-}" ]; then
    WEB_CONCURRENCY=$(( $(nproc) * 2 + 1 ))
    export WEB_CONCURRENCY
fi

# Sync workers, which is the right class here and not a default left alone:
# PLAN.md:64 - "Views are synchronous, since the request path is a single
# routing call plus database queries".
exec gunicorn config.wsgi:application \
    --bind "${GUNICORN_BIND:-0.0.0.0:8000}" \
    --workers "${WEB_CONCURRENCY}" \
    --timeout "${GUNICORN_TIMEOUT:-60}" \
    --graceful-timeout "${GUNICORN_GRACEFUL_TIMEOUT:-30}" \
    --access-logfile - \
    --error-logfile - \
    --capture-output
