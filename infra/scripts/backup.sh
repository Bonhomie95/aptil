#!/usr/bin/env bash
# Nightly backup of MongoDB + MinIO. Point BACKUP_DIR at durable storage.
set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-./backups}"
RETENTION_DAYS="${RETENTION_DAYS:-14}"
STAMP="$(date +%Y%m%d-%H%M%S)"
COMPOSE="docker compose -f docker-compose.yml -f docker-compose.prod.yml"

# Load MONGO_DB / MINIO_* from .env without leaking them into the log.
if [[ -f .env ]]; then
  set -a
  # shellcheck disable=SC1091
  source .env
  set +a
fi

mkdir -p "$BACKUP_DIR"

echo "==> Dumping MongoDB"
$COMPOSE exec -T mongo mongodump --db "${MONGO_DB:-aptil}" --archive --gzip \
  > "$BACKUP_DIR/mongo-$STAMP.archive.gz"

# The previous version claimed to back up MinIO and only backed up Mongo, so a
# restore would have come back with every CV and generated résumé missing.
echo "==> Mirroring MinIO bucket"
MINIO_ARCHIVE="$BACKUP_DIR/minio-$STAMP.tar.gz"
$COMPOSE exec -T \
  -e MC_HOST_local="http://${MINIO_ROOT_USER}:${MINIO_ROOT_PASSWORD}@localhost:9000" \
  minio sh -c "mc mirror --quiet local/${MINIO_BUCKET:-aptil-uploads} /tmp/backup >/dev/null 2>&1 \
    && tar -czf - -C /tmp backup && rm -rf /tmp/backup" \
  > "$MINIO_ARCHIVE"

echo "==> Pruning backups older than ${RETENTION_DAYS} days"
find "$BACKUP_DIR" -name 'mongo-*.archive.gz' -mtime "+${RETENTION_DAYS}" -delete
find "$BACKUP_DIR" -name 'minio-*.tar.gz' -mtime "+${RETENTION_DAYS}" -delete

echo "==> Done:"
ls -lh "$BACKUP_DIR/mongo-$STAMP.archive.gz" "$MINIO_ARCHIVE"

cat <<'NOTE'

Restore:
  MongoDB: docker compose exec -T mongo mongorestore --gzip --archive < mongo-<stamp>.archive.gz
  MinIO:   tar -xzf minio-<stamp>.tar.gz && mc mirror backup/ local/<bucket>
NOTE
