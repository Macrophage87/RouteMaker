#!/usr/bin/env bash
# Sends what a cloud rebuild needs from the LOCAL live stack to S3. Run at home.
# Pairs with scripts/cloud/box-rebuild.sh on the box and scripts/cloud/import-result.sh
# back here (docs/OPERATIONS.md, "Rebuilding on the cloud box").
#
#   scripts/cloud/send-inputs.sh [options] RUN_URL
#
#   RUN_URL   s3://<bucket>/rebuild-checkpoints/transfer/<run>, the run's folder. The last
#             part names the run (lowercase letters, digits, hyphens), e.g. cloud-20261011.
#             The bucket name is given here, at run time, and is written nowhere in the
#             repository.
#
# What goes to RUN_URL/in/:
#   db.tar                  a dump made for this run by scripts/beta/ship-data.sh (its db part
#                           only, --no-transfer): the same tables left out and the same person
#                           columns blanked as the beta's data, and the same refusal of a dump
#                           that carries them. No accounts, Homes, saved or shared routes, audit
#                           log or sessions leave home; the approved overrides (the road panel's
#                           stress edits among them) do, so they are all in the box's map.
#   reference.tar           DATA_ROOT/reference, or --reference-dir (crossings, urban areas,
#                           traffic counts)
#   elevation.tar           DATA_ROOT/elevation (saves the box the 3DEP download)
#   extracts.tar            DATA_ROOT/extracts (the box applies the same six-day rule to it)
#   MANIFEST.txt            run, commit, backup=db.tar and read_at=<the UTC time the dump began>
#   SHA256SUMS              one line per file, sent LAST: a folder without it is unfinished,
#                           and box-rebuild.sh refuses it
#
# READ-ONLY on the live stack: it reads DATA_ROOT, the checkout's git state and (through
# ship-data.sh, with pg_dump and SELECTs) the database, which must be running, and writes
# only under --stage (default ~/cloud-runs/<run>/in), which it refuses to place inside
# DATA_ROOT or the checkout. The tars are made with sudo because DATA_ROOT's directories
# belong to the containers' uid (10001); --numeric-owner keeps that owner for the box.
#
# Options:
#   --live-dir DIR   the live stack's checkout: .env and the commit [this repository]
#   --stage DIR      where the files are assembled [~/cloud-runs/<run>/in]
#   --profile NAME   the AWS CLI profile (`aws login --remote --profile NAME` first)
#   --reference-dir DIR
#                    the reference folder to send [DATA_ROOT/reference]. Refused when it lacks
#                    a traffic-count source the live map has (every agency in the live segment
#                    table's volume_source must be in its volume.json or roadway.json; not
#                    checked where there is no live table yet), or when a file of
#                    DATA_ROOT/reference, which the live build read, is missing from it or
#                    differs (by checksum, every file below it): the v0.7.0 staging run was
#                    sent a stale folder with no MDOT SHA counts and lost 5,954 segments'
#                    counts
#   --allow-dirty    send even though the checkout has uncommitted changes to tracked
#                    files (the box builds the commit, not those changes)
#   --no-transfer    assemble and checksum the stage, send nothing
#   -h, --help
# Environment (for tests): CLOUD_AWS [aws], CLOUD_SUDO [sudo], CLOUD_GIT [git],
# CLOUD_DOCKER [docker], CLOUD_SHIP_DATA [scripts/beta/ship-data.sh beside this script].
set -Eeuo pipefail

die() { echo "send-inputs: $*" >&2; exit 2; }
note() { echo "send-inputs: $*"; }

here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
live_dir=$(cd "$here/../.." && pwd)
stage="" profile="" allow_dirty=0 transfer=1 url="" reference_dir=""
while [ $# -gt 0 ]; do
	case "$1" in
		--live-dir) [ $# -ge 2 ] || die "$1 needs a value"; live_dir=$2; shift 2 ;;
		--stage) [ $# -ge 2 ] || die "$1 needs a value"; stage=$2; shift 2 ;;
		--profile) [ $# -ge 2 ] || die "$1 needs a value"; profile=$2; shift 2 ;;
		--reference-dir) [ $# -ge 2 ] || die "$1 needs a value"; reference_dir=$2; shift 2 ;;
		--allow-dirty) allow_dirty=1; shift ;;
		--no-transfer) transfer=0; shift ;;
		-h | --help) sed -n '2,/^set -E/p' "$0" | sed '$d; s/^# \{0,1\}//'; exit 0 ;;
		-*) die "unknown option $1" ;;
		*) [ -z "$url" ] || die "one RUN_URL only"; url=$1; shift ;;
	esac
done
[ -n "$url" ] || die "usage: send-inputs.sh [options] s3://<bucket>/rebuild-checkpoints/transfer/<run>"
url=${url%/}
case "$url" in s3://?*/?*) ;; *) die "RUN_URL must be s3://<bucket>/.../<run>, not $url" ;; esac
run=${url##*/}
[[ "$run" =~ ^[a-z0-9][a-z0-9-]{0,62}$ ]] || die "the run name '$run' must be lowercase letters, digits and hyphens"

AWS=${CLOUD_AWS:-aws}
SUDO=${CLOUD_SUDO-sudo}
GIT=${CLOUD_GIT:-git}
DOCKER=${CLOUD_DOCKER:-docker}
aws_() { if [ -n "$profile" ]; then "$AWS" --profile "$profile" "$@"; else "$AWS" "$@"; fi; }

live_dir=$(cd "$live_dir" && pwd) || die "no such directory: $live_dir"
env_file="$live_dir/.env"
[ -r "$env_file" ] || die "no .env in $live_dir: --live-dir names the checkout the live stack runs from"
# One name out of .env with sed, never by sourcing it (docs/DEPLOYMENT.md, ".env is
# compose's input, not the shell's").
data_root=$(sed -n 's/^DATA_ROOT=//p' "$env_file" | tail -n1)
data_root=${data_root%\"}; data_root=${data_root#\"}
case "$data_root" in /?*) ;; *) die "DATA_ROOT in $env_file is not an absolute path" ;; esac
# The box builds with the defaults for these; a deployment that changed them would get a
# different map back. Only whether each is set is read, never its value.
for key in COVERAGE_POLYGON ROUTEMAKER_LIVE_SCHEMA ROUTEMAKER_STAGING_SCHEMA; do
	set_to=$(sed -n "s/^$key=//p" "$env_file" | tail -n1 | tr -d "\"'")
	[ -z "$set_to" ] ||
		die "$key is set in $env_file; the cloud box builds with its default, so its map would differ. Build here instead"
done
[ -d "$data_root" ] || die "DATA_ROOT $data_root does not exist"

# safe.directory: run with sudo, or as another user than the checkout's owner, git refuses
# the checkout as "dubious ownership" without it.
git_() { "$GIT" -c safe.directory="$live_dir" -C "$live_dir" "$@"; }
commit=$(git_ rev-parse HEAD) || die "$live_dir is not a git checkout"
if [ -n "$(git_ status --porcelain --untracked-files=no)" ]; then
	[ "$allow_dirty" = 1 ] || die "$live_dir has uncommitted changes to tracked files; the box builds commit $commit without them. Commit them, or pass --allow-dirty"
	note "WARNING: uncommitted changes in $live_dir are not in the box's build"
fi
# The box clones from GitHub, so the commit has to be there.
[ -n "$(git_ branch -r --contains "$commit" 2>/dev/null)" ] ||
	die "commit $commit is on no remote branch; push it first, or the box cannot check it out"

for part in reference elevation extracts; do
	[ -d "$data_root/$part" ] || die "$data_root/$part is missing"
done
live_reference="$data_root/reference"
reference_dir=${reference_dir:-$live_reference}
[ -d "$reference_dir" ] || die "--reference-dir $reference_dir is not a directory"
reference_dir=$(cd "$reference_dir" && pwd)

# The reference folder against the live map. A folder without a count source the live map
# has builds a map that silently loses those counts (the v0.7.0 staging run: no MDOT SHA
# counts, so 5,986 busy roads lost their volume step-ups and the narrow-road rule read
# 421 mi of counted rural roads as uncounted).
pguser=$(sed -n 's/^PGUSER=//p' "$env_file" | tail -n1 | tr -d "\"'")
pgdb=$(sed -n 's/^PGDATABASE=//p' "$env_file" | tail -n1 | tr -d "\"'")
live_sql() {
	(cd "$live_dir" && "$DOCKER" compose exec -T postgis psql -U "${pguser:-routemaker}" \
		-d "${pgdb:-routemaker}" -AtX -v ON_ERROR_STOP=1 -c "$1" </dev/null)
}
has_live=$(live_sql "SELECT to_regclass('live.segment') IS NOT NULL") ||
	die "could not ask the database whether there is a live map (its message is above; is it running?); the reference folder is checked against the live map's count sources"
if [ "$has_live" != t ]; then
	note "no live segment table here (a first deployment?): the reference folder's count sources are not checked against a live map"
else
	live_sources=$(live_sql "SELECT DISTINCT volume_source FROM live.segment
		WHERE volume_source IS NOT NULL AND volume_source <> 'none' ORDER BY 1") ||
		die "could not read the live map's count sources (its message is above); the reference folder is checked against them"
	held=$(for f in volume.json roadway.json; do
		[ ! -e "$reference_dir/$f" ] || $SUDO grep -o '"agency": *"[^"]*"' "$reference_dir/$f" || true
	done | sed 's/.*"\([^"]*\)"$/\1/' | sort -u)
	missing=()
	while IFS= read -r agency; do
		[ -n "$agency" ] || continue
		grep -qxF -- "$agency" <<<"$held" || missing+=("$agency")
	done <<<"$live_sources"
	[ ${#missing[@]} -eq 0 ] ||
		die "$reference_dir has no traffic counts from ${missing[*]}, which the live map has; the box would build a map without them. Send the folder the live build read ($live_reference), or reinstall the counts (scripts/install_reference_data.py --volume ...)"
fi
# Another folder than the live build's must hold every file the live build read, with
# the same contents: anything else is an older (or other) copy, and the box would build
# a different map from it. Newer data goes into DATA_ROOT/reference first.
if [ "$reference_dir" != "$(cd "$live_reference" && pwd)" ]; then
	while IFS= read -r -d '' rel; do
		[ -e "$reference_dir/$rel" ] ||
			die "$reference_dir has no $rel, which $live_reference (the live build's) has"
		ours=$($SUDO sha256sum -- "$live_reference/$rel" | cut -d' ' -f1)
		theirs=$($SUDO sha256sum -- "$reference_dir/$rel" | cut -d' ' -f1)
		[ "$ours" = "$theirs" ] ||
			die "$reference_dir/$rel differs from $live_reference/$rel, which the live build read; send the live build's folder, or install the newer data there first"
	done < <($SUDO find "$live_reference" -type f -printf '%P\0')
fi

[ -n "$stage" ] || stage="$HOME/cloud-runs/$run/in"
# Checked before anything is created, so a mistaken --stage never writes into DATA_ROOT.
stage=$(realpath -m "$stage")
case "$stage/" in
	"$(realpath -m "$data_root")"/* | "$(realpath -m "$live_dir")"/*)
		die "--stage $stage is inside DATA_ROOT or the checkout; put it elsewhere" ;;
esac
mkdir -p "$stage"
rm -rf "$stage/db-bundle"
rm -f "$stage"/routemaker-*.dump "$stage"/*.tar "$stage/MANIFEST.txt" "$stage/SHA256SUMS"

# Not the nightly backup: that keeps accounts, Homes and the audit log for a restore here,
# and none of them belongs in the cloud. The rebuild reads none of them either (it reads the
# approved overrides and the segment tables). Taken before the dump starts, so an override
# approved while it runs counts as later than the copy (import_cloud_build lists those).
read_at=$(date -u +%Y%m%dT%H%M%SZ)
backup=db.tar
note "dumping the database without identities (scripts/beta/ship-data.sh's db part), commit $commit"
(umask 077 && "${CLOUD_SHIP_DATA:-$here/../beta/ship-data.sh}" --live-dir "$live_dir" --stage "$stage/db-bundle" \
	--no-transfer --without tiles --without elevation --without basemap --without photon \
	--without transit --without frontend) ||
	die "ship-data.sh made no database dump (its message is above)"
[ -s "$stage/db-bundle/db/routemaker.dump" ] || die "ship-data.sh staged no db/routemaker.dump"
(umask 077 && tar -C "$stage/db-bundle" -cf "$stage/$backup" db)
rm -rf "$stage/db-bundle"
note "packing reference (from $reference_dir)"
# Always packed as reference/, whichever folder it came from.
$SUDO tar -C "$reference_dir" --numeric-owner --transform 's,^\.,reference,' -cf "$stage/reference.tar" .
$SUDO chown "$(id -u):$(id -g)" "$stage/reference.tar" 2>/dev/null || true
for part in elevation extracts; do
	note "packing $part"
	$SUDO tar -C "$data_root" --numeric-owner -cf "$stage/$part.tar" "$part"
	$SUDO chown "$(id -u):$(id -g)" "$stage/$part.tar" 2>/dev/null || true
done
{
	echo "run=$run"
	echo "commit=$commit"
	echo "backup=$(basename "$backup")"
	echo "read_at=$read_at"
	echo "created=$(date -u +%Y%m%dT%H%M%SZ)"
} >"$stage/MANIFEST.txt"
(cd "$stage" && sha256sum -- "$backup" reference.tar elevation.tar extracts.tar MANIFEST.txt >SHA256SUMS)
note "staged in $stage: $(du -sh "$stage" | cut -f1)"

if [ "$transfer" = 0 ]; then
	note "--no-transfer: nothing sent"
	exit 0
fi
# The old folder first, checksums included, and the new checksums last, so a folder whose
# upload stopped part way has no SHA256SUMS and the box refuses it rather than building
# from half of it (or from an earlier send's files).
aws_ s3 rm "$url/in/" --recursive --only-show-errors >/dev/null 2>&1 || true
aws_ s3 cp "$stage/" "$url/in/" --recursive --exclude SHA256SUMS --only-show-errors
aws_ s3 cp "$stage/SHA256SUMS" "$url/in/SHA256SUMS" --only-show-errors
note "sent to $url/in/"
note "next, on the box: scripts/cloud/box-rebuild.sh $url"
