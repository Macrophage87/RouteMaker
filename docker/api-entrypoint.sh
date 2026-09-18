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

# The worker count, when compose has not already set one. `compose.yaml` does
# set it - `WEB_CONCURRENCY: ${WEB_CONCURRENCY:-5}` on the api service, from
# `.env` - so this is the fallback for a container run by hand, and it is the
# fallback that has to be right, because it is the one nobody is looking at.
#
# It reads the cgroup cpu quota before it reads `nproc`, and that ordering is
# the whole of the fix. `nproc` reports the *host*: a compose `cpus:` limit is
# a cgroup quota and does not change it. On PLAN:293's 8-vCPU host the old
# `nproc * 2 + 1` was 17 sync gunicorn workers - 17 full Django processes -
# inside this service's 2 GB limit, which is an OOM kill rather than a
# throughput setting. PLAN.md:64 asks for a count "set from the host's cores",
# and the cgroup quota is that number for a service that is given a slice of
# the host rather than the whole of it.
#
# cgroup v2 only. /sys/fs/cgroup/cpu.max is "<quota> <period>" in
# microseconds, or "max <period>" when there is no limit at all - which is the
# honest case for falling through to nproc, since then the service really does
# have the machine. A v1 host, or a cgroup namespace that does not expose the
# file, falls through the same way.
cgroup_cpus() {
    [ -r /sys/fs/cgroup/cpu.max ] || return 1
    read -r quota period < /sys/fs/cgroup/cpu.max || return 1
    case "$quota" in
        ''|*[!0-9]*) return 1 ;;
    esac
    case "$period" in
        ''|*[!0-9]*|0) return 1 ;;
    esac
    # Rounded up, so a fractional limit is worth one core rather than none.
    cpus=$(( (quota + period - 1) / period ))
    [ "$cpus" -ge 1 ] || cpus=1
    echo "$cpus"
}

if [ -z "${WEB_CONCURRENCY:-}" ]; then
    if cores=$(cgroup_cpus); then
        :
    else
        cores=$(nproc)
    fi
    WEB_CONCURRENCY=$(( cores * 2 + 1 ))
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
