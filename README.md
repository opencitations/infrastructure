# OpenCitations Kubernetes Infrastructure

This repository contains the Kubernetes manifests and deployment tools for deploying and managing OpenCitations services on a Kubernetes cluster. To begin working with this infrastructure, you'll need to either clone or fork this repository to your own GitHub account.

## Prerequisites

- Python 3.11
- Running Kubernetes cluster with kubectl configured
- Helm package manager
- Git (for Fleet integration)
- Storage system (NFS or alternative)

## Installation Steps

### 1. Database Preparation

Before beginning the deployment, you must prepare the OpenCitations databases:

1. Download the Meta and Index databases from https://opencitations.net/download
2. Place these databases in your storage system that will be used by the infrastructure
3. Make note of the storage paths as they will be needed in the configuration

### 2. Environment Configuration

Create and configure your environment file:

```bash
cp .env.example .env
```

Edit the `.env` file with your specific configurations for services, infrastructure, and Git integration.

### 3. Storage Configuration

#### For NFS Storage:
1. Edit `preliminary/00-secrets.yaml` with your NFS configuration
2. Modify `preliminary/02-storage.yaml` with your NFS paths and settings
3. Ensure the following variables are properly set in `.env`:
   - `NFS_SERVER`
   - `NFS_CERT_PATH`
   - `NFS_DATA_PATH`
   - `NFS_LOG_PATH`
   - `NFS_LOG_TRAEFIK_SUBPATH`

#### For Alternative Storage:
1. Modify both `preliminary/00-secrets.yaml` and `preliminary/02-storage.yaml` to match your storage system's requirements
2. Update the corresponding storage variables in `.env`

### 4. Traefik Configuration

1. Edit `preliminary/03-traefik-values.yaml`:
   - Modify `additionalArguments` section for HTTPS certificate configuration
   - If not using MetalLB, for instance in a Cloud environment, remove the MetalLB-specific configurations

### 5. Domain Configuration

Update the domain addresses in .env configuration file:
- Web service manifests
- API service manifests
- Any other services with web addresses

### 6. Services system requirements

Configure your service requirements in the `.env` file. Each service has specific resource needs that should be adjusted based on your infrastructure capacity.

Important considerations:
- CPU and memory requests should be set according to your cluster's available resources
- Storage sizes should accommodate your data requirements plus growth
- Service versions should match your deployment requirements
- Ports should be available and not conflict with other services

### 7. WordPress Configuration (OPTIONAL)

The OpenCitations infrastructure currently features a showcase website developed on WordPress. To set up a showcase site using this same technological approach, uncomment the 03 and 04 YAML sections and update the WordPress configuration parameters specified in the .env file.

The infrastructure includes an automated backup system for WordPress using rclone and pCloud storage (YAML 04). The system performs daily backups of:
- WordPress database (SQL dump)
- WordPress files
- MariaDB raw data

Configure the backup system by setting the appropriate variables in your `.env`:
```ini
WORDPRESS_SUBPATH=wordpress_prod
MARIADB_SUBPATH=mariadb_prod
BACKUP_SCHEDULE="0 2 * * *"
BACKUP_RETENTION_DAYS=90
PCLOUD_BACKUP_FOLDER=backup/wordpress
RCLONE_CONFIG=your_base64_encoded_config
```

If you install WordPress and/or the backup system, remove the `_OPTIONAL` suffix from the file names.

WP backup info ---> docs/wp-backup.md
Redis token implementation info ---> docs/oc-api-token.md

### 8. Fleet Integration

Fleet provides automated deployment capabilities through Git repository monitoring.

#### Fleet Repository Setup

1. Create a **private** Git repository for your production manifests
2. Configure Fleet variables in `.env`:
```bash
PRIVATE_REPO_URL=https://github.com/your-org/your-repo
GIT_USERNAME=your-username
GIT_TOKEN=your-personal-access-token
```

#### Fleet Configuration in Rancher

##### If using Rancher:

1. Navigate to Rancher UI → Continuous Delivery
2. Create a new Git Repository with:
   - Name: opencitations-fleet
   - Repository URL: Your private repository URL
   - Branch: main
   - Paths: ./ (root directory)
   - Target cluster: Your cluster name

##### If using standalone Fleet:

1. Create a Fleet configuration file `fleet.yaml`:
```yaml
namespace: opencitations
targetCustomizations:
  - name: production
    clusterSelector:
      matchLabels:
        environment: production
```

2. Apply the configuration:
```bash
kubectl apply -f fleet.yaml
```

### 9. Deployment

Install Python dependencies:
```bash
pip3.11 install -r requirements.txt
```

The deployment script (`deploy.py`) provides several options:

```bash
python3.11 ./deploy.py -i    # Initialize infrastructure
python3.11 ./deploy.py -p    # Preview manifest or preliminary files with variable substitution
python3.11 ./deploy.py -f    # Create Fleet-ready production files
python3.11 ./deploy.py       # Deploy all services
python3.11 ./deploy.py <manifests/0x-manifest.yaml>  # Deploy a specific manifest file
```

#### Initialize Infrastructure

#### Initialize Infrastructure

The first time you deploy, you'll need to initialize the infrastructure by deploying all manifests in the `preliminary` folder.  Use the `-i` switch with the `deploy.py` script to do this:

```bash
./deploy.py -i
```

This will guide you through:
1. Creating Kubernetes secrets
2. Setting up MetalLB (if used)
3. Configuring storage
4. Installing Traefik
5. Setting up the Traefik dashboard (optional)

#### Preview Configuration
```bash
python3.11 ./deploy.py -p <manifests/0x-manifest.yaml>  # Preview how variables will be substituted
```
This allows you to verify your configuration before deployment by showing how environment variables will be substituted in your YAML files.

#### Deploy Using Fleet
```bash
python3.11 ./deploy.py -f  # For Fleet-managed deployments
```
This will process all manifests and push them to your Fleet repository.

To configure Fleet, use the section in .env.example:

```bash
PRIVATE_REPO_URL=https://github.com/username/private-repo.git
GIT_USERNAME=your-username
GIT_TOKEN=your-personal-access-token
```

#### Direct Deployment

If you've cloned the repository within a server in the Kubernetes cluster, you can deploy the manifests directly using these commands (remember to initialize the infrastructure first).

```bash
python3.11 ./deploy.py                            # Deploy all manifest
python3.11 ./deploy.py manifests/0x-manifest.yaml  # Deploy a specific service
```

## Troubleshooting

If you encounter issues during deployment:

1. Check the logs of the deployment script
2. Verify your environment variables in `.env`
3. Ensure all prerequisites are properly installed
4. Check your Kubernetes cluster's status and connectivity
5. Verify storage system accessibility

For more detailed troubleshooting, consult the Kubernetes and Fleet documentation.
