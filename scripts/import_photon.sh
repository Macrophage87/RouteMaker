#!/bin/bash
# Build the geocoder's index from GraphHopper's US Photon dump, trimmed to the
# coverage box (PLAN.md:60).
#
#     scripts/import_photon.sh DUMP INDEX_DIR
#
# DUMP is photon-dump-usa-1.0-latest.jsonl.zst, already downloaded, with its
# .md5 beside it (GraphHopper publishes one, and it is part of the approved
# download); without it the import stops. This script downloads nothing:
# the owner approved that one file (PLAN.md:65, amendment of 2026-09-27; from
# https://download1.graphhopper.com/public/north-america/usa/), and fetching it
# is the operator's step in docs/DEPLOYMENT.md, "Photon".
#
# INDEX_DIR must not exist yet; the index is written there, and serving it is
# pointing ${DATA_ROOT}/photon at it (the monthly refresh in the same section
# does exactly that). Nothing here touches a running stack.
#
# What it runs is the pinned photon image's own Photon (1.3.0 in
# rtuszik/photon-docker:2.4.0), with the image's download machinery bypassed:
# scripts/photon_trim.py streams the dump through the image's python and keeps
# the lines inside BBOX, and `photon.jar import -import-file` reads what it
# kept. Photon's importer has no box filter of its own; `-country-codes` is the
# finest it offers, and the dump is one country. The two run one after the
# other, not in a pipe: the trim is a single core decompressing ~80 GB for
# about 24 minutes (1,416 s measured), and Photon's embedded OpenSearch, starved beside it on a
# busy host, let a bulk request run past its fixed 30 s client timeout and the
# import failed (twice, 2026-09-27). The trimmed file (about 5 GB for this box)
# is deleted once the import succeeds; a failed import is run again on it by
# running this again with the same INDEX_DIR.
#
# Names are imported in English only (`-languages en`, settings.PHOTON_LANGUAGES),
# with the local name kept as the default; that is the one language the API
# lets a search ask for.

set -euo pipefail

IMAGE="docker.io/rtuszik/photon-docker:2.4.0"
# settings.COVERAGE_BBOX, west,south,east,north; tests/test_photon_trim.py holds
# the two equal.
BBOX="-78.0,38.2,-76.02,39.72"
LANGUAGES="en"
# The import's heap. The container is capped at the serving limit (3 GB,
# PLAN.md:60), so the import proves the index fits the box it will run in.
JAVA_HEAP="${PHOTON_IMPORT_HEAP:-1536m}"
THREADS="${PHOTON_IMPORT_THREADS:-1}"

if [ "$#" -ne 2 ]; then
	echo "usage: $0 DUMP INDEX_DIR" >&2
	exit 64
fi
dump=$(readlink -f "$1")
index=$2
repo=$(cd "$(dirname "$0")/.." && pwd)

if [ ! -f "$dump" ]; then
	echo "no dump at $dump" >&2
	exit 66
fi
case "$(basename "$dump")" in
photon-dump-*-1.0-*.jsonl.zst) ;;
*)
	echo "expected a Photon 1.0 JSON dump (photon-dump-usa-1.0-latest.jsonl.zst), got $dump" >&2
	exit 65
	;;
esac
resume=false
if [ -e "$index" ]; then
	if [ -f "$index/trimmed.done" ]; then
		# A run whose trim finished and whose import did not: the import is
		# run again on what was kept, rather than the ~80 GB pass repeated.
		echo "$index holds a finished trim; running the import again on it"
		resume=true
	else
		echo "$index exists; the index is built into a new directory" >&2
		exit 73
	fi
fi

if [ "$resume" = false ]; then
	if [ -f "$dump.md5" ]; then
		echo "checking $(basename "$dump") against its .md5"
		(cd "$(dirname "$dump")" && md5sum -c "$(basename "$dump").md5")
	else
		echo "no $dump.md5 beside the dump; fetch it with the dump (docs/DEPLOYMENT.md, Photon)" >&2
		exit 66
	fi
fi

mkdir -p "$index"
index=$(readlink -f "$index")
started=$(date +%s)

# As the image's root, since /photon (and the jar in it) is readable by the
# image's photon user alone; the index is handed to the invoking user at the
# end, so whoever ran this owns it. The serving image's entrypoint re-owns
# /photon/data to its own uid when it starts.
#
# `--memory-swap` equal to `--memory`: no swap for this container. On a host
# short of memory the kernel otherwise swaps out the JVM's heap, every
# collection then waits on the disk, and a bulk request runs past Photon's
# fixed 30 s client timeout - which is how the first three imports here
# failed (2026-09-27, host swap full). The high CPU weight asks the kernel to
# favour this container over others on a busy host (an IO weight is not
# settable on every cgroup setup, this WSL host's included).
docker run --rm \
	--name "photon-import-$$" \
	--memory 3g --memory-swap 3g \
	--cpu-shares 4096 \
	--network none \
	--entrypoint /bin/bash \
	-v "$(dirname "$dump")":/in:ro \
	-v "$repo/scripts/photon_trim.py":/opt/photon_trim.py:ro \
	-v "$index":/photon/data \
	"$IMAGE" -c "set -euo pipefail
		trap 'chown -R $(id -u):$(id -g) /photon/data' EXIT
		if [ ! -f /photon/data/trimmed.done ]; then
			start=\$(date +%s)
			/photon/.venv/bin/python /opt/photon_trim.py '/in/$(basename "$dump")' --bbox='$BBOX' \
				> /photon/data/trimmed.jsonl
			touch /photon/data/trimmed.done
			echo \"trimmed in \$((\$(date +%s) - start)) s: \$(du -h /photon/data/trimmed.jsonl | cut -f1)\"
		fi
		rm -rf /photon/data/photon_data
		start=\$(date +%s)
		java -Xms$JAVA_HEAP -Xmx$JAVA_HEAP -jar /photon/photon.jar import \
			-import-file /photon/data/trimmed.jsonl -data-dir /photon/data \
			-languages $LANGUAGES -j $THREADS
		echo \"Photon import took \$((\$(date +%s) - start)) s\"
		rm -f /photon/data/trimmed.jsonl /photon/data/trimmed.done" \
	</dev/null

echo "done in $(($(date +%s) - started)) s; index $(du -sh "$index" | cut -f1) at $index"
