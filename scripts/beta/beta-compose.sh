#!/bin/sh
# docker compose for the beta: always the base file plus the overlay, always this
# checkout's .env, and refusing the commands that would start the wrong things.
#
#   scripts/beta/beta-compose.sh <compose arguments>
#   scripts/beta/beta-compose.sh up -d postgis
#   scripts/beta/beta-compose.sh up -d api worker photon valhalla-standard ...
#
# What it refuses, because each one has bitten or would bite:
#   * caddy, rebuild, renderer or bot (or the not-in-beta profile) named ANYWHERE after the
#     subcommand, under EVERY subcommand: up, run, create, start, restart, pull, build, exec,
#     logs, and the rest. Compose enables a service's profile when the service is named
#     explicitly, so `run --rm rebuild` would otherwise start the parked rebuild. The word
#     is refused even as an option value or a command argument (`exec api echo bot` too):
#     the check does not depend on parsing compose's options right.
#   * `up` or `create` with no service named (a bare `up -d` starts everything the overlay
#     did not park, and the next person to add a service would be starting it by accident).
#     Option values are skipped properly, so `up -d --pull never` is a bare up, not an up
#     of a service called "never".
#   * -p/--project-name (the project is COMPOSE_PROJECT_NAME in .env), -f/--file,
#     --env-file and --project-directory (the wrapper decides those);
#   * any --profile but `offroad` (so not `--profile '*'` and not not-in-beta);
#   * COMPOSE_PROFILES, COMPOSE_FILE, COMPOSE_PROJECT_NAME, COMPOSE_PATH_SEPARATOR or
#     COMPOSE_ENV_FILES in the environment, and COMPOSE_PROFILES or COMPOSE_FILE in .env:
#     each would change the project, the files or the profiles behind the wrapper's back;
#   * --scale (a second copy of a service doubles its memory cap), and `run -p/--publish`
#     (it would publish a port on every interface, not 127.0.0.1);
#   * `down` or `rm` with -v/--volumes, and `down --rmi` (nothing durable is in a volume
#     here, but the habit is the danger);
#   * running without .env or without COMPOSE_PROJECT_NAME in it (a missing project name
#     makes compose use the directory name, which can be another project's).
# Everything else (ps, logs, exec, run, build, pull, stop, restart, config, down) passes
# through. As a backstop, compose.beta.yaml also caps caddy and rebuild tiny.
#
# BETA_ENV_FILE names the env file [<repo>/.env]; DOCKER is the docker binary [docker]
# (tests point it at a stub).
set -eu

die() { echo "beta-compose: $*" >&2; exit 2; }

here=$(cd "$(dirname "$0")" && pwd)
repo=$(cd "$here/../.." && pwd)
cd "$repo"

for var in COMPOSE_PROFILES COMPOSE_FILE COMPOSE_PROJECT_NAME COMPOSE_PATH_SEPARATOR COMPOSE_ENV_FILES; do
	if printenv "$var" >/dev/null 2>&1; then
		die "$var is set in the environment; unset it (.env and this wrapper decide the project, files and profiles)"
	fi
done

env_file=${BETA_ENV_FILE:-$repo/.env}
[ -r "$env_file" ] || die "no readable $env_file (scripts/beta/make-env.sh creates it)"
grep -q '^COMPOSE_PROJECT_NAME=.' "$env_file" || die "COMPOSE_PROJECT_NAME is not set in $env_file"
if grep -Eq '^[[:space:]]*(export[[:space:]]+)?COMPOSE_(PROFILES|FILE)[[:space:]]*=' "$env_file"; then
	die "$env_file sets COMPOSE_PROFILES or COMPOSE_FILE; remove that line"
fi
[ -r compose.yaml ] && [ -r compose.beta.yaml ] || die "compose.yaml and compose.beta.yaml must both be in $repo"

parked="caddy rebuild renderer bot not-in-beta"
is_parked() {
	for p in $parked; do
		[ "$1" != "$p" ] || return 0
	done
	return 1
}
check_profile() {
	case "$1" in
		offroad) ;;
		not-in-beta) die "the not-in-beta profile parks caddy and rebuild; they do not run on the beta" ;;
		*) die "--profile '$1' is refused; the only profile the beta uses is offroad" ;;
	esac
}

sub=""; expect=""; names=""; dashdash=0
for arg in "$@"; do
	if [ -z "$sub" ]; then
		# --- global options, before the subcommand ---
		if [ -n "$expect" ]; then
			[ "$expect" != --profile ] || check_profile "$arg"
			expect=""
			continue
		fi
		case "$arg" in
			-p | -p?* | --project-name | --project-name=*) die "$arg is refused: the project name is COMPOSE_PROJECT_NAME in .env" ;;
			-f | -f?* | --file | --file=*) die "$arg is refused: the wrapper always uses compose.yaml and compose.beta.yaml" ;;
			--env-file | --env-file=*) die "$arg is refused: name the file with BETA_ENV_FILE" ;;
			--project-directory | --project-directory=*) die "$arg is refused: the wrapper runs in its own checkout" ;;
			--profile) expect=--profile ;;
			--profile=*) check_profile "${arg#--profile=}" ;;
			--ansi | --parallel | --progress) expect=$arg ;;
			-*) ;;
			*) sub=$arg ;;
		esac
		continue
	fi
	# --- after the subcommand: a parked name is refused wherever it appears ---
	for word in "$arg" "${arg%%=*}" "${arg#*=}"; do
		if is_parked "$word"; then
			die "$word is not part of the beta stack (refused under every subcommand, here '$sub')"
		fi
	done
	if [ -n "$expect" ]; then
		expect=""
		continue
	fi
	if [ "$dashdash" = 1 ]; then
		names="$names $arg"
		continue
	fi
	case "$arg" in
		--) dashdash=1 ;;
		--scale | --scale=*) die "--scale is refused: a second copy of a service doubles its memory cap" ;;
		-p | -p?* | --publish | --publish=*)
			[ "$sub" != run ] || die "run $arg is refused: it would publish on every interface, not 127.0.0.1"
			case "$arg" in -p | --publish) expect=$arg ;; esac
			;;
		-v | --volumes | --volumes=*)
			case "$sub" in
				down | rm) die "$sub $arg is refused here" ;;
				run) [ "$arg" != -v ] || expect=$arg ;;
			esac
			;;
		--rmi | --rmi=*) [ "$sub" != down ] || die "down $arg is refused here"; [ "$arg" != --rmi ] || expect=$arg ;;
		--volume) expect=$arg ;;
		# options that take a value as the next word, across compose's subcommands
		--pull | --wait-timeout | -t | --timeout | --exit-code-from | --attach | --no-attach | \
			-e | --env | -u | --user | -w | --workdir | --entrypoint | --name | -l | --label | \
			--index | --tail | --since | --until | --format | --status | --filter | --cap-add | \
			--cap-drop | --build-arg | --ssh | --builder | --signal | -s | -m | --memory | --progress | \
			--hash | --output | -o)
			expect=$arg
			;;
		-*) ;;
		*) names="$names $arg" ;;
	esac
done
[ -n "$sub" ] || die "no compose command given"

case "$sub" in
	up | create)
		[ -n "$names" ] || die "name the services to start; a bare '$sub' is refused (see docs/BETA-RUNBOOK.md for the order)"
		;;
esac

exec "${DOCKER:-docker}" compose -f compose.yaml -f compose.beta.yaml --env-file "$env_file" "$@"
