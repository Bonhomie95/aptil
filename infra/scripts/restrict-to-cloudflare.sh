#!/usr/bin/env bash
# Allow only Cloudflare to reach the published container ports (80/443).
#
# Why DOCKER-USER and not ufw: Docker writes its own iptables rules into
# FORWARD/DOCKER ahead of ufw's chains, so `ufw deny 80` silently does nothing
# to a published container port. DOCKER-USER is the one chain Docker guarantees
# it will not clobber and evaluates before its own rules.
#
# SSH is NOT affected. Port 22 is a host socket and never traverses DOCKER-USER,
# so a mistake here takes the website down, never your shell.
#
#   sudo ./restrict-to-cloudflare.sh apply     # fetch ranges + install rules
#   sudo ./restrict-to-cloudflare.sh status    # show what is installed
#   sudo ./restrict-to-cloudflare.sh remove    # undo, back to open 80/443
set -euo pipefail

CHAIN=CF-ONLY
CACHE=/etc/cloudflare-ips
PORTS=80,443

[[ $EUID -eq 0 ]] || { echo "ERROR: run with sudo" >&2; exit 1; }

# The interface that carries default-route traffic. Matching on it keeps
# container-to-container and host-originated traffic out of these rules.
IFACE="$(ip route get 1.1.1.1 2>/dev/null | awk '{for(i=1;i<=NF;i++) if($i=="dev") {print $(i+1); exit}}')"
[[ -n "$IFACE" ]] || { echo "ERROR: could not determine the external interface" >&2; exit 1; }

fetch_ranges() {
  mkdir -p "$CACHE"
  local ok=1
  for v in 4 6; do
    if curl -fsS --max-time 20 "https://www.cloudflare.com/ips-v$v" -o "$CACHE/v$v.txt.new" \
       && [[ -s "$CACHE/v$v.txt.new" ]]; then
      mv "$CACHE/v$v.txt.new" "$CACHE/v$v.txt"
    else
      rm -f "$CACHE/v$v.txt.new"
      # A failed refresh must never widen access — keep the cached list.
      [[ -s "$CACHE/v$v.txt" ]] || ok=0
      echo "WARN: could not refresh IPv$v ranges; using cached copy" >&2
    fi
  done
  [[ $ok -eq 1 ]] || { echo "ERROR: no Cloudflare ranges available" >&2; exit 1; }
}

build() {           # build <iptables-cmd> <ranges-file>
  local ipt="$1" file="$2"
  command -v "$ipt" >/dev/null || return 0
  "$ipt" -L DOCKER-USER -n >/dev/null 2>&1 || {
    echo "note: $ipt has no DOCKER-USER chain (Docker not using it) — skipping" >&2
    return 0
  }
  "$ipt" -N "$CHAIN" 2>/dev/null || "$ipt" -F "$CHAIN"
  local n=0
  # `|| [[ -n "$cidr" ]]` is load-bearing: Cloudflare serves these files with no
  # trailing newline, so a bare `while read` silently drops the LAST range —
  # which cost 131.0.72.0/22 and 2c0f:f248::/32 the first time this ran.
  while read -r cidr || [[ -n "$cidr" ]]; do
    cidr="${cidr//[$'\r\t ']/}"
    [[ -n "$cidr" ]] || continue
    "$ipt" -A "$CHAIN" -s "$cidr" -j RETURN     # RETURN = allowed, fall through
    n=$((n+1))
  done < "$file"
  # A truncated list is worse than no list: it silently blackholes a slice of
  # real visitors. Cloudflare has published 15 v4 / 7 v6 ranges for years.
  local min=6
  [[ "$ipt" == iptables ]] && min=15
  if (( n < min )); then
    echo "ERROR: only $n ranges parsed from $file (expected >= $min) — refusing" >&2
    "$ipt" -F "$CHAIN"; exit 1
  fi
  "$ipt" -A "$CHAIN" -j DROP                    # anything else, silently dropped
  # Hook it in at position 1, only for new traffic to 80/443 off the wire.
  "$ipt" -C DOCKER-USER -i "$IFACE" -p tcp -m multiport --dports "$PORTS" -j "$CHAIN" 2>/dev/null \
    || "$ipt" -I DOCKER-USER 1 -i "$IFACE" -p tcp -m multiport --dports "$PORTS" -j "$CHAIN"
  echo "  $ipt: $n Cloudflare ranges allowed on $PORTS via $IFACE"
}

teardown() {
  local ipt="$1"
  command -v "$ipt" >/dev/null || return 0
  while "$ipt" -C DOCKER-USER -i "$IFACE" -p tcp -m multiport --dports "$PORTS" -j "$CHAIN" 2>/dev/null; do
    "$ipt" -D DOCKER-USER -i "$IFACE" -p tcp -m multiport --dports "$PORTS" -j "$CHAIN"
  done
  "$ipt" -F "$CHAIN" 2>/dev/null || true
  "$ipt" -X "$CHAIN" 2>/dev/null || true
}

case "${1:-apply}" in
  apply)
    fetch_ranges
    echo "Restricting ports $PORTS on $IFACE to Cloudflare:"
    build iptables  "$CACHE/v4.txt"
    build ip6tables "$CACHE/v6.txt"
    echo "Done. SSH (port 22) is untouched."
    ;;
  status)
    echo "== interface: $IFACE =="
    for ipt in iptables ip6tables; do
      command -v "$ipt" >/dev/null || continue
      echo "== $ipt DOCKER-USER =="; "$ipt" -L DOCKER-USER -n --line-numbers 2>/dev/null || true
      echo "== $ipt $CHAIN =="; "$ipt" -L "$CHAIN" -n 2>/dev/null || echo "  (not installed)"
    done
    ;;
  remove)
    teardown iptables; teardown ip6tables
    echo "Removed. Ports $PORTS are open to the internet again."
    ;;
  *) echo "usage: $0 [apply|status|remove]" >&2; exit 2 ;;
esac
