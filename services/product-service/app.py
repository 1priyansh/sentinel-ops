from common import create_app, log
app = create_app()
PRODUCTS = [{"id": 1, "name": "Laptop", "price": 900}, {"id": 2, "name": "Phone", "price": 500}, {"id": 3, "name": "Headphones", "price": 80}]

@app.get("/products")
def products():
    log("INFO", "listed products", count=len(PRODUCTS))
    return PRODUCTS
