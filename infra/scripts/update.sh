#!/usr/bin/env bash
# One-command deploy: sync to origin, rebuild, restart, clean up.
#
#   ./infra/scripts/update.sh
#
# Safe to run repeatedly. It does a HARD reset to origin/main — the correct
# action for a deploy box, which should always mirror GitHub exactly and never
# carry its own commits. Your .env is untouched (it is gitignored; reset --hard
# only affects tracked files). COMPOSE_FILE in .env means plain `docker compose`
# already includes the prod + searxng overlays.

# Re-exec from a stable copy so the `git reset` below cannot rewrite THIS script
# while bash is still reading it.
if [[ "${_APTIL_UPDATE_STABLE:-}" != "1" ]]; then
  cp "$0" /tmp/aptil-update.sh
  exec env _APTIL_UPDATE_STABLE=1 bash /tmp/aptil-update.sh "$@"
fi

set -euo pipefail
cd ~/aptil

echo "==> Syncing to origin/main (discards any local changes to tracked files)"
git fetch origin
git reset --hard origin/main

echo "==> Building and restarting the stack"
docker compose up -d --build --wait

echo "==> Reclaiming old image layers"
docker image prune -f

echo "==> Status"
docker compose ps
echo "==> Done."
