import httpx, random, time
time.sleep(15)
while True:
    try:
        httpx.get("http://gateway:8000/products", timeout=5)
        httpx.post("http://gateway:8000/login", json={"user": "u%d" % random.randint(1, 50)}, timeout=5)
        httpx.post("http://gateway:8000/orders", json={"item": 1}, timeout=8)
    except Exception:
        pass
    time.sleep(0.3)
