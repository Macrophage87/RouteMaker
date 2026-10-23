#!/usr/bin/env bash
# Smoke test for the beta: health, a route, place search and reverse lookup, a stress tile,
# and (public mode) the gate: robots.txt, basic auth, noindex, the base map's same-origin rule
# and byte ranges, and Django's static files.
# Read-only: it only sends GET and one POST /api/route, which plans a short ride and saves nothing.
#
#   scripts/beta/smoke-test.sh --local [--port 8087] [--host NAME]
#       Straight to the api on 127.0.0.1, before nginx is involved. No credentials. The Host
#       header is --host, else RM_BETA_HOST from the environment or the checkout's .env, else
#       RM_CD_HOST (the deploy agent's override); the beta's name is server config, never in
#       the repository. auto-release.sh passes --host with the name its health check uses.
#   scripts/beta/smoke-test.sh --public https://beta.example.org --passwords-file ~/routemaker-beta-passwords.txt
#       Through nginx and TLS, as the first tester in the file make-htpasswd.sh wrote (or as
#       BETA_USER, if set). The password is read from that file, never printed, and handed to
#       curl on standard input, so it is in no process listing, history line or transcript.
#       BETA_USER=alice BETA_PASSWORD=... in the environment works too, without the file.
#   scripts/beta/smoke-test.sh --public https://beta.example.org --open
#       The same for a beta with no site password (the owner removed it, 2026-10-22): no
#       credentials, and the front end and the api must answer without them instead of 401.
#   --no-401-page
#       With --public, after the runbook's step 10 recovery (render-nginx.sh --no-401-page): skip
#       the check of the sign-in page's text, which nginx's own 401 page does not carry.
#
# Exit status 0 only if every check passed.
set -uo pipefail

mode=""; port=""; host=""; base=""; passwords_file=""; page401=1; open=0
while [ $# -gt 0 ]; do
	case "$1" in
		--local) mode=local; shift ;;
		--public) mode=public; base=${2:-}; [ -n "$base" ] || { echo "smoke-test: --public needs a URL" >&2; exit 2; }; shift 2 ;;
		--port) port=${2:-}; shift 2 ;;
		--host) host=${2:-}; shift 2 ;;
		--passwords-file) passwords_file=${2:-}; shift 2 ;;
		--no-401-page) page401=0; shift ;;
		--open) open=1; shift ;;
		-h | --help) sed -n '2,/^set -uo/p' "${BASH_SOURCE[0]}" | sed '$d' | sed 's/^# \{0,1\}//'; exit 0 ;;
		*) echo "smoke-test: unknown argument $1" >&2; exit 2 ;;
	esac
done
[ -n "$mode" ] || { echo "smoke-test: give --local or --public URL (--help)" >&2; exit 2; }
command -v curl >/dev/null 2>&1 || { echo "smoke-test: curl is required" >&2; exit 2; }

if [ "$mode" = local ]; then
	here=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
	if [ -z "$port" ]; then
		port=$(sed -n 's/^[[:space:]]*BETA_API_PORT[[:space:]]*=//p' "$here/../../.env" 2>/dev/null | tail -n 1 | tr -d '\r')
		port=${port:-8087}
	fi
	base="http://127.0.0.1:$port"
	[ -n "$host" ] || host=${RM_BETA_HOST:-}
	[ -n "$host" ] || host=$(sed -n 's/^[[:space:]]*RM_BETA_HOST[[:space:]]*=//p' "$here/../../.env" 2>/dev/null | tail -n 1 | tr -d "\r\"'")
	[ -n "$host" ] || host=${RM_CD_HOST:-}
	[ -n "$host" ] || { echo "smoke-test: no host: set RM_BETA_HOST=<the beta's name> in .env (docs/BETA-RUNBOOK.md, section 0), or pass --host" >&2; exit 2; }
fi
base=${base%/}

fails=0
ok() { printf 'PASS  %s\n' "$1"; }
bad() { printf 'FAIL  %s\n' "$1"; fails=$((fails + 1)); }

# curl wrapper: common options; credentials, when given, go in on stdin as a curl config.
curl_run() {
	local args=(--silent --show-error --max-time 90 -H "Host: $host")
	[ "$mode" = public ] && args=(--silent --show-error --max-time 90)
	if [ -n "${AUTH:-}" ] && [ -n "${BETA_USER:-}" ] && [ -n "${BETA_PASSWORD:-}" ]; then
		printf 'user = "%s:%s"\n' "$BETA_USER" "$BETA_PASSWORD" | curl -K - "${args[@]}" "$@"
	else
		curl "${args[@]}" "$@"
	fi
}

status() { curl_run -o /dev/null -w '%{http_code}' "$@"; }

check_status() { # description expected-code curl-args...
	local description=$1 expected=$2 got
	shift 2
	got=$(status "$@") || got="curl-failed"
	if [ "$got" = "$expected" ]; then ok "$description ($got)"; else bad "$description: expected $expected, got $got"; fi
}

check_body() { # description grep-pattern curl-args...
	local description=$1 pattern=$2 body
	shift 2
	body=$(curl_run "$@") || body=""
	if grep -Eq "$pattern" <<<"$body"; then ok "$description"; else bad "$description: no match for /$pattern/ in: ${body:0:200}"; fi
}

route='{"points":[[-77.0353,38.8895],[-77.0369,38.9072]],"preset":"default"}'

if [ "$mode" = public ] && [ -n "$passwords_file" ]; then
	[ -r "$passwords_file" ] || { echo "smoke-test: cannot read $passwords_file" >&2; exit 2; }
	# "user password" lines; the first one, or BETA_USER's. Read here, never echoed.
	if [ -z "${BETA_USER:-}" ]; then
		BETA_USER=$(awk '!/^#/ && NF == 2 { print $1; exit }' "$passwords_file")
	fi
	BETA_PASSWORD=$(awk -v u="${BETA_USER:-}" '!/^#/ && NF == 2 && $1 == u { print $2; exit }' "$passwords_file")
	export BETA_USER BETA_PASSWORD
fi

if [ "$mode" = public ]; then
	if [ "$open" = 0 ] && { [ -z "${BETA_USER:-}" ] || [ -z "${BETA_PASSWORD:-}" ]; }; then
		echo "smoke-test: give --passwords-file, or set BETA_USER and BETA_PASSWORD, for --public (or --open for a beta with no password)" >&2
		exit 2
	fi
	AUTH=
	check_status "robots.txt is public" 200 "$base/robots.txt"
	check_body "robots.txt disallows everything" 'Disallow: /' "$base/robots.txt"
	check_status "the account-deletion page is public" 200 "$base/delete-account"
	check_status "the privacy policy is public" 200 "$base/privacy"
	# POST only, so a GET reaching the api without a password is refused by the api (405), not 401.
	check_status "Garmin's deregistration notice reaches the api" 405 "$base/garmin/deregistrations"
	if [ "$open" = 1 ]; then
		check_status "the front end is open (no credentials; --open)" 200 "$base/"
		check_status "the api is open (no credentials; --open)" 200 "$base/healthz"
	else
		check_status "the front end is behind basic auth (no credentials)" 401 "$base/"
		check_status "the api is behind basic auth (no credentials)" 401 "$base/healthz"
		check_status "a wrong password is refused" 401 -u "nobody:wrong" "$base/"
		unauthorized=$(curl_run -D - -o /dev/null "$base/" | tr -d '\r')
		if grep -qi '^www-authenticate: basic' <<<"$unauthorized"; then ok "the 401 asks for a password (WWW-Authenticate: Basic)"; else bad "the 401 has no WWW-Authenticate: Basic, so browsers will not show their sign-in box"; fi
		if [ "$page401" = 1 ]; then
			check_body "the 401 page says how to get in" 'person who gave you access' "$base/"
		else
			printf 'SKIP  %s\n' "the 401 page's text (--no-401-page: the site was rendered without it)"
		fi
	fi
	headers=$(curl_run -I "$base/robots.txt" | tr -d '\r')
	if grep -qi '^x-robots-tag: noindex, nofollow' <<<"$headers"; then ok "X-Robots-Tag: noindex, nofollow on robots.txt"; else bad "no X-Robots-Tag on robots.txt"; fi
	check_status "plain http redirects to https" 301 "http://${base#https://}/"
	AUTH=1
fi

check_status "healthz" 200 "$base/healthz"
check_body "healthz says ok" '^ok' "$base/healthz"

if [ "$mode" = public ]; then
	check_body "the front end is served" '<div id="root">' "$base/"
	headers=$(curl_run -I "$base/" | tr -d '\r')
	grep -qi '^x-robots-tag: noindex' <<<"$headers" && ok "noindex on the front end" || bad "no X-Robots-Tag on the front end"
	grep -qi '^content-security-policy: default-src' <<<"$headers" && ok "CSP on the front end" || bad "no CSP on the front end"
	check_status "a preset link redirects" 302 "$base/mass-ride"
	# A satisfiable Range request on a static file is answered 206 Partial Content, which is
	# what the map's pmtiles reader asks for; 200 would mean nginx ignored the range.
	check_status "the base map for this site's own page (a byte range)" 206 -H "Referer: $base/" -H "Range: bytes=0-16383" "$base/basemap/region.pmtiles"
	check_status "the base map refused to a foreign page" 403 -H "Origin: https://example.org" "$base/basemap/region.pmtiles"
	check_status "an unlisted base map path is a 404" 404 -H "Referer: $base/" "$base/basemap/nope.txt"
	check_status "Django's static files are served (the admin's CSS, the /static/ alias)" 200 "$base/static/admin/css/base.css"
fi

check_body "a route comes back with a distance and a line" '"distance_m".*"geometry"|"geometry".*"distance_m"' \
	-X POST -H 'Content-Type: application/json' -H 'Accept: application/json' -d "$route" "$base/api/route"
check_body "place search finds Union Station" 'Union' "$base/api/geocode?q=union%20station&limit=5&lat=38.9&lon=-77.03"
check_status "a place name for a point (reverse)" 200 "$base/api/reverse?lat=38.8895&lon=-77.0353"
check_status "a stress tile (z12, central DC)" 200 "$base/tiles/stress/12/1171/1566.pbf"

echo
if [ "$fails" = 0 ]; then echo "smoke-test: all checks passed"; else echo "smoke-test: $fails check(s) FAILED"; fi
[ "$fails" = 0 ]
