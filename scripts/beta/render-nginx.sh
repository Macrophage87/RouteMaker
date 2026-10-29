#!/bin/sh
# Renders deploy/beta/nginx-routemaker.conf.template into an nginx site file.
#
# It only prints (or writes the file named by --out). It never touches /etc, never
# runs nginx, and never reads a secret: the htpasswd FILE is named, not read.
#
#   render-nginx.sh --stage acme [--out FILE]
#       Port 80 only, answering the ACME challenge. For before a certificate exists.
#   render-nginx.sh --stage full --cert-fullchain F --cert-key K [--out FILE | --diff FILE]
#       The whole site: 80 redirects to 443, 443 serves the beta.
#
# The site's shape is remembered as settings (exported, as vars.sh does, or else a line in .env),
# so a re-render after a template change needs only --stage full (and --diff against the
# installed file to see the change first):
#   BETA_SITE_PASSWORD=0      as --no-password        BETA_NGINX_IPV6=0   as --no-ipv6
#   BETA_NGINX_401_PAGE=0     as --no-401-page
#   RM_CERT_FULLCHAIN, RM_CERT_KEY, BETA_NGINX_TLS_INCLUDE
#                             as --cert-fullchain, --cert-key, --tls-options-include
# A flag given on the command line wins. Each switch is 1 (the default) or 0.
#
# Options (defaults in brackets; RM_BETA_HOST, DATA_ROOT and BETA_API_PORT are read out of
# .env by sed, never by sourcing it):
#   --server-name NAME       [RM_BETA_HOST from .env; required: the beta's name is server
#                            config, never in the repository]
#   --api-port N             [BETA_API_PORT from .env, else 8087]
#   --data-root PATH         [DATA_ROOT from .env, else /data/routemaker]
#   --htpasswd FILE          [/etc/nginx/routemaker-beta.htpasswd]
#   --acme-root PATH         [/var/www/routemaker-acme]
#   --tls-options-include F  an nginx file to include in the 443 server, such as
#                            certbot's /etc/letsencrypt/options-ssl-nginx.conf
#   --env-file FILE          [<repo>/.env]
#   --diff FILE              print `diff -u FILE <the rendering>` instead of the rendering, and
#                            exit 0 if they are the same, 1 if not (FILE is the installed site)
#   --no-ipv6                drop the `listen [::]:...` lines (for a host whose other
#                            sites do not listen on IPv6; docs/BETA-RUNBOOK.md, step 1)
#   --no-password            no site password (the owner opened the beta, 2026-10-22): leave out
#                            the gate's auth_basic lines and the sign-in page (error_page 401 and
#                            its location); robots.txt, noindex and the "back soon" page stay
#   --no-401-page            leave out the sign-in page (error_page 401 and its location), so
#                            Cancel shows nginx's own 401 page: the runbook's recovery when nginx
#                            cannot read deploy/beta/401.html (step 10). The "back soon" page
#                            (error_page 502, deploy/beta/502.html) is read from the same
#                            directory, so it goes too and a 502 is nginx's own again.
set -eu

die() { echo "render-nginx: $*" >&2; exit 2; }

here=$(cd "$(dirname "$0")" && pwd)
repo=$(cd "$here/../.." && pwd)
template="$repo/deploy/beta/nginx-routemaker.conf.template"
[ -r "$template" ] || die "cannot read $template"

stage=""; out=""; server_name=""; api_port=""; data_root=""
htpasswd="/etc/nginx/routemaker-beta.htpasswd"; acme_root="/var/www/routemaker-acme"
cert_fullchain=""; cert_key=""; tls_include=""; env_file="$repo/.env"

diff_file=""
ipv6=""
page401=""
password=""
while [ $# -gt 0 ]; do
	if [ "$1" = --no-ipv6 ]; then ipv6=0; shift; continue; fi
	if [ "$1" = --no-401-page ]; then page401=0; shift; continue; fi
	if [ "$1" = --no-password ]; then password=0; shift; continue; fi
	[ $# -ge 2 ] || die "$1 needs a value"
	case "$1" in
		--stage) stage=$2 ;;
		--out) out=$2 ;;
		--server-name) server_name=$2 ;;
		--api-port) api_port=$2 ;;
		--data-root) data_root=$2 ;;
		--htpasswd) htpasswd=$2 ;;
		--acme-root) acme_root=$2 ;;
		--cert-fullchain) cert_fullchain=$2 ;;
		--cert-key) cert_key=$2 ;;
		--tls-options-include) tls_include=$2 ;;
		--env-file) env_file=$2 ;;
		--diff) diff_file=$2 ;;
		*) die "unknown option $1" ;;
	esac
	shift 2
done

case "$stage" in acme | full) ;; *) die "--stage acme|full is required" ;; esac

env_value() { # the last KEY= line of the env file, quotes stripped, never evaluated
	[ -r "$env_file" ] || return 0
	sed -n "s/^[[:space:]]*$1[[:space:]]*=//p" "$env_file" | tail -n 1 | tr -d '\r' | sed "s/^['\"]//; s/['\"]\$//"
}

[ -n "$server_name" ] || server_name=$(env_value RM_BETA_HOST)
[ -n "$server_name" ] ||
	die "no server name: set RM_BETA_HOST=<the beta's name> in $env_file (docs/BETA-RUNBOOK.md, section 0), or pass --server-name"
[ -n "$api_port" ] || api_port=$(env_value BETA_API_PORT)
[ -n "$api_port" ] || api_port=8087
[ -n "$data_root" ] || data_root=$(env_value DATA_ROOT)
[ -n "$data_root" ] || data_root=/data/routemaker

setting() { # key: from the environment (vars.sh), else from .env
	printenv "$1" 2>/dev/null || env_value "$1"
}
switch() { # flag-value key: the flag, else the setting, else on; prints 1 or 0
	[ -z "$1" ] || { echo "$1"; return 0; }
	case "$(setting "$2")" in
		'' | 1) echo 1 ;;
		0) echo 0 ;;
		*) die "$2 (in the environment or $env_file) must be 1 or 0" ;;
	esac
}
password=$(switch "$password" BETA_SITE_PASSWORD)
ipv6=$(switch "$ipv6" BETA_NGINX_IPV6)
page401=$(switch "$page401" BETA_NGINX_401_PAGE)
[ -n "$cert_fullchain" ] || cert_fullchain=$(setting RM_CERT_FULLCHAIN)
[ -n "$cert_key" ] || cert_key=$(setting RM_CERT_KEY)
[ -n "$tls_include" ] || tls_include=$(setting BETA_NGINX_TLS_INCLUDE)

safe() { # name value: a word with no space, quote, brace, semicolon, backslash or @
	case "$2" in
		'' | *[!A-Za-z0-9._/:-]*) die "$1 has a character this renderer will not put in an nginx file: '$2'" ;;
	esac
}
safe server-name "$server_name"
safe api-port "$api_port"
safe data-root "$data_root"
safe htpasswd "$htpasswd"
safe acme-root "$acme_root"
# The sign-in and "back soon" pages (deploy/beta/401.html, 502.html) are served from this
# checkout; nginx must be able to read them.
pages_dir="$repo/deploy/beta"
safe pages-dir "$pages_dir"
for page in 401.html 502.html; do
	[ "$page401" = 0 ] || [ -r "$pages_dir/$page" ] || die "cannot read $pages_dir/$page (or render with --no-401-page)"
done
case "$api_port" in *[!0-9]*) die "--api-port must be a number" ;; esac
case "$data_root" in /?*) ;; *) die "--data-root must be an absolute path" ;; esac
case "$data_root" in / | /etc | /usr | /var | /home | /root | /data) die "--data-root '$data_root' is not a RouteMaker directory" ;; esac

if [ "$stage" = full ]; then
	[ -n "$cert_fullchain" ] && [ -n "$cert_key" ] || die "--stage full needs --cert-fullchain and --cert-key"
	safe cert-fullchain "$cert_fullchain"
	safe cert-key "$cert_key"
	[ -z "$tls_include" ] || safe tls-options-include "$tls_include"
fi

# The server name as a regular expression (dots escaped), with the backslashes doubled once
# more so that sed's replacement side writes them out literally.
name_re=$(printf '%s' "$server_name" | sed 's/\./\\\\./g')

keep_stage() { # print the template with the other stage's section removed, and the marker lines
	awk -v keep="$stage" '
		/^# BEGIN stage:/ { split($0, a, ":"); in_section = 1; wanted = (a[2] == keep); next }
		/^# END stage:/ { in_section = 0; next }
		{ if (!in_section || wanted) print }
	' "$template"
}

git_sha=$(git -C "$repo" rev-parse --short=12 HEAD 2>/dev/null || echo unknown)
rendered_from="Rendered by scripts/beta/render-nginx.sh (stage $stage) from deploy/beta/nginx-routemaker.conf.template at git $git_sha. Edit the template and re-render; do not edit this file by hand."

rendered=$(keep_stage | grep -v '^# TEMPLATE: ' | sed \
	-e "s|@RENDERED_FROM@|$rendered_from|g" \
	-e "s|@SERVER_NAME_RE@|$name_re|g" \
	-e "s|@SERVER_NAME@|$server_name|g" \
	-e "s|@API_PORT@|$api_port|g" \
	-e "s|@DATA_ROOT@|$data_root|g" \
	-e "s|@HTPASSWD_FILE@|$htpasswd|g" \
	-e "s|@ACME_ROOT@|$acme_root|g" \
	-e "s|@PAGES_DIR@|$pages_dir|g" \
	-e "s|@CERT_FULLCHAIN@|$cert_fullchain|g" \
	-e "s|@CERT_KEY@|$cert_key|g")

if [ "$ipv6" = 0 ]; then
	rendered=$(printf '%s\n' "$rendered" | grep -vF 'listen [::]')
fi

if [ "$page401" = 0 ]; then
	# the error_page lines, and each page's location from its opening line to its closing brace
	rendered=$(printf '%s\n' "$rendered" | awk '
		/^[[:space:]]*error_page (401|502) / { next }
		/^[[:space:]]*location = \/rmbeta-(401|502)\.html \{/ { skip = 1; next }
		skip && /^[[:space:]]*\}[[:space:]]*$/ { skip = 0; next }
		!skip { print }
	')
fi

if [ "$password" = 0 ]; then
	# the gate's password (the locations' own `auth_basic off;` lines are harmless without it),
	# and the sign-in page that only a 401 shows
	rendered=$(printf '%s\n' "$rendered" | awk '
		/^[[:space:]]*auth_basic[[:space:]]+"/ { next }
		/^[[:space:]]*auth_basic_user_file[[:space:]]/ { next }
		/^[[:space:]]*error_page 401 / { next }
		/^[[:space:]]*location = \/rmbeta-401\.html \{/ { skip = 1; next }
		skip && /^[[:space:]]*\}[[:space:]]*$/ { skip = 0; next }
		!skip { print }
	')
fi

if [ -n "$tls_include" ]; then
	rendered=$(printf '%s\n' "$rendered" | sed "s|@TLS_OPTIONS_INCLUDE@|include $tls_include;|")
else
	rendered=$(printf '%s\n' "$rendered" | sed '/@TLS_OPTIONS_INCLUDE@/d')
fi

if printf '%s\n' "$rendered" | grep -n '@[A-Z_]*@' >&2; then
	die "unfilled placeholders remain (listed above)"
fi

if [ -n "$diff_file" ]; then
	[ -z "$out" ] || die "--diff and --out are one or the other"
	[ -r "$diff_file" ] || die "cannot read $diff_file"
	printf '%s\n' "$rendered" | diff -u "$diff_file" - && echo "render-nginx: no change from $diff_file" >&2
	exit $?
elif [ -n "$out" ]; then
	[ ! -e "$out" ] || [ -n "${RENDER_NGINX_FORCE:-}" ] || die "$out exists; remove it or set RENDER_NGINX_FORCE=1"
	printf '%s\n' "$rendered" >"$out"
	echo "render-nginx: wrote $out (stage $stage)" >&2
else
	printf '%s\n' "$rendered"
fi
