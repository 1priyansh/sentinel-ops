import os, random, time
from fastapi import HTTPException
from common import create_app, log
app = create_app()
state = {"fail": float(os.getenv("FAIL_RATE", "0")), "delay": 0.0}

@app.post("/pay")
def pay(p: dict):
    time.sleep(state["delay"])
    if random.random() < state["fail"]:
        log("ERROR", "payment provider timeout", order_id=p.get("order_id"))
        raise HTTPException(502, "payment failed")
    log("INFO", "payment ok", order_id=p.get("order_id"))
    return {"status": "paid"}

@app.post("/chaos")  # inject failures at runtime for demos
def chaos(fail: float = 0, delay: float = 0):
    state.update(fail=fail, delay=delay)
    log("WARN", "chaos config changed", **state)
    return state
