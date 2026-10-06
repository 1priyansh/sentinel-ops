import itertools, httpx
from fastapi import HTTPException
from common import create_app, log
app = create_app()
counter = itertools.count(1)

@app.post("/orders")
def create_order(o: dict):
    oid = next(counter)
    try:
        r = httpx.post("http://payment-service:8000/pay", json={"order_id": oid}, timeout=5)
    except Exception as e:
        log("ERROR", "order failed: payment unreachable", order_id=oid, error=str(e))
        raise HTTPException(504, "payment unreachable")
    if r.status_code != 200:
        log("ERROR", "order failed: payment error", order_id=oid)
        raise HTTPException(502, "payment error")
    log("INFO", "order created", order_id=oid)
    return {"order_id": oid, "status": "confirmed"}
