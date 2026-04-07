import sys
import os

root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, root)

from flask import Flask, render_template, request, redirect, session
import httpx
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__,
    template_folder=os.path.join(root, "templates"),
    static_folder=os.path.join(root, "static")
)

app.secret_key = os.environ.get("SECRET_KEY", "retailhub_secret")

SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://xfeehkqvaxdrwvsgoaqv.supabase.co")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InhmZWVoa3F2YXhkcnd2c2dvYXF2Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzU0NjE5NTcsImV4cCI6MjA5MTAzNzk1N30.mnsrn9RO5Lg2fanSaae-1FgOz0lN3SCWzkUUSv6zi9A")

HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "return=representation"
}

ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "admin123"


def db_get(table, filters=None, order=None):
    url = f"{SUPABASE_URL}/rest/v1/{table}?select=*"
    if filters:
        for k, v in filters.items():
            url += f"&{k}=eq.{v}"
    if order:
        url += f"&order={order}.desc"
    r = httpx.get(url, headers=HEADERS)
    return r.json()


def db_insert(table, data):
    url = f"{SUPABASE_URL}/rest/v1/{table}"
    r = httpx.post(url, headers=HEADERS, json=data)
    return r.json()


def db_update(table, data, filters):
    url = f"{SUPABASE_URL}/rest/v1/{table}?"
    for k, v in filters.items():
        url += f"{k}=eq.{v}&"
    r = httpx.patch(url.rstrip("&"), headers=HEADERS, json=data)
    return r.json()


def db_delete(table, filters):
    url = f"{SUPABASE_URL}/rest/v1/{table}?"
    for k, v in filters.items():
        url += f"{k}=eq.{v}&"
    httpx.delete(url.rstrip("&"), headers=HEADERS)


@app.route("/")
def home():
    return render_template("home.html", user=session.get("user"))


@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        password = generate_password_hash(request.form["password"])
        try:
            db_insert("users", {
                "name": request.form["name"],
                "username": request.form["username"],
                "email": request.form["email"],
                "phone": request.form["phone"],
                "address": request.form["address"],
                "password": password
            })
            return redirect("/login")
        except Exception as e:
            return f"Error: {e}"
    return render_template("signup.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]

        if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
            session["admin"] = True
            return redirect("/admin/dashboard")

        users = db_get("users", {"username": username})
        if users and check_password_hash(users[0]["password"], password):
            session["user"] = username
            return redirect("/")
        return render_template("login.html", error="Invalid credentials")
    return render_template("login.html", error=None)


@app.route("/shop")
def shop():
    if "user" not in session:
        return redirect("/login")
    category = request.args.get("category")
    if category:
        products = db_get("products", {"category": category})
    else:
        products = db_get("products")
    return render_template("shop.html", products=products)


@app.route("/contact", methods=["GET", "POST"])
def contact():
    if "user" not in session:
        return redirect("/login")
    if request.method == "POST":
        db_insert("contacts", {
            "name": request.form["name"],
            "email": request.form["email"],
            "message": request.form["message"]
        })
        return redirect("/contact?sent=1")
    return render_template("contact.html", sent=request.args.get("sent"))


@app.route("/add_to_cart/<int:item_id>")
def add_to_cart(item_id):
    if "user" not in session:
        return redirect("/login")
    if "cart" not in session:
        session["cart"] = []
    cart = session["cart"]
    for item in cart:
        if item["id"] == item_id:
            item["qty"] += 1
            session.modified = True
            return redirect("/shop")
    products = db_get("products", {"id": item_id})
    if products:
        p = products[0]
        cart.append({"id": p["id"], "name": p["name"],
                     "price": float(p["price"]), "image": p["image"], "qty": 1})
        session.modified = True
    return redirect("/shop")


@app.route("/cart/increase/<int:item_id>")
def increase_qty(item_id):
    if "cart" in session:
        for item in session["cart"]:
            if item["id"] == item_id:
                item["qty"] += 1
                session.modified = True
                break
    return redirect("/cart")


@app.route("/cart/decrease/<int:item_id>")
def decrease_qty(item_id):
    if "cart" in session:
        for item in session["cart"]:
            if item["id"] == item_id:
                if item["qty"] > 1:
                    item["qty"] -= 1
                else:
                    session["cart"] = [i for i in session["cart"] if i["id"] != item_id]
                session.modified = True
                break
    return redirect("/cart")


@app.route("/remove_from_cart/<int:item_id>")
def remove_from_cart(item_id):
    if "cart" in session:
        session["cart"] = [i for i in session["cart"] if i["id"] != item_id]
        session.modified = True
    return redirect("/cart")


@app.route("/cart")
def cart():
    if "user" not in session:
        return redirect("/login")
    cart = session.get("cart", [])
    total = sum(i["price"] * i["qty"] for i in cart)
    return render_template("cart.html", cart=cart, total=total)


@app.route("/checkout", methods=["GET", "POST"])
def checkout():
    if "user" not in session:
        return redirect("/login")
    cart = session.get("cart", [])
    total = sum(i["price"] * i["qty"] for i in cart)
    users = db_get("users", {"username": session["user"]})
    user = users[0] if users else {}
    if request.method == "POST":
        payment = request.form["payment"]
        order = db_insert("orders", {
            "username": session["user"],
            "name": request.form["name"],
            "email": request.form["email"],
            "phone": request.form["phone"],
            "address": request.form["address"],
            "payment": payment,
            "total": total
        })
        order_id = order[0]["id"]
        for item in cart:
            db_insert("order_items", {
                "order_id": order_id,
                "product_name": item["name"],
                "price": item["price"],
                "qty": item["qty"]
            })
        ordered_items = cart.copy()
        ordered_total = total
        session["cart"] = []
        session.modified = True
        return render_template("checkout.html", success=True, user=user,
                               cart=ordered_items, total=ordered_total, payment=payment)
    return render_template("checkout.html", success=False, user=user, cart=cart, total=total)


@app.route("/orders")
def my_orders():
    if "user" not in session:
        return redirect("/login")
    orders = db_get("orders", {"username": session["user"]}, order="created_at")
    return render_template("my_orders.html", orders=orders)


@app.route("/profile")
def profile():
    if "user" not in session:
        return redirect("/login")
    users = db_get("users", {"username": session["user"]})
    user = users[0] if users else {}
    return render_template("profile.html", user=user)


@app.route("/profile/update", methods=["POST"])
def update_profile():
    if "user" not in session:
        return redirect("/login")
    db_update("users", {
        "name": request.form["name"],
        "email": request.form["email"],
        "phone": request.form["phone"],
        "address": request.form["address"]
    }, {"username": session["user"]})
    return redirect("/profile")


@app.route("/profile/delete", methods=["POST"])
def delete_account():
    if "user" not in session:
        return redirect("/login")
    db_delete("users", {"username": session["user"]})
    session.clear()
    return redirect("/signup")


@app.route("/admin/dashboard")
def admin_dashboard():
    if not session.get("admin"):
        return redirect("/login")
    orders = db_get("orders", order="created_at")
    users = db_get("users")
    products = db_get("products")
    contacts = db_get("contacts", order="created_at")
    total_sales = sum(float(o["total"]) for o in orders)
    return render_template("admin_dashboard.html", orders=orders, users=users,
                           products=products, contacts=contacts, total_sales=total_sales)


@app.route("/admin/order/status", methods=["POST"])
def update_order_status():
    if not session.get("admin"):
        return redirect("/login")
    db_update("orders", {"status": request.form["status"]}, {"id": request.form["order_id"]})
    return redirect("/admin/dashboard")


@app.route("/admin/logout")
def admin_logout():
    session.pop("admin", None)
    return redirect("/login")


@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")
