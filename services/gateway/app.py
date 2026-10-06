import httpx
from fastapi import HTTPException
from common import create_app
app = create_app()

def fwd(method, url, **kw):
    try:
        r = httpx.request(method, url, timeout=8, **kw)
    except Exception:
        raise HTTPException(504, "upstream timeout")
    if r.status_code >= 400:
        raise HTTPException(r.status_code, "upstream error")
    return r.json()

@app.get("/products")
def products(): return fwd("GET", "http://product-service:8000/products")

@app.post("/login")
def login(u: dict): return fwd("POST", "http://user-service:8000/login", json=u)

@app.post("/orders")
def orders(o: dict): return fwd("POST", "http://order-service:8000/orders", json=o)

@app.post("/admin/chaos")
def chaos(fail: float = 0, delay: float = 0):
    return fwd("POST", "http://payment-service:8000/chaos", params={"fail": fail, "delay": delay})
