import os, time, httpx
from fastapi import Request, HTTPException
from common import create_app, log
app = create_app()
INC = []  # in-memory incident (ITSM ticket) store
LOKI = os.getenv("LOKI_URL", "http://loki:3100")
PROM = os.getenv("PROM_URL", "http://prometheus:9090")
KEY = os.getenv("ANTHROPIC_API_KEY", "")
MODEL = os.getenv("CLAUDE_MODEL", "claude-sonnet-5-5")
SLACK = os.getenv("SLACK_WEBHOOK_URL", "")

async def get_logs(svc):
    end = int(time.time() * 1e9)
    q = f'{{service="{svc}"}} |= "ERROR"'
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(f"{LOKI}/loki/api/v1/query_range", params={"query": q, "limit": 15, "start": end - 300 * 10**9, "end": end})
        return [v[1] for s in r.json()["data"]["result"] for v in s["values"]]
    except Exception as e:
        return [f"(could not fetch logs: {e})"]

async def get_err_rate(svc):
    q = f'sum(rate(http_requests_total{{service="{svc}",status=~"5.."}}[1m]))'
    try:
        async with httpx.AsyncClient(timeout=10) as c:
            r = await c.get(f"{PROM}/api/v1/query", params={"query": q})
        return float(r.json()["data"]["result"][0]["value"][1])
    except Exception:
        return None

async def analyze(alert, svc, logs, rate):
    ctx = f"Alert: {alert}\nService: {svc}\n5xx rate/sec: {rate}\nRecent error logs:\n" + "\n".join(logs[:15])
    if KEY:
        try:
            async with httpx.AsyncClient(timeout=40) as c:
                r = await c.post("https://api.anthropic.com/v1/messages",
                    headers={"x-api-key": KEY, "anthropic-version": "2023-06-01"},
                    json={"model": MODEL, "max_tokens": 500, "messages": [{"role": "user", "content":
                        "You are an SRE assistant. Given this incident context, write: 1) summary, 2) likely root cause, 3) next steps. Be concise.\n\n" + ctx}]})
            return r.json()["content"][0]["text"]
        except Exception as e:
            log("ERROR", "AI call failed, using rule-based summary", error=str(e))
    top = logs[0] if logs else "no error logs found"
    return f"[rule-based] {svc} is failing ({alert}). 5xx rate={rate}. Latest error: {top}. Next steps: check recent deploys, dependency health, and the runbook."

@app.post("/webhook")
async def webhook(req: Request):
    body = await req.json()
    for a in body.get("alerts", []):
        name, svc = a["labels"]["alertname"], a["labels"].get("service", "unknown")
        open_inc = next((i for i in INC if i["alert"] == name and i["status"] != "Resolved"), None)
        if a["status"] == "firing" and not open_inc:
            logs, rate = await get_logs(svc), await get_err_rate(svc)
            inc = {"id": f"INC-{len(INC)+1:04d}", "alert": name, "service": svc, "severity": a["labels"].get("severity", "P3"),
                   "status": "Open", "opened_at": time.time(), "resolved_at": None, "mttr_sec": None,
                   "ai_summary": await analyze(name, svc, logs, rate)}
            INC.append(inc)
            log("INFO", "incident created", id=inc["id"], severity=inc["severity"])
            if SLACK:
                async with httpx.AsyncClient() as c:
                    await c.post(SLACK, json={"text": f":rotating_light: *{inc['id']}* [{inc['severity']}] {svc}\n{inc['ai_summary']}"})
        elif a["status"] == "resolved" and open_inc:
            open_inc.update(status="Resolved", resolved_at=time.time())
            open_inc["mttr_sec"] = round(open_inc["resolved_at"] - open_inc["opened_at"])
            log("INFO", "incident resolved", id=open_inc["id"], mttr_sec=open_inc["mttr_sec"])
    return {"ok": True}

@app.get("/incidents")
def incidents(): return INC

@app.post("/incidents/{iid}/ack")
def ack(iid: str):
    for i in INC:
        if i["id"] == iid and i["status"] == "Open":
            i["status"] = "Acknowledged"; return i
    raise HTTPException(404, "not found or not open")
