#!/bin/sh
# docker compose for the beta: always the base file plus the overlay, always this
# checkout's .env, and refusing the commands that would start the wrong things.
#
#   scripts/beta/beta-compose.sh <compose arguments>
#   scripts/beta/beta-compose.sh up -d postgis
#   scripts/beta/beta-compose.sh up -d api worker photon valhalla-standard ...
#
# What it refuses, because each one has bitten or would bite:
#   * `up` with no service named (a bare `up -d` starts everything the overlay did not
#     park, and the next person to add a service would be starting it by accident);
#   * `up` naming caddy, rebuild, renderer or bot, which are not part of the beta;
#   * --profile not-in-beta (the profile that parks caddy and rebuild);
#   * `down` with -v/--volumes or --rmi (nothing durable is in a volume here, but the
#     habit is the danger);
#   * running without .env or without COMPOSE_PROJECT_NAME in it (a missing project name
#     makes compose use the directory name, which can be another project's).
# Everything else (ps, logs, exec, run, build, pull, stop, restart, config, down) passes
# through.
set -eu

die() { echo "beta-compose: $*" >&2; exit 2; }

here=$(cd "$(dirname "$0")" && pwd)
repo=$(cd "$here/../.." && pwd)
cd "$repo"

env_file=${BETA_ENV_FILE:-$repo/.env}
[ -r "$env_file" ] || die "no readable $env_file (scripts/beta/make-env.sh creates it)"
grep -q '^COMPOSE_PROJECT_NAME=.' "$env_file" || die "COMPOSE_PROJECT_NAME is not set in $env_file"
[ -r compose.yaml ] && [ -r compose.beta.yaml ] || die "compose.yaml and compose.beta.yaml must both be in $repo"

# Find the subcommand: the first argument that is not a global option or an option's value.
sub=""; prev=""
for arg in "$@"; do
	case "$prev" in
		--profile | -p | --project-name | -f | --file | --env-file | --project-directory) prev=""; continue ;;
	esac
	case "$arg" in
		--profile | -p | --project-name | -f | --file | --env-file | --project-directory) prev=$arg; continue ;;
		--profile=* | --project-name=* | --file=* | --env-file=* | --project-directory=*) continue ;;
		-*) continue ;;
	esac
	sub=$arg
	break
done
[ -n "$sub" ] || die "no compose command given"

for arg in "$@"; do
	case "$arg" in
		not-in-beta | --profile=not-in-beta) die "the not-in-beta profile parks caddy and rebuild; they do not run on the beta" ;;
	esac
done

case "$sub" in
	up)
		# Service names are the non-option words after `up` that are not option values.
		seen_up=0; names=""
		for arg in "$@"; do
			if [ "$seen_up" = 0 ]; then
				[ "$arg" = up ] && seen_up=1
				continue
			fi
			case "$arg" in
				-*) ;;
				*) names="$names $arg" ;;
			esac
		done
		# --scale NAME=N and --timeout N/-t N put a value among the words; drop numbers and NAME=N.
		clean=""
		for word in $names; do
			case "$word" in
				*=* | [0-9]*) ;;
				*) clean="$clean $word" ;;
			esac
		done
		[ -n "$clean" ] || die "name the services to start; a bare 'up' is refused (see docs/BETA-RUNBOOK.md for the order)"
		for word in $clean; do
			case "$word" in
				caddy | rebuild | renderer | bot) die "$word is not part of the beta stack" ;;
			esac
		done
		;;
	down)
		for arg in "$@"; do
			case "$arg" in
				-v | --volumes | --rmi | --rmi=*) die "down $arg is refused here" ;;
			esac
		done
		;;
esac

exec docker compose -f compose.yaml -f compose.beta.yaml --env-file "$env_file" "$@"
