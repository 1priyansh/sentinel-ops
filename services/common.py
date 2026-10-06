import os, time, json
from fastapi import FastAPI, Request, Response
from prometheus_client import Counter, Histogram, generate_latest, CONTENT_TYPE_LATEST

SVC = os.getenv("SERVICE", "svc")
REQ = Counter("http_requests_total", "Requests", ["service", "path", "status"])
LAT = Histogram("http_request_duration_seconds", "Latency", ["service", "path"])

def log(level, msg, **kw):  # structured JSON logs -> Promtail -> Loki
    print(json.dumps({"ts": time.time(), "level": level, "service": SVC, "msg": msg, **kw}), flush=True)

def create_app():
    app = FastAPI(title=SVC)

    @app.get("/metrics")
    def metrics():
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    @app.get("/health")
    def health():
        return {"status": "ok", "service": SVC}

    @app.middleware("http")
    async def track(request: Request, call_next):
        t = time.time()
        resp = await call_next(request)
        if request.url.path != "/metrics":
            REQ.labels(SVC, request.url.path, str(resp.status_code)).inc()
            LAT.labels(SVC, request.url.path).observe(time.time() - t)
        return resp
    return app
