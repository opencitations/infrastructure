# oc-api Redis Cache Proxy

Redis-backed cache between Varnish and `oc-api-service`. Keeps API responses warm across Varnish restarts. Restart the pod to clear the cache on new database releases.

Only caches `/index/v1/*`, `/index/v2/*`, `/meta/v1/*` GET 200 responses. Everything else passes through.

## Source files

### Dockerfile

```dockerfile
FROM python:3.12-slim

WORKDIR /app

RUN pip install --no-cache-dir "aiohttp>=3.10,<4" "redis>=5.0,<6"

COPY proxy.py .

EXPOSE 8888

CMD ["python", "proxy.py"]
```

### proxy.py

```python
#!/usr/bin/env python3
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

REDIS_HOST = os.getenv("REDIS_HOST", "127.0.0.1")
REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
BACKEND_HOST = os.getenv("BACKEND_HOST", "oc-api-service.default.svc.cluster.local")
BACKEND_PORT = int(os.getenv("BACKEND_PORT", "80"))
LISTEN_PORT = int(os.getenv("LISTEN_PORT", "8888"))
CACHE_TTL = int(os.getenv("CACHE_TTL", str(120 * 86400)))
MAX_BODY_CACHE = int(os.getenv("MAX_BODY_CACHE", str(50 * 1024 * 1024)))
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

API_PATH_PATTERN = re.compile(r"^/(index/v[12]|meta/v1)/.+")

CACHEABLE_HEADERS = {
    "content-type", "content-disposition", "x-total-count", "link",
}

FORWARD_HEADERS = {
    "accept", "host", "user-agent", "x-real-ip",
    "x-forwarded-for", "x-forwarded-proto", "authorization",
}

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("redis-api-cache")


def make_cache_key(path: str, query: str, accept: str) -> str:
    raw = path
    if query:
        raw += f"?{query}"
    if accept:
        raw += f"|accept:{accept.lower().strip()}"
    return "apicache:" + hashlib.sha256(raw.encode()).hexdigest()


class CacheProxy:
    def __init__(self):
        self.redis: aioredis.Redis | None = None
        self.http_session: aiohttp.ClientSession | None = None
        self.backend_url = f"http://{BACKEND_HOST}:{BACKEND_PORT}"

    async def start(self, app: web.Application):
        self.redis = aioredis.Redis(
            host=REDIS_HOST, port=REDIS_PORT, decode_responses=False,
            socket_connect_timeout=5, socket_timeout=10, retry_on_timeout=True,
        )
        self.http_session = aiohttp.ClientSession(
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
            await self.redis.close()
        logger.info("Cache proxy stopped")

    async def health(self, request: web.Request) -> web.Response:
        try:
            await self.redis.ping()
            return web.Response(text="OK", status=200)
        except Exception as e:
            logger.error("Health check failed: %s", e)
            return web.Response(text="Redis unavailable", status=503)

    async def handle(self, request: web.Request) -> web.Response:
        method = request.method.upper()

        if method not in ("GET", "HEAD"):
            return await self._proxy_to_backend(request)

        path = request.path
        query = request.query_string

        if "preview=true" in query:
            return await self._proxy_to_backend(request)

        if not API_PATH_PATTERN.match(path):
            return await self._proxy_to_backend(request)

        accept = request.headers.get("Accept", "")
        cache_key = make_cache_key(path, query, accept)

        try:
            cached = await self.redis.get(cache_key)
        except Exception as e:
            logger.warning("Redis GET failed: %s", e)
            cached = None

        if cached:
            try:
                entry = json.loads(cached)
                headers = entry.get("headers", {})
                headers["X-Redis-Cache"] = "HIT"

                if method == "HEAD":
                    return web.Response(status=entry["status"], headers=headers)

                return web.Response(
                    status=entry["status"],
                    body=entry["body"].encode("utf-8"),
                    headers=headers,
                )
            except (json.JSONDecodeError, KeyError) as e:
                logger.warning("Corrupted cache entry: %s", e)

        return await self._proxy_to_backend(request, cache_key=cache_key)

    async def _proxy_to_backend(
        self, request: web.Request, cache_key: str | None = None
    ) -> web.Response:
        url = f"{self.backend_url}{request.path_qs}"

        fwd_headers = {}
        for name, value in request.headers.items():
            if name.lower() in FORWARD_HEADERS:
                fwd_headers[name] = value

        try:
            async with self.http_session.request(
                method=request.method, url=url,
                headers=fwd_headers, allow_redirects=False,
            ) as backend_resp:
                body = await backend_resp.read()
                status = backend_resp.status

                resp_headers = {}
                if cache_key:
                    for name, value in backend_resp.headers.items():
                        if name.lower() in CACHEABLE_HEADERS:
                            resp_headers[name] = value
                    resp_headers["X-Redis-Cache"] = "MISS"
                else:
                    for name, value in backend_resp.headers.items():
                        if name.lower() not in (
                            "transfer-encoding", "connection", "keep-alive"
                        ):
                            resp_headers[name] = value

                if (
                    cache_key and status == 200
                    and request.method == "GET"
                    and len(body) <= MAX_BODY_CACHE
                ):
                    entry = json.dumps({
                        "status": status,
                        "body": body.decode("utf-8", errors="replace"),
                        "headers": {
                            k: v for k, v in resp_headers.items()
                            if k != "X-Redis-Cache"
                        },
                        "cached_at": int(time.time()),
                    })
                    try:
                        await self.redis.set(cache_key, entry, ex=CACHE_TTL)
                    except Exception as e:
                        logger.warning("Redis SET failed: %s", e)

                return web.Response(status=status, body=body, headers=resp_headers)

        except asyncio.TimeoutError:
            logger.error("Backend timeout: %s", url)
            return web.Response(status=504, text="Backend timeout")
        except Exception as e:
            logger.error("Backend error: %s — %s", url, e)
            return web.Response(status=502, text="Backend unavailable")


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

## Build

```bash
# From ARM (Apple Silicon)
docker buildx build --platform linux/amd64 -t opencitations/redis-api-cache-proxy:<version> --push .

# From amd64
docker build -t opencitations/redis-api-cache-proxy:<version> .
docker push opencitations/redis-api-cache-proxy:<version>
```

Update `REDIS_API_CACHE_VERSION` in `.env`, then:

```bash
kubectl apply -f manifests/03-varnish.yaml
kubectl rollout restart deployment/redis-api-cache
```

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `REDIS_HOST` | `127.0.0.1` | Redis address |
| `REDIS_PORT` | `6379` | Redis port |
| `BACKEND_HOST` | `oc-api-service.default.svc.cluster.local` | Backend |
| `BACKEND_PORT` | `80` | Backend port |
| `LISTEN_PORT` | `8888` | Proxy listen port |
| `CACHE_TTL` | `10368000` | TTL in seconds (120 days) |
| `MAX_BODY_CACHE` | `52428800` | Max response size (50 MB) |
| `LOG_LEVEL` | `INFO` | Log verbosity |
