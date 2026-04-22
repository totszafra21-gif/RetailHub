from flask import Flask, render_template, request, redirect, session
from supabase import create_client
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = "retailhub_secret"

SUPABASE_URL = "https://xfeehkqvaxdrwvsgoaqv.supabase.co"
SUPABASE_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InhmZWVoa3F2YXhkcnd2c2dvYXF2Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzU0NjE5NTcsImV4cCI6MjA5MTAzNzk1N30.mnsrn9RO5Lg2fanSaae-1FgOz0lN3SCWzkUUSv6zi9A"

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

FALLBACK_PRODUCTS = [
    {"id": 1, "name": "Gaming Laptop", "price": 32999, "category": "laptop", "image": "images/laptop.jpg"},
    {"id": 2, "name": "Smartphone", "price": 9999, "category": "phone", "image": "images/phone.jpg"},
    {"id": 3, "name": "Running Shoes", "price": 2499, "category": "shoes", "image": "images/shoes.jpg"},
    {"id": 4, "name": "Classic Watch", "price": 4999, "category": "watch", "image": "images/watch.jpg"},
    {"id": 5, "name": "Wireless Headset", "price": 799, "category": "accessories", "image": "images/headset.jpg"},
]


def get_products_data(category=None):
    try:
        query = supabase.table("products").select("*")
        if category:
            query = query.eq("category", category)
        result = query.execute()
        return result.data, None
    except Exception:
        products = FALLBACK_PRODUCTS
        if category:
            products = [p for p in products if p["category"].lower() == category.lower()]
        return products, "Live product data is temporarily unavailable. Showing offline items instead."


def get_product_data(item_id):
    try:
        result = supabase.table("products").select("*").eq("id", item_id).execute()
        if result.data:
            return result.data[0]
    except Exception:
        pass

    for product in FALLBACK_PRODUCTS:
        if product["id"] == item_id:
            return product
    return None


ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "admin123"


def require_admin():
    if not session.get("admin"):
        return redirect("/admin")
    return None


def get_admin_overview_data():
    orders = supabase.table("orders").select("*").order("created_at", desc=True).execute().data
    users = supabase.table("users").select("*").execute().data
    products = supabase.table("products").select("*").execute().data
    contacts = supabase.table("contacts").select("*").order("created_at", desc=True).execute().data

    total_sales = sum(float(order.get("total", 0) or 0) for order in orders)

    order_status_counts = {
        "Pending": 0,
        "Delivered": 0,
        "Completed": 0,
        "Cancelled": 0
    }
    for order in orders:
        status = order.get("status") or "Pending"
        order_status_counts[status] = order_status_counts.get(status, 0) + 1

    product_category_counts = {}
    for product in products:
        category = (product.get("category") or "Uncategorized").title()
        product_category_counts[category] = product_category_counts.get(category, 0) + 1

    sales_by_day = {}
    for order in orders:
        created_at = order.get("created_at") or ""
        day = created_at[:10] if created_at else "Unknown"
        sales_by_day[day] = sales_by_day.get(day, 0) + float(order.get("total", 0) or 0)

    sales_labels = list(reversed(list(sales_by_day.keys())[:7]))
    sales_values = [sales_by_day[label] for label in sales_labels]

    return {
        "orders": orders,
        "users": users,
        "products": products,
        "contacts": contacts,
        "total_sales": total_sales,
        "recent_orders": orders[:5],
        "recent_contacts": contacts[:5],
        "order_status_labels": list(order_status_counts.keys()),
        "order_status_values": list(order_status_counts.values()),
        "category_labels": list(product_category_counts.keys()),
        "category_values": list(product_category_counts.values()),
        "sales_labels": sales_labels,
        "sales_values": sales_values
    }


# HOME
@app.route("/")
def home():
    return render_template("home.html", user=session.get("user"))


@app.route("/admin", methods=["GET", "POST"])
def admin_login():
    if session.get("admin"):
        return redirect("/admin/dashboard")

    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]

        if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
            session["admin"] = True
            return redirect("/admin/dashboard")

        return render_template("admin_login.html", error="Invalid admin credentials")

    return render_template("admin_login.html", error=None)


# SIGN UP
@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        name = request.form["name"]
        username = request.form["username"]
        email = request.form["email"]
        phone = request.form["phone"]
        address = request.form["address"]
        password = generate_password_hash(request.form["password"])

        try:
            supabase.table("users").insert({
                "name": name,
                "username": username,
                "email": email,
                "phone": phone,
                "address": address,
                "password": password
            }).execute()
            return redirect("/login")
        except Exception as e:
            return f"Error: {e}"

    return render_template("signup.html")


# LOGIN
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]

        if username == ADMIN_USERNAME and password == ADMIN_PASSWORD:
            session["admin"] = True
            return redirect("/admin/dashboard")

        result = supabase.table("users").select("*").eq("username", username).execute()

        if result.data:
            user = result.data[0]
            if check_password_hash(user["password"], password):
                session["user"] = username
                return redirect("/")
            else:
                return render_template("login.html", error="Invalid credentials")
        else:
            return render_template("login.html", error="Invalid credentials")

    return render_template("login.html", error=None)


# SHOP
@app.route("/shop")
def shop():
    category = request.args.get("category")
    products, shop_error = get_products_data(category)
    return render_template("shop.html", products=products, shop_error=shop_error)


# CONTACT
@app.route("/contact", methods=["GET", "POST"])
def contact():
    if "user" not in session:
        return redirect("/login")

    if request.method == "POST":
        name = request.form["name"]
        email = request.form["email"]
        message = request.form["message"]

        supabase.table("contacts").insert({
            "name": name,
            "email": email,
            "message": message
        }).execute()

        return redirect("/contact?sent=1")

    return render_template("contact.html", sent=request.args.get("sent"))


# ADD TO CART
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

    product = get_product_data(item_id)

    if product:
        cart.append({
            "id": product["id"],
            "name": product["name"],
            "price": float(product["price"]),
            "image": product["image"],
            "qty": 1
        })
        session.modified = True

    return redirect("/shop")


# INCREASE QTY
@app.route("/cart/increase/<int:item_id>")
def increase_qty(item_id):
    if "cart" in session:
        for item in session["cart"]:
            if item["id"] == item_id:
                item["qty"] += 1
                session.modified = True
                break
    return redirect("/cart")


# DECREASE QTY
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


# REMOVE FROM CART
@app.route("/remove_from_cart/<int:item_id>")
def remove_from_cart(item_id):
    if "cart" in session:
        session["cart"] = [i for i in session["cart"] if i["id"] != item_id]
        session.modified = True
    return redirect("/cart")


# VIEW CART
@app.route("/cart")
def cart():
    if "user" not in session:
        return redirect("/login")
    cart = session.get("cart", [])
    total = sum(i["price"] * i["qty"] for i in cart)
    return render_template("cart.html", cart=cart, total=total)


# CHECKOUT
@app.route("/checkout", methods=["GET", "POST"])
def checkout():
    if "user" not in session:
        return redirect("/login")

    cart = session.get("cart", [])
    total = sum(i["price"] * i["qty"] for i in cart)

    result = supabase.table("users").select("*").eq("username", session["user"]).execute()
    user = result.data[0] if result.data else {"name": "", "email": "", "phone": "", "address": ""}

    if request.method == "POST":
        name = request.form["name"]
        email = request.form["email"]
        phone = request.form["phone"]
        address = request.form["address"]
        payment = request.form["payment"]

        order = supabase.table("orders").insert({
            "username": session["user"],
            "name": name,
            "email": email,
            "phone": phone,
            "address": address,
            "payment": payment,
            "total": total
        }).execute()

        order_id = order.data[0]["id"]

        for item in cart:
            supabase.table("order_items").insert({
                "order_id": order_id,
                "product_name": item["name"],
                "price": item["price"],
                "qty": item["qty"]
            }).execute()

        ordered_items = cart.copy()
        ordered_total = total
        session["cart"] = []
        session.modified = True
        return render_template("checkout.html", success=True, user=user, cart=ordered_items, total=ordered_total, payment=payment)

    return render_template("checkout.html", success=False, user=user, cart=cart, total=total)


# MY ORDERS
@app.route("/orders")
def my_orders():
    if "user" not in session:
        return redirect("/login")

    orders = supabase.table("orders").select("*").eq("username", session["user"]).order("created_at", desc=True).execute()
    return render_template("my_orders.html", orders=orders.data)


# ADMIN DASHBOARD
@app.route("/admin/dashboard")
def admin_dashboard():
    guard = require_admin()
    if guard:
        return guard

    data = get_admin_overview_data()
    return render_template("admin_dashboard.html", active_page="dashboard", **data)


@app.route("/admin/orders")
def admin_orders():
    guard = require_admin()
    if guard:
        return guard

    orders = supabase.table("orders").select("*").order("created_at", desc=True).execute()
    return render_template("admin_orders.html", orders=orders.data, active_page="orders")


@app.route("/admin/users")
def admin_users():
    guard = require_admin()
    if guard:
        return guard

    users = supabase.table("users").select("*").execute()
    return render_template("admin_users.html", users=users.data, active_page="users")


@app.route("/admin/products")
def admin_products():
    guard = require_admin()
    if guard:
        return guard

    products = supabase.table("products").select("*").execute()
    return render_template("admin_products.html", products=products.data, active_page="products")


@app.route("/admin/contacts")
def admin_contacts():
    guard = require_admin()
    if guard:
        return guard

    contacts = supabase.table("contacts").select("*").order("created_at", desc=True).execute()
    return render_template("admin_contacts.html", contacts=contacts.data, active_page="contacts")


# ADMIN ADD PRODUCT
@app.route("/admin/product/add", methods=["POST"])
def admin_add_product():
    if not session.get("admin"):
        return redirect("/admin")
    supabase.table("products").insert({
        "name": request.form["name"],
        "price": request.form["price"],
        "category": request.form["category"],
        "image": request.form["image"]
    }).execute()
    return redirect("/admin/products")


# ADMIN EDIT PRODUCT
@app.route("/admin/product/edit", methods=["POST"])
def admin_edit_product():
    if not session.get("admin"):
        return redirect("/admin")
    supabase.table("products").update({
        "name": request.form["name"],
        "price": request.form["price"],
        "category": request.form["category"],
        "image": request.form["image"]
    }).eq("id", request.form["id"]).execute()
    return redirect("/admin/products")


# ADMIN DELETE PRODUCT
@app.route("/admin/product/delete", methods=["POST"])
def admin_delete_product():
    if not session.get("admin"):
        return redirect("/admin")
    supabase.table("products").delete().eq("id", request.form["id"]).execute()
    return redirect("/admin/products")


# ADMIN DELETE USER
@app.route("/admin/user/delete", methods=["POST"])
def admin_delete_user():
    if not session.get("admin"):
        return redirect("/admin")
    supabase.table("users").delete().eq("id", request.form["id"]).execute()
    return redirect("/admin/users")


# ADMIN DELETE CONTACT
@app.route("/admin/contact/delete", methods=["POST"])
def admin_delete_contact():
    if not session.get("admin"):
        return redirect("/admin")
    supabase.table("contacts").delete().eq("id", request.form["id"]).execute()
    return redirect("/admin/contacts")


# ADMIN UPDATE ORDER STATUS
@app.route("/admin/order/status", methods=["POST"])
def update_order_status():
    if not session.get("admin"):
        return redirect("/admin")

    order_id = request.form["order_id"]
    status = request.form["status"]

    supabase.table("orders").update({"status": status}).eq("id", order_id).execute()
    return redirect("/admin/orders")


# ADMIN LOGOUT
@app.route("/admin/logout")
def admin_logout():
    session.pop("admin", None)
    return redirect("/login")


# SALES
@app.route("/sales")
def sales():
    if "user" not in session:
        return redirect("/login")

    orders = supabase.table("orders").select("*").order("created_at", desc=True).execute()
    return render_template("sales.html", orders=orders.data)

# PROFILE
@app.route("/profile")
def profile():
    if "user" not in session:
        return redirect("/login")

    result = supabase.table("users").select("*").eq("username", session["user"]).execute()
    user = result.data[0] if result.data else {}

    return render_template("profile.html", user=user)


# UPDATE PROFILE
@app.route("/profile/update", methods=["POST"])
def update_profile():
    if "user" not in session:
        return redirect("/login")

    name = request.form["name"]
    email = request.form["email"]
    phone = request.form["phone"]
    address = request.form["address"]

    try:
        supabase.table("users").update({
            "name": name,
            "email": email,
            "phone": phone,
            "address": address
        }).eq("username", session["user"]).execute()
    except Exception as e:
        return f"Error: {e}"

    return redirect("/profile")


# DELETE ACCOUNT
@app.route("/profile/delete", methods=["POST"])
def delete_account():
    if "user" not in session:
        return redirect("/login")

    supabase.table("users").delete().eq("username", session["user"]).execute()
    session.clear()
    return redirect("/signup")


# LOGOUT
@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")


if __name__ == "__main__":
    app.run(debug=True)
