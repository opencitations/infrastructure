# WordPress Backup System

This document describes the automated backup system for WordPress using rclone and pCloud storage. The system is designed to create daily backups of your WordPress installation and store them securely in pCloud.

## Overview

The backup system:
- Creates SQL dumps of the WordPress database
- Archives WordPress files
- Backs up raw MariaDB data
- Uploads everything to pCloud
- Automatically cleans up old backups

## Prerequisites

- Running WordPress installation in Kubernetes
- pCloud account
- rclone installed locally for configuration

## Configuration Steps

### 1. rclone Setup

Install rclone locally:
```bash
# Linux
sudo apt install rclone

# macOS
brew install rclone
```

Configure pCloud access:
```bash
rclone config

# Follow the interactive setup:
n) New remote
name> pcloud
Storage> pcloud
client_id> [leave empty]
client_secret> [leave empty]
token> [will be generated]
hostname> eapi.pcloud.com
```

Test your configuration:
```bash
rclone ls pcloud:
```

### 2. Environment Configuration

1. Generate base64-encoded rclone config:
```bash
cat ~/.config/rclone/rclone.conf | base64 -w 0
```

2. Add the following variables to your `.env` file:
```ini
# WordPress paths (adjust according to your setup)
WORDPRESS_SUBPATH=wordpress_prod
MARIADB_SUBPATH=mariadb_prod

# Backup configuration
BACKUP_SCHEDULE="0 2 * * *"          # Cron schedule
BACKUP_RETENTION_DAYS=90             # Days to keep backups
PCLOUD_BACKUP_FOLDER=backup/wordpress # pCloud destination
RCLONE_CONFIG=your_base64_encoded_config_here
```

### 3. Deployment

Deploy the backup system:
```bash
python3.11 ./deploy.py manifests/04-wordpress-backup.yaml
```

## Monitoring and Management

### View Backup Status

Check scheduled backups:
```bash
kubectl get cronjob wordpress-backup
```

List backup jobs:
```bash
kubectl get jobs
```

View backup logs:
```bash
# Latest backup logs
kubectl logs -l app=wordpress-backup

# Specific job logs
kubectl logs job/wordpress-backup-<timestamp>
```

### Manual Backup

Create a manual backup:
```bash
kubectl create job --from=cronjob/wordpress-backup manual-backup-$(date +%s)
```

### Clean Up Old Jobs

Remove completed jobs:
```bash
kubectl delete jobs -l app=wordpress-backup
```

## Backup Contents

Each backup includes:
1. SQL dump of the WordPress database
2. Archive of WordPress files
3. Archive of MariaDB data files
4. Combined archive containing all of the above

## Backup Location

Backups are stored in:
- Temporary local storage: `/mnt/nfs/wp-backup/`
- pCloud: `PCLOUD_BACKUP_FOLDER` setting (e.g., `backup/wordpress/`)

## Troubleshooting

### Common Issues

1. rclone Authentication Errors:
```bash
# Check rclone config
kubectl describe secret pcloud-config
# Verify the config is correctly base64-encoded
```

2. Backup Path Errors:
```bash
# Verify NFS paths
kubectl exec -it <pod-name> -- ls -la /mnt/nfs
```

3. Database Connection Issues:
```bash
# Check MariaDB service
kubectl get svc mariadb
# Test database connection
kubectl exec -it <pod-name> -- mysql -h mariadb.default.svc.cluster.local -u wp_user -p
```

### Checking Backup Files

In pCloud:
```bash
# List backups
rclone ls pcloud:backup/wordpress

# Download specific backup
rclone copy pcloud:backup/wordpress/full_backup_20240101_020000.tar.gz ./
```

### Resource Usage

The backup job is configured with the following resources:
```yaml
resources:
  requests:
    memory: "256Mi"
    cpu: "200m"
  limits:
    memory: "1Gi"
    cpu: "1"
```

Adjust these values in the manifest if needed for your environment.

## Restore Procedure

While automatic restoration is not implemented, you can restore manually:

1. Download the backup:
```bash
rclone copy pcloud:backup/wordpress/full_backup_YYYYMMDD_HHMMSS.7z ./
```

2. Extract the backup:
```bash
tar xzf full_backup_YYYYMMDD_HHMMSS.7z
```

3. Restore components as needed:
   - `db_dump_YYYYMMDD_HHMMSS.sql`: Database dump
   - `wp_backup_YYYYMMDD_HHMMSS.7z`: WordPress files
   - `db_files_YYYYMMDD_HHMMSS.7z`: Raw database files

For detailed restoration steps, consult the WordPress and MariaDB documentation.
