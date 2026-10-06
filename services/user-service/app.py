from common import create_app, log
app = create_app()

@app.post("/login")
def login(u: dict):
    log("INFO", "user login", user=u.get("user"))
    return {"token": "tok-" + str(u.get("user"))}
