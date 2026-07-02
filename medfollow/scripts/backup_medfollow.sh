#!/bin/sh
# Sauvegarde nocturne de Doctivo (base SQLite + pièces jointes).
# Sûr sous WAL : utilise `sqlite3 .backup` (copie cohérente), PAS un simple cp.
#
# Installation sur la VM (NE PAS déployer automatiquement — à faire à la main) :
#   sudo cp backup_medfollow.sh /usr/local/bin/ && sudo chmod +x /usr/local/bin/backup_medfollow.sh
#   crontab -e   →   15 2 * * * /usr/local/bin/backup_medfollow.sh >> /var/log/medfollow-backup.log 2>&1
#
# Restauration (à TESTER au moins une fois) :
#   sqlite3 /data/medfollow.db ".restore '/backup/medfollow/db/medfollow-YYYY-MM-DD.db'"
#   rsync -a /backup/medfollow/files/ /chemin/vers/medfollow/
set -eu

DB_PATH="${MEDFOLLOW_DATABASE_PATH:-/data/medfollow.db}"
APP_DIR="${MEDFOLLOW_APP_DIR:-/opt/medfollow}"
BACKUP_DIR="${MEDFOLLOW_BACKUP_DIR:-/backup/medfollow}"
RETENTION_DAYS="${MEDFOLLOW_BACKUP_RETENTION:-30}"
STAMP="$(date +%Y-%m-%d)"

mkdir -p "$BACKUP_DIR/db" "$BACKUP_DIR/files"

# 1) Base SQLite — copie cohérente même pendant que l'app tourne (WAL)
sqlite3 "$DB_PATH" ".backup '$BACKUP_DIR/db/medfollow-$STAMP.db'"

# 2) Pièces jointes : uploads/ (documents patients, papiers à en-tête)
#    et data/feuilles/ (instantanés HTML des feuilles de soins)
rsync -a --delete "$APP_DIR/uploads/" "$BACKUP_DIR/files/uploads/"
if [ -d "$APP_DIR/data/feuilles" ]; then
    rsync -a --delete "$APP_DIR/data/feuilles/" "$BACKUP_DIR/files/feuilles/"
fi

# 3) Rotation : supprime les sauvegardes DB plus vieilles que RETENTION_DAYS
find "$BACKUP_DIR/db" -name 'medfollow-*.db' -mtime "+$RETENTION_DAYS" -delete

# 4) IMPORTANT : $BACKUP_DIR doit être HORS de la VM (disque bloc séparé, ou
#    synchronisé vers un stockage objet). Exemple avec OCI Object Storage :
#    oci os object put --bucket-name medfollow-backups \
#        --file "$BACKUP_DIR/db/medfollow-$STAMP.db" --name "db/medfollow-$STAMP.db"

echo "OK $(date -u +%FT%TZ) — sauvegarde $STAMP terminée"
