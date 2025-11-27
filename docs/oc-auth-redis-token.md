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

You can find these files on this GitHub Repo -> https://github.com/opencitations/oc_auth_token

| File | Purpose |
|------|---------|
| `oc_auth_service/app/main.py` | FastAPI auth service |
| `oc_auth_service/Dockerfile` | Docker image |
| `04-wordpress-mariadb-redis-authtoken-OPTIONAL.yaml` | Deployment + ForwardAuth middleware + IngressRoute override |

## Deploy

**Important:** `04-wordpress-mariadb-redis-authtoken-OPTIONAL.yaml` overwrites the `oc-api` (inside the file `09-oc-splitted-api.yaml`) IngressRoute to add ForwardAuth.

## Verify

```bash
# Check pods
kubectl get pods -l app=oc-auth-service

# Test invalid token (should return 403)
curl -i -H "Authorization: fake-token" https://api.opencitations.net/meta/v1/metadata/doi:10.1162/qss_a_00023

# Test valid request (should return 200, X-Cache: HIT after first call)
curl -i https://api.opencitations.net/meta/v1/metadata/doi:10.1162/qss_a_00023
```

## Rollback

If issues occur, redeploy `09-oc-splitted-api.yaml` to restore original IngressRoute without ForwardAuth.