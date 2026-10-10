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
#   routemaker-<utc>.dump   the newest nightly backup under DATA_ROOT/backups. The box builds
#                           from this copy of the database, so the owner's access overrides,
#                           stress edits and Avoid junctions are all in its map.
#   reference.tar           DATA_ROOT/reference (crossings, urban areas, traffic counts)
#   elevation.tar           DATA_ROOT/elevation (saves the box the 3DEP download)
#   extracts.tar            DATA_ROOT/extracts (the box applies the same six-day rule to it)
#   MANIFEST.txt            run, commit, backup and read_at=<the backup's UTC time>
#   SHA256SUMS              one line per file, sent LAST: a folder without it is unfinished,
#                           and box-rebuild.sh refuses it
#
# READ-ONLY on the live stack: it reads DATA_ROOT and the checkout's git state and writes
# only under --stage (default ~/cloud-runs/<run>/in), which it refuses to place inside
# DATA_ROOT or the checkout. The tars are made with sudo because DATA_ROOT's directories
# belong to the containers' uid (10001); --numeric-owner keeps that owner for the box.
#
# Options:
#   --live-dir DIR   the live stack's checkout: .env and the commit [this repository]
#   --stage DIR      where the files are assembled [~/cloud-runs/<run>/in]
#   --profile NAME   the AWS CLI profile (`aws sso login --profile NAME` first)
#   --allow-dirty    send even though the checkout has uncommitted changes to tracked
#                    files (the box builds the commit, not those changes)
#   --no-transfer    assemble and checksum the stage, send nothing
#   -h, --help
# Environment (for tests): CLOUD_AWS [aws], CLOUD_SUDO [sudo], CLOUD_GIT [git].
set -Eeuo pipefail

die() { echo "send-inputs: $*" >&2; exit 2; }
note() { echo "send-inputs: $*"; }

here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
live_dir=$(cd "$here/../.." && pwd)
stage="" profile="" allow_dirty=0 transfer=1 url=""
while [ $# -gt 0 ]; do
	case "$1" in
		--live-dir) [ $# -ge 2 ] || die "$1 needs a value"; live_dir=$2; shift 2 ;;
		--stage) [ $# -ge 2 ] || die "$1 needs a value"; stage=$2; shift 2 ;;
		--profile) [ $# -ge 2 ] || die "$1 needs a value"; profile=$2; shift 2 ;;
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

commit=$("$GIT" -C "$live_dir" rev-parse HEAD) || die "$live_dir is not a git checkout"
if [ -n "$("$GIT" -C "$live_dir" status --porcelain --untracked-files=no)" ]; then
	[ "$allow_dirty" = 1 ] || die "$live_dir has uncommitted changes to tracked files; the box builds commit $commit without them. Commit them, or pass --allow-dirty"
	note "WARNING: uncommitted changes in $live_dir are not in the box's build"
fi
# The box clones from GitHub, so the commit has to be there.
[ -n "$("$GIT" -C "$live_dir" branch -r --contains "$commit" 2>/dev/null)" ] ||
	die "commit $commit is on no remote branch; push it first, or the box cannot check it out"

backup=""
for f in "$data_root"/backups/routemaker-*.dump; do
	[ -f "$f" ] || continue
	[[ "$(basename "$f")" =~ ^routemaker-[0-9]{8}T[0-9]{6}Z\.dump$ ]] || continue
	backup=$f   # the glob sorts, and the names sort by time
done
[ -n "$backup" ] || die "no backup under $data_root/backups (routemaker-<utc>.dump); the nightly backup writes one at 07:00 UTC"
read_at=$(basename "$backup" .dump); read_at=${read_at#routemaker-}
for part in reference elevation extracts; do
	[ -d "$data_root/$part" ] || die "$data_root/$part is missing"
done

[ -n "$stage" ] || stage="$HOME/cloud-runs/$run/in"
# Checked before anything is created, so a mistaken --stage never writes into DATA_ROOT.
stage=$(realpath -m "$stage")
case "$stage/" in
	"$(realpath -m "$data_root")"/* | "$(realpath -m "$live_dir")"/*)
		die "--stage $stage is inside DATA_ROOT or the checkout; put it elsewhere" ;;
esac
mkdir -p "$stage"
rm -f "$stage"/routemaker-*.dump "$stage"/*.tar "$stage/MANIFEST.txt" "$stage/SHA256SUMS"

note "backup $(basename "$backup") (database as of $read_at), commit $commit"
# The dump belongs to the containers' uid too, and may not be readable as you.
$SUDO cp "$backup" "$stage/"
$SUDO chown "$(id -u):$(id -g)" "$stage/$(basename "$backup")" 2>/dev/null || true
for part in reference elevation extracts; do
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
(cd "$stage" && sha256sum -- "$(basename "$backup")" reference.tar elevation.tar extracts.tar MANIFEST.txt >SHA256SUMS)
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
