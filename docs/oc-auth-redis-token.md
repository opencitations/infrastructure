# OpenCitations Auth Token Service

## How it works

```
Request → Traefik → ForwardAuth → oc-auth-service → Redis
                         │
                         ├─ invalid token → 403
                         └─ valid/no token → Varnish (cached) → API
```

- Token validation happens at Traefik level via ForwardAuth
- Varnish caches all API responses (no more `pass` for Authorization header)
- API backend has `REDIS_ENABLED=false` - no direct Redis connection needed

## Files

| File | Purpose |
|------|---------|
| `oc_auth_service/app/main.py` | FastAPI auth service |
| `oc_auth_service/Dockerfile` | Docker image |
| `04-wordpress-mariadb-redis-OPTIONAL.yaml` | Deployment + ForwardAuth middleware + IngressRoute override |

## Update version

```bash
cd oc_auth_service

# Build new version
docker build -t opencitations/oc_auth_token:X.X.X .

# Push
docker push opencitations/oc_auth_token:X.X.X

# Update .env
AUTH_SERVICE_VERSION=X.X.X
```

## Deploy

**Important:** `04-wordpress-mariadb-redis-OPTIONAL.yaml` overwrites the `oc-api` IngressRoute to add ForwardAuth.

```bash
# Deploy auth service + IngressRoute override
python3.11 ./deploy.py manifests/04-wordpress-mariadb-redis-OPTIONAL.yaml

# If you also changed Varnish
python3.11 ./deploy.py manifests/03-varnish.yaml
```

## Verify

```bash
# Check pods
kubectl get pods -l app=oc-auth-service

# Test invalid token (should return 403)
curl -I -H "Authorization: fake-token" https://api.opencitations.net/meta/v1/metadata/doi:10.1162/qss_a_00023

# Test valid request (should return 200, X-Cache: HIT after first call)
curl -I https://api.opencitations.net/meta/v1/metadata/doi:10.1162/qss_a_00023
```

## Rollback

If issues occur, redeploy `09-oc-splitted-api.yaml` to restore original IngressRoute without ForwardAuth.