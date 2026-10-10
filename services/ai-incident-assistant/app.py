import os, time, json, httpx
from fastapi import Request, HTTPException
from common import create_app, log
app = create_app()
DATA_FILE = os.path.join(os.getenv("DATA_DIR", "/data"), "incidents.json")

def load():
    try:
        with open(DATA_FILE) as f:
            return json.load(f)
    except Exception:
        return []

def save():  # write to a temp file first, then swap, so a crash never leaves a half-written file
    try:
        os.makedirs(os.path.dirname(DATA_FILE), exist_ok=True)
        with open(DATA_FILE + ".tmp", "w") as f:
            json.dump(INC, f)
        os.replace(DATA_FILE + ".tmp", DATA_FILE)
    except Exception as e:
        log("ERROR", "could not save incidents", error=str(e))

INC = load()  # incident (ITSM ticket) store, reloaded from disk on startup
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

JIRA_URL = os.getenv("JIRA_URL", "").rstrip("/")
JIRA_EMAIL = os.getenv("JIRA_EMAIL", "")
JIRA_TOKEN = os.getenv("JIRA_TOKEN", "")
JIRA_PROJECT = os.getenv("JIRA_PROJECT", "SENT")
JIRA_ISSUE_TYPE = os.getenv("JIRA_ISSUE_TYPE", "Task")

def adf(text):  # Jira Cloud v3 wants Atlassian Document Format for text fields
    paras = [{"type": "paragraph", "content": [{"type": "text", "text": ln}]} for ln in text.split("\n") if ln.strip()]
    return {"type": "doc", "version": 1, "content": paras or [{"type": "paragraph", "content": []}]}

async def jira(method, path, **kw):
    if not (JIRA_URL and JIRA_EMAIL and JIRA_TOKEN):
        return None  # Jira not configured: skip silently
    try:
        async with httpx.AsyncClient(timeout=15, auth=(JIRA_EMAIL, JIRA_TOKEN)) as c:
            r = await c.request(method, f"{JIRA_URL}/rest/api/3{path}", **kw)
        if r.status_code >= 400:
            log("ERROR", "jira call failed", status=r.status_code, body=r.text[:200])
            return None
        return r.json() if r.text else {}
    except Exception as e:
        log("ERROR", "jira call error", error=str(e))
        return None

async def jira_open(inc):
    res = await jira("POST", "/issue", json={"fields": {
        "project": {"key": JIRA_PROJECT},
        "summary": f"[{inc['severity']}] {inc['service']}: {inc['alert']} ({inc['id']})",
        "issuetype": {"name": JIRA_ISSUE_TYPE},
        "labels": ["sentinelops", "incident", inc["severity"]],
        "description": adf(inc["ai_summary"])}})
    if res:
        inc["jira_key"] = res["key"]
        log("INFO", "jira ticket created", id=inc["id"], jira=res["key"])

async def jira_move(key, category):  # category: "indeterminate" (in progress) or "done"
    t = await jira("GET", f"/issue/{key}/transitions")
    for x in (t or {}).get("transitions", []):
        if x["to"]["statusCategory"]["key"] == category:
            await jira("POST", f"/issue/{key}/transitions", json={"transition": {"id": x["id"]}})
            return

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
            save()
            await jira_open(inc)
            save()
            log("INFO", "incident created", id=inc["id"], severity=inc["severity"])
            if SLACK:
                async with httpx.AsyncClient() as c:
                    await c.post(SLACK, json={"text": f":rotating_light: *{inc['id']}* [{inc['severity']}] {svc}\n{inc['ai_summary']}"})
        elif a["status"] == "resolved" and open_inc:
            open_inc.update(status="Resolved", resolved_at=time.time())
            open_inc["mttr_sec"] = round(open_inc["resolved_at"] - open_inc["opened_at"])
            save()
            if open_inc.get("jira_key"):
                await jira("POST", f"/issue/{open_inc['jira_key']}/comment", json={"body": adf(f"Resolved automatically. MTTR: {open_inc['mttr_sec']} seconds.")})
                await jira_move(open_inc["jira_key"], "done")
            log("INFO", "incident resolved", id=open_inc["id"], mttr_sec=open_inc["mttr_sec"])
    return {"ok": True}

@app.get("/incidents")
def incidents(): return INC

@app.post("/incidents/{iid}/ack")
async def ack(iid: str):
    for i in INC:
        if i["id"] == iid and i["status"] == "Open":
            i["status"] = "Acknowledged"
            save()
            if i.get("jira_key"):
                await jira("POST", f"/issue/{i['jira_key']}/comment", json={"body": adf("Acknowledged by on-call engineer.")})
                await jira_move(i["jira_key"], "indeterminate")
            return i
    raise HTTPException(404, "not found or not open")
