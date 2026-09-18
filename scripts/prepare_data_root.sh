#!/bin/sh
# Create every directory the stack binds under ${DATA_ROOT}, owned by uid 10001,
# BEFORE the first `docker compose up`.
#
# Why the order is the whole point. A bind mount whose *source* does not exist
# on the host is not an error: the Docker daemon creates it, as a directory,
# owned by root, because the daemon is root. So `up` on a fresh host silently
# manufactures ${DATA_ROOT}/backups, ${DATA_ROOT}/static, ${DATA_ROOT}/elevation
# and the three tiles/<variant>/current directories as root:root - and both of
# this project's images run as uid 10001, which then cannot write a single one
# of them. The `chown -R` that docs/DEPLOYMENT.md used to give on its own ran
# *before* that happened and so chowned a directory tree that did not yet
# contain any of the directories the problem is about.
#
# The symptom is late and does not read as an ownership problem: the nightly
# dump fails on a file it cannot create, and a rebuild gets six hours in before
# a Valhalla binary reports a permission error on a tile directory.
#
# If you have already run `up` and skipped this: stop the stack, run this same
# script, and start it again. That is the whole remedy - the directories exist
# by then, they are simply root's. It used to be given as
# `chown -R 10001:10001 "$DATA_ROOT"`, and that is the one thing not to do on a
# live host: ${DATA_ROOT} also holds `caddy/` (the ACME account key and the
# deployment's TLS private key), `postgres/` (PGDATA) and `backups/` (a dump of
# the whole database), and a recursive chown of the root hands all three to the
# uid every one of this project's containers runs as.
#
# Usage, from the repository root on the deployment host:
#
#     sudo sh scripts/prepare_data_root.sh --env-file ./.env
#
# Re-running it is safe: it creates nothing that already exists and sets no
# ownership that is already right, and it never touches the three directories
# above - so running it on a live host cannot move the database's files or the
# edge's private key to another uid.
#
# `--env-file` reads one name out of that file. It does NOT source it, and that
# is the reason the option exists rather than the caller doing
# `set -a; . ./.env; set +a` as this script used to tell them to. `.env` is
# compose's input, not the shell's: `$$` there is a literal escape and in a
# shell it is the pid, backticks in a value would run as commands, and an
# exported value takes precedence over the file when compose reads it - so a
# shell that has sourced `.env` is a shell that hands compose different values
# than the file holds. The one thing this script needs from it is a path, so it
# takes that one line and leaves every secret in the file untouched.
#
# DATA_ROOT already in the environment still works, for a caller who exported
# it deliberately; `--env-file` overrides it, since naming a file is the more
# specific instruction.

set -eu

usage() {
	echo "usage: prepare_data_root.sh [--env-file <path>]" >&2
	echo "       or with DATA_ROOT set in the environment" >&2
	exit 2
}

env_file=""
while [ $# -gt 0 ]; do
	case "$1" in
		--env-file)
			[ $# -ge 2 ] || usage
			env_file="$2"
			shift 2
			;;
		--env-file=*)
			env_file="${1#--env-file=}"
			shift
			;;
		*) usage ;;
	esac
done

if [ -n "$env_file" ]; then
	[ -r "$env_file" ] || { echo "cannot read env file '$env_file'" >&2; exit 2; }
	# The last uncommented DATA_ROOT assignment in the file, which is the one
	# compose's own reader would use. `sed` and not `.`: nothing in the file is
	# evaluated, so a value containing `$`, a backtick or a semicolon is a
	# string here exactly as it is to compose.
	value=$(sed -n 's/^[[:space:]]*DATA_ROOT[[:space:]]*=//p' "$env_file" | tail -n 1)
	# Strip a trailing CR, for a file edited on Windows, and then a matching
	# pair of quotes - which compose's dotenv reader removes and which are
	# therefore not part of the value. (Measured, and written down in
	# .env.example: quotes there are the parser's, not the value's.)
	value=$(printf '%s' "$value" | tr -d '\r')
	case "$value" in
		\'*\') value=$(printf '%s' "$value" | sed "s/^'//; s/'\$//") ;;
		'"'*'"') value=$(printf '%s' "$value" | sed 's/^"//; s/"$//') ;;
	esac
	[ -n "$value" ] || { echo "no DATA_ROOT= line in '$env_file'" >&2; exit 2; }
	DATA_ROOT="$value"
fi

: "${DATA_ROOT:?DATA_ROOT is not set. Pass --env-file ./.env, or export DATA_ROOT yourself}"

# An unset or relative DATA_ROOT would make the chowns below chowns of the
# working directory - or, empty, of /. The check above catches unset; this
# catches every other shape that is not an absolute path.
case "$DATA_ROOT" in
	/?*) ;;
	*) echo "DATA_ROOT must be an absolute path, not '$DATA_ROOT'" >&2; exit 2 ;;
esac

# Every ${DATA_ROOT} bind-mount source in compose.yaml, plus the per-variant
# `current` directories the serving containers bind individually.
# tests/test_deploy_docs.py reads the mappings out of compose.yaml and fails if
# this list stops covering them, so a mount added to the stack cannot be
# forgotten here.
DIRECTORIES="
caddy
static
postgres
photon
backups
elevation
tiles
tiles/standard/current
tiles/no-trail/current
tiles/ebike/current
extracts
reference
rebuild
"

for directory in $DIRECTORIES; do
	mkdir -p "$DATA_ROOT/$directory"
done

# The directories this project's own images write into, and the only ones this
# script changes the ownership of. uid 10001 by number, not by name: the
# account exists inside the images and need not exist on the host at all.
#
# `static` is here although compose binds it read-only into Caddy: it is
# written by the `collectstatic` deploy step, which runs the api image with
# that directory mounted (docs/DEPLOYMENT.md, "Static assets"). `tiles` is here
# rather than the three `current` paths below it because the rebuild creates a
# dated build directory beside them and replaces the symlink, which is a write
# to `tiles/<variant>` itself.
OWNED="
static
backups
elevation
tiles
extracts
reference
rebuild
"

# ...and the ones it deliberately leaves alone. This is why the chown below is
# per directory instead of `chown -R 10001:10001 "$DATA_ROOT"`, which is what
# this script used to end with:
#
#   postgres  PGDATA. The postgis image's entrypoint chowns it to its own uid
#             on every start, so a chown here is undone at best - and at worst
#             it is the database's own files handed to the uid that every
#             container of ours runs as.
#   caddy     Caddy's ACME account key and the deployment's TLS private key.
#             Caddy runs as root and obtains them itself. Nothing else on this
#             host has a reason to read them, and the rebuild container - which
#             binds five directories under ${DATA_ROOT} and used to bind the
#             whole volume - least of all.
#   photon    The geocoder's index, for a service parked behind the `unbuilt`
#             profile (see compose.yaml). Nothing in this repository writes it
#             and the image is not ours, so its owner is a question for
#             whoever enables that profile.
#
# The directory is still created for each of them: a bind-mount source that
# does not exist is manufactured by the daemon on the first `up`, which is the
# defect this whole script is about, and creating it is independent of who owns
# it.
for directory in $OWNED; do
	chown -R 10001:10001 "$DATA_ROOT/$directory"
done

echo "prepared $DATA_ROOT for uid 10001 (postgres, caddy and photon left as they are)"
