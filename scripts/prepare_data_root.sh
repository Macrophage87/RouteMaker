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
# If you have already run `up` and skipped this: stop the stack, run
# `sudo chown -R 10001:10001 "$DATA_ROOT"`, and start it again. That is the
# whole remedy - the directories exist by then, they are simply root's.
#
# Usage, from the repository root on the deployment host:
#
#     set -a; . ./.env; set +a
#     sudo -E sh scripts/prepare_data_root.sh
#
# Re-running it is safe and does nothing on an already-prepared host.

set -eu

: "${DATA_ROOT:?DATA_ROOT is not set. Load the deployment's environment first: set -a; . ./.env; set +a}"

# An unset or relative DATA_ROOT would make the chown below a chown of the
# working directory - or, empty, of /. The check above catches unset; this
# catches every other shape that is not an absolute path.
case "$DATA_ROOT" in
	/?*) ;;
	*) echo "DATA_ROOT must be an absolute path, not '$DATA_ROOT'" >&2; exit 2 ;;
esac

# Every ${DATA_ROOT} bind-mount source in compose.yaml, plus the three
# directories the rebuild writes inside its whole-volume mount and so does not
# name as a mapping of its own. tests/test_deploy_docs.py reads the mappings out
# of compose.yaml and fails if this list stops covering them, so a mount added
# to the stack cannot be forgotten here.
DIRECTORIES="
caddy
static
postgres
photon
backups
elevation
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

# uid 10001 by number, not by name: the account exists inside the images and
# need not exist on the host at all.
#
# Two of these directories end up owned by somebody else, and that is correct.
# The postgres image's entrypoint chowns its own PGDATA to its own uid on every
# start, and Caddy runs as root and owns the certificates it obtains. 10001 is
# the right owner for everything this project's images write - the dumps, the
# collected static assets, the tiles, the elevation cache, the extracts and the
# reference data - which is everything else.
chown -R 10001:10001 "$DATA_ROOT"

echo "prepared $DATA_ROOT for uid 10001"
