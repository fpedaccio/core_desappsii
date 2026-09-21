import time

from fastapi import Request
from prometheus_client import Counter, Gauge, Histogram

REQUEST_COUNT = Counter(
    "request_count",
    "Total number of HTTP requests",
    ["method", "endpoint", "status_code"],
)

REQUEST_LATENCY = Histogram(
    "request_latency_seconds",
    "HTTP request latency in seconds",
    ["method", "endpoint"],
)

AUTH_FAILURES = Counter(
    "auth_failures",
    "Total number of failed authentication attempts",
    ["auth_type", "reason"],
)

ACTIVE_USERS = Gauge(
    "active_users",
    "Number of users with at least one active session",
)

def get_route_path(request: Request) -> str:
    route = request.scope.get("route")

    if route is not None and hasattr(route, "path"):
        return route.path

    return "unmatched"


async def metrics_middleware(request: Request, call_next):
    if request.url.path == "/metrics":
        return await call_next(request)

    start_time = time.perf_counter()

    response = await call_next(request)

    duration = time.perf_counter() - start_time
    endpoint = get_route_path(request)

    REQUEST_COUNT.labels(
        method=request.method,
        endpoint=endpoint,
        status_code=str(response.status_code),
    ).inc()

    REQUEST_LATENCY.labels(
        method=request.method,
        endpoint=endpoint,
    ).observe(duration)

    return response