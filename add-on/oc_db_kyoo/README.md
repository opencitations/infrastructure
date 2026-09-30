# oc_db_kyoo add-on

Queue, concurrency limiter and circuit breaker between `oc-api` and the QLever databases. It is used **only by the API**: the other services (`oc-sparql`, `oc-search`, `oc-ldd`, `oc-oci`, the statistics CronJob) query the database services directly.

Source code and full documentation: https://github.com/opencitations/oc_db_kyoo (image `opencitations/oc_db_kyoo`).

```
Client ─► Traefik ─► Varnish ─► redis-api-cache ─► oc-api ─► oc_db_kyoo ─► QLever index
                                                                           QLever meta
```

Varnish and the Redis API cache are part of `manifests/03-varnish-rediscache.yaml` (see `docs/oc-api-redis-cache.md`).

This folder is not picked up by `./deploy.py` (all manifests) or `./deploy.py -f` (Fleet): the manifest is applied explicitly, as shown below.

oc_db_kyoo is an async HTTP reverse proxy. For each database backend it keeps an independent queue and circuit breaker, routes each request to the least-loaded backend, and answers with a "backend busy" page instead of overloading the databases. One instance manages one database type, so there are two instances:

| Deployment | Service | Backends |
|------------|---------|----------|
| `oc-db-kyoo-qleverindex` | `oc-db-kyoo-qleverindex-service:80` | `index-db-qlever-{1,2}` |
| `oc-db-kyoo-qlevermeta` | `oc-db-kyoo-qlevermeta-service:80` | `meta-db-qlever-{1,2,3}` |

## How backends are reached

Each backend is a single StatefulSet pod, addressed through its per-pod DNS name:

```
<statefulset>-0.<serviceName>.default.svc.cluster.local
e.g. meta-db-qlever-1-0.meta-qlever-service.default.svc.cluster.local
```

This name only resolves if the StatefulSet's `serviceName` is the Service that selects its pods. `serviceName` is immutable: if it is wrong, the StatefulSet must be deleted and recreated. Check with:

```bash
kubectl exec deploy/oc-db-kyoo-qleverindex -- getent hosts meta-db-qlever-1-0.meta-qlever-service.default.svc.cluster.local
```

Backends are configured with `BACKEND_N_NAME/HOST/PORT/PATH` env vars, with `N` contiguous from `0` (discovery stops at the first missing index). To add a database replica, add the next `BACKEND_N_*` block and redeploy.

## Configuration choices

| Variable | Value | Why |
|----------|-------|-----|
| `MAX_CONCURRENT_PER_BACKEND` | `20` | Below QLever `--num-simultaneous-queries` (24) |
| `BACKEND_TIMEOUT` | `330` | Must be **higher** than QLever `--default-query-timeout` (320s). kyoo counts its own timeouts as backend failures: with a lower value, three slow queries would open the circuit of a healthy backend. With 330s, QLever answers first with an HTTP error, which does not trip the breaker |
| `HEALTH_CHECK_QUERY` | `ASK` on a known entity | Cheap probe used to confirm backend recovery |
| Probes | `/ready` | `/health` returns 503 when all backends are busy: using it for Kubernetes probes would restart kyoo exactly when it is needed |

## Deploy

1. Add the image version to `.env`:
   ```bash
   DB_KYOO_VERSION=3.3.0
   ```
2. Preview and apply:
   ```bash
   python3.11 ./deploy.py -p add-on/oc_db_kyoo/oc-db-kyoo.yaml
   python3.11 ./deploy.py add-on/oc_db_kyoo/oc-db-kyoo.yaml
   ```
3. Point `oc-api` to kyoo in `manifests/09-oc-splitted-api.yaml`:
   ```yaml
               - name: SPARQL_ENDPOINT_INDEX
                 value: http://oc-db-kyoo-qleverindex-service.default.svc.cluster.local
               - name: SPARQL_ENDPOINT_META
                 value: http://oc-db-kyoo-qlevermeta-service.default.svc.cluster.local
   ```
   kyoo ignores the request path and forwards only the query string to `<backend>/<BACKEND_N_PATH>`, so no path is needed in the URL.

Without kyoo, set these two variables to the database services instead (`${SPARQL_ENDPOINT_INDEX}` / `${SPARQL_ENDPOINT_META}` from `.env`).

On a fresh installation, deploy the databases (`01`, `02`) first, then kyoo, then the API (`09`).

## Operations

```bash
# Per-backend queues, circuit state, response times (JSON)
kubectl exec deploy/oc-db-kyoo-qlevermeta -- curl -s localhost:8080/status

# Live dashboard
kubectl port-forward deploy/oc-db-kyoo-qlevermeta 8080:8080   # then open http://localhost:8080/dashboard

# Slow queries that hit BACKEND_TIMEOUT (full SPARQL text, client IP, user agent)
kubectl exec deploy/oc-db-kyoo-qlevermeta -- tail -n 50 /app/timeout_requests.log

# Connection / unexpected errors
kubectl exec deploy/oc-db-kyoo-qlevermeta -- tail -n 50 /app/error_requests.log
```
