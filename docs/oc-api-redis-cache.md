# oc-api Redis Cache Proxy

Warm cache between Varnish and `oc-api-service`, deployed with `manifests/03-varnish-rediscache.yaml`.

Varnish keeps its cache in memory (`malloc`): every restart empties it and all API traffic hits `oc-api` until the cache warms up again. Since database releases happen about every 4 months, API responses stay valid for the whole release cycle. The Redis API cache keeps them warm across Varnish restarts.

It runs as a single pod with two containers sharing `localhost`:

- `redis` — `redis:8.10.2-alpine`, ephemeral (no RDB/AOF), `allkeys-lru`, `maxmemory 16gb`
- `proxy` — `opencitations/redis-api-cache-proxy` (Python, aiohttp), port 8888, exposed as `redis-api-cache-service:80`

## Integration

- Varnish `api` backend (`manifests/03-varnish-rediscache.yaml`) points to `redis-api-cache-service.default.svc.cluster.local`.
- The proxy forwards to `oc-api-service` (`BACKEND_HOST`).

To disable the cache, point the Varnish `api` backend back to `oc-api-service.default.svc.cluster.local`.

## What gets cached

- Only paths matching `^/(index/v[12]|meta/v1|skg-if/v1)/.+` (`API_PATH_PATTERN` in `proxy.py`). Documentation pages and everything else pass through.
- Only `GET` responses with status `200` and a body up to 50 MB (`MAX_BODY_CACHE`). `HEAD` is answered from the `GET` entry when present.
- Requests with `preview=true` in the query string are never cached.
- Key: SHA-256 of `path?query|accept:<Accept header>`, prefixed `apicache:v2:`. Different formats (JSON, CSV, ...) get separate entries; the `Authorization` token is not part of the key.
- Entry: a Redis hash `{status, headers, body, cached_at}` with the body stored as raw bytes. TTL: 120 days (`CACHE_TTL`).

## Resilience

If Redis is down or restarting, the proxy keeps working as a plain pass-through to `oc-api` (one immediate retry, no backoff, so no added latency). For this reason:

- `/healthz` always returns `200` and only reports the Redis state in the body.
- The `redis` container has a liveness probe but **no readiness probe**, so a Redis restart does not remove the pod from the Service.

## Build and release

Create a folder with the `Dockerfile` and `proxy.py` from the [Source files](#source-files) section below, then:

```bash
# From Apple Silicon, --platform is required for the amd64 cluster nodes
docker buildx build --platform linux/amd64 \
  -t opencitations/redis-api-cache-proxy:<version> --push .
```

Then set `REDIS_API_CACHE_VERSION=<version>` in `.env` (one line only) and deploy `manifests/03-varnish-rediscache.yaml`. The pod is recreated, so the cache starts empty.

## Environment variables (proxy)

| Variable | Default | Description |
|----------|---------|-------------|
| `REDIS_HOST` | `127.0.0.1` | Redis address (sidecar) |
| `REDIS_PORT` | `6379` | Redis port |
| `BACKEND_HOST` | `oc-api-service.default.svc.cluster.local` | Backend |
| `BACKEND_PORT` | `80` | Backend port |
| `LISTEN_PORT` | `8888` | Proxy port |
| `CACHE_TTL` | `10368000` | Entry TTL in seconds (120 days) |
| `MAX_BODY_CACHE` | `52428800` | Max cacheable body size in bytes (50 MB) |
| `LOG_LEVEL` | `INFO` | Log verbosity |

## Response headers

| `X-Cache` (Varnish) | `X-Redis-Cache` (proxy) | Meaning |
|---------------------|-------------------------|---------|
| `HIT` | *(absent)* | Served by Varnish |
| `MISS` | `HIT` | Varnish miss, served by Redis |
| `MISS` | `MISS` | Both missed, served by `oc-api` and stored |
| `MISS` | *(absent)* | Not cacheable (path, method, preview) |

## Operations

```bash
kubectl exec deploy/redis-api-cache -c redis -- redis-cli dbsize        # cached entries
kubectl exec deploy/redis-api-cache -c redis -- redis-cli info memory   # memory usage
kubectl exec deploy/redis-api-cache -c redis -- redis-cli flushall      # flush without restart
kubectl logs -f deploy/redis-api-cache -c proxy                         # proxy logs
```

## New database release checklist

API responses are cached in two layers (Varnish 60 days, Redis 120 days). After switching to a new database release, clear them **in this order**, otherwise Varnish refills from the old Redis entries:

```bash
# 1. Redis: restart the pod (ephemeral cache)
kubectl rollout restart deploy/redis-api-cache
kubectl rollout status deploy/redis-api-cache

# 2. Varnish: ban the API entries on every replica
for p in $(kubectl get pods -l app=varnish -o name); do
  kubectl exec $p -- varnishadm 'ban req.http.host == "api.opencitations.net" && req.url ~ "^/(index/v[12]|meta/v1|skg-if/v1)/"'
done
```

oc_db_kyoo needs no action, unless the database backends themselves changed (names, number of replicas, port).

## Source files

Current image version: `1.1.0` (Python 3.14, aiohttp 3.14.3, redis-py 8.1.0).

### Dockerfile

```dockerfile
FROM python:3.14-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

RUN pip install --no-cache-dir "aiohttp==3.14.3" "redis==8.1.0"

COPY proxy.py .

USER nobody

EXPOSE 8888

CMD ["python", "proxy.py"]
```

### proxy.py

```python
#!/usr/bin/env python3
"""
OpenCitations Redis API Cache Proxy
====================================
Sits between Varnish and oc-api-service.
Caches API responses in Redis keyed by URL + Accept header.

Flow: Varnish -> this proxy -> oc-api-service
"""

import asyncio
import hashlib
import json
import logging
import os
import re
import time

import aiohttp
from aiohttp import web
import redis.asyncio as aioredis
from redis.asyncio.retry import Retry
from redis.backoff import NoBackoff

# ---------------------------------------------------------------------------
# Configuration (from environment variables)
# ---------------------------------------------------------------------------
REDIS_HOST = os.getenv("REDIS_HOST", "127.0.0.1")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
BACKEND_HOST = os.getenv("BACKEND_HOST", "oc-api-service.default.svc.cluster.local")
BACKEND_PORT = int(os.getenv("BACKEND_PORT", "80"))
LISTEN_PORT = int(os.getenv("LISTEN_PORT", "8888"))
CACHE_TTL = int(os.getenv("CACHE_TTL", str(120 * 86400)))  # 120 days default
MAX_BODY_CACHE = int(os.getenv("MAX_BODY_CACHE", str(50 * 1024 * 1024)))  # 50 MB max
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

# Only cache actual API data endpoints, not documentation pages
# Matches: /index/v1/<id>, /index/v2/<id>, /meta/v1/<id>, /skg-if/v1/<id>
API_PATH_PATTERN = re.compile(r"^/(index/v[12]|meta/v1|skg-if/v1)/.+")

# Cache entries are Redis hashes {status, headers, body, cached_at}.
# The "v2" prefix keeps them apart from the old JSON-string entries.
CACHE_KEY_PREFIX = "apicache:v2:"

# Headers to preserve in cache (lowercase)
CACHEABLE_HEADERS = {
    "content-type",
    "content-disposition",
    "x-total-count",
    "link",
}

# Headers to forward to backend (lowercase)
FORWARD_HEADERS = {
    "accept",
    "host",
    "user-agent",
    "x-real-ip",
    "x-forwarded-for",
    "x-forwarded-proto",
    "authorization",
}

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("redis-api-cache")


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def make_cache_key(path: str, query: str, accept: str) -> str:
    """
    Cache key based on URL + Accept header only.
    Method is NOT included: GET and HEAD share the same cache entry.
    Accept IS included: different formats (json, csv, turtle) get separate entries.
    """
    raw = path
    if query:
        raw += f"?{query}"
    if accept:
        raw += f"|accept:{accept.lower().strip()}"
    return CACHE_KEY_PREFIX + hashlib.sha256(raw.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Application
# ---------------------------------------------------------------------------
class CacheProxy:
    def __init__(self):
        self.redis: aioredis.Redis | None = None
        self.http_session: aiohttp.ClientSession | None = None
        self.backend_url = f"http://{BACKEND_HOST}:{BACKEND_PORT}"

    async def start(self, app: web.Application):
        self.redis = aioredis.Redis(
            host=REDIS_HOST,
            port=REDIS_PORT,
            decode_responses=False,
            socket_connect_timeout=5,
            socket_timeout=10,
            # One immediate retry only: redis-py's default (3 retries with backoff)
            # adds seconds of latency to every request while Redis is down.
            retry=Retry(NoBackoff(), 1),
        )
        connector = aiohttp.TCPConnector(
            limit=100,
            limit_per_host=100,
            keepalive_timeout=15,       # must be < gunicorn keepalive (20s)
            enable_cleanup_closed=True,
        )
        self.http_session = aiohttp.ClientSession(
            connector=connector,
            timeout=aiohttp.ClientTimeout(total=900, sock_read=900),
        )
        logger.info(
            "Cache proxy started — backend=%s redis=%s:%s ttl=%dd",
            self.backend_url, REDIS_HOST, REDIS_PORT, CACHE_TTL // 86400,
        )

    async def stop(self, app: web.Application):
        if self.http_session:
            await self.http_session.close()
        if self.redis:
            await self.redis.aclose()
        logger.info("Cache proxy stopped")

    async def health(self, request: web.Request) -> web.Response:
        """
        Kubernetes probe. Always 200 while the proxy is running: without Redis
        the proxy keeps working as a plain pass-through to oc-api, so a Redis
        outage must not take the API offline. Redis state is reported in the body.
        """
        try:
            await self.redis.ping()
            return web.Response(text="OK", status=200)
        except Exception as e:
            logger.warning("Redis unavailable, running as pass-through: %s", e)
            return web.Response(text="OK (redis unavailable, pass-through)", status=200)

    async def handle(self, request: web.Request) -> web.Response:
        """Main request handler with Redis cache lookup."""
        method = request.method.upper()

        # Only cache GET and HEAD
        if method not in ("GET", "HEAD"):
            return await self._proxy_to_backend(request)

        path = request.path
        query = request.query_string

        # Bypass cache for preview requests
        if "preview=true" in query:
            return await self._proxy_to_backend(request)

        # Only cache actual API data endpoints, not documentation pages
        if not API_PATH_PATTERN.match(path):
            return await self._proxy_to_backend(request)

        accept = request.headers.get("Accept", "")
        cache_key = make_cache_key(path, query, accept)

        # ---- Try Redis cache ----
        try:
            cached = await self.redis.hgetall(cache_key)
        except Exception as e:
            logger.warning("Redis HGETALL failed: %s", e)
            cached = None

        if cached:
            # Cache HIT
            try:
                status = int(cached[b"status"])
                headers = json.loads(cached[b"headers"])
                headers["X-Redis-Cache"] = "HIT"

                # HEAD responses: return headers only, no body
                if method == "HEAD":
                    return web.Response(status=status, headers=headers)

                return web.Response(
                    status=status, body=cached[b"body"], headers=headers
                )
            except (KeyError, ValueError) as e:
                logger.warning("Corrupted cache entry: %s", e)
                # Fall through to backend

        # ---- Cache MISS — fetch from backend ----
        return await self._proxy_to_backend(request, cache_key=cache_key)

    async def _proxy_to_backend(
        self, request: web.Request, cache_key: str | None = None
    ) -> web.Response:
        """Forward request to oc-api backend and optionally cache the response."""
        url = f"{self.backend_url}{request.path_qs}"

        # Build headers to forward
        fwd_headers = {}
        for name, value in request.headers.items():
            if name.lower() in FORWARD_HEADERS:
                fwd_headers[name] = value

        try:
            async with self.http_session.request(
                method=request.method,
                url=url,
                headers=fwd_headers,
                allow_redirects=False,
            ) as backend_resp:
                body = await backend_resp.read()
                status = backend_resp.status

                # For non-cached requests: forward ALL response headers
                # For cached requests: only keep headers we want to store in Redis
                resp_headers = {}
                if cache_key:
                    for name, value in backend_resp.headers.items():
                        if name.lower() in CACHEABLE_HEADERS:
                            resp_headers[name] = value
                else:
                    for name, value in backend_resp.headers.items():
                        # Skip hop-by-hop headers that shouldn't be forwarded
                        if name.lower() not in (
                            "transfer-encoding", "connection", "keep-alive"
                        ):
                            resp_headers[name] = value

                # Cache only successful GET responses within size limit.
                # The body is stored as raw bytes: no JSON escaping overhead,
                # no corruption of non UTF-8 payloads.
                if (
                    cache_key
                    and status == 200
                    and request.method == "GET"
                    and len(body) <= MAX_BODY_CACHE
                ):
                    try:
                        async with self.redis.pipeline(transaction=True) as pipe:
                            pipe.hset(cache_key, mapping={
                                "status": status,
                                "headers": json.dumps(resp_headers),
                                "body": body,
                                "cached_at": int(time.time()),
                            })
                            pipe.expire(cache_key, CACHE_TTL)
                            await pipe.execute()
                    except Exception as e:
                        logger.warning("Redis SET failed: %s", e)

                if cache_key:
                    resp_headers["X-Redis-Cache"] = "MISS"

                return web.Response(
                    status=status, body=body, headers=resp_headers
                )

        except asyncio.TimeoutError:
            logger.error("Backend timeout: %s", url)
            return web.Response(status=504, text="Backend timeout")
        except Exception as e:
            logger.error("Backend error: %s — %s", url, e)
            return web.Response(status=502, text="Backend unavailable")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def create_app() -> web.Application:
    proxy = CacheProxy()
    app = web.Application()
    app.on_startup.append(proxy.start)
    app.on_cleanup.append(proxy.stop)
    app.router.add_get("/healthz", proxy.health)
    app.router.add_route("*", "/{path_info:.*}", proxy.handle)
    return app


if __name__ == "__main__":
    web.run_app(create_app(), host="0.0.0.0", port=LISTEN_PORT)
```
