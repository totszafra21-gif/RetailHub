from flask import Flask, render_template, request, redirect, session
import mysql.connector
from werkzeug.security import generate_password_hash, check_password_hash

app = Flask(__name__)
app.secret_key = "retailhub_secret"

DB_CONFIG = {
    "host": "localhost",
    "user": "root",
    "password": "",
    "database": "retailhub"
}


def get_db():
    conn = mysql.connector.connect(**DB_CONFIG)
    return conn


def init_db():
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
    CREATE TABLE IF NOT EXISTS users(
        id INT AUTO_INCREMENT PRIMARY KEY,
        name VARCHAR(100),
        username VARCHAR(100) UNIQUE,
        email VARCHAR(100) UNIQUE,
        phone VARCHAR(20),
        address TEXT,
        password VARCHAR(255)
    )
    """)

    conn.commit()
    cursor.close()
    conn.close()


# HOME
@app.route("/")
def home():
    if "user" in session:
        return render_template("home.html", user=session["user"])
    return redirect("/login")


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

        conn = get_db()
        cursor = conn.cursor()

        try:
            cursor.execute("""
            INSERT INTO users(name, username, email, phone, address, password)
            VALUES(%s,%s,%s,%s,%s,%s)
            """, (name, username, email, phone, address, password))

            conn.commit()
            return redirect("/login")

        except Exception as e:
            return f"Error: {e}"

        finally:
            cursor.close()
            conn.close()

    return render_template("signup.html")


# LOGIN
@app.route("/login", methods=["GET", "POST"])
def login():

    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]

        conn = get_db()
        cursor = conn.cursor(dictionary=True)

        cursor.execute(
            "SELECT * FROM users WHERE username=%s",
            (username,)
        )
        user = cursor.fetchone()
        cursor.close()
        conn.close()

        if user and check_password_hash(user["password"], password):
            session["user"] = username
            return redirect("/")
        else:
            return "Invalid credentials"

    return render_template("login.html")

@app.route("/shop")
def shop():
    if "user" not in session:
        return redirect("/login")
    conn = get_db()
    cursor = conn.cursor(dictionary=True)

    category = request.args.get("category")

    if category:
        cursor.execute("SELECT * FROM products WHERE category=%s", (category,))
    else:
        cursor.execute("SELECT * FROM products")

    products = cursor.fetchall()
    cursor.close()
    conn.close()

    return render_template("shop.html", products=products)

@app.route("/contact", methods=["GET", "POST"])
def contact():
    if "user" not in session:
        return redirect("/login")

    if request.method == "POST":
        name = request.form["name"]
        email = request.form["email"]
        message = request.form["message"]

        return "Message sent successfully!"

    return render_template("contact.html")

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

    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM products WHERE id=%s", (item_id,))
    product = cursor.fetchone()
    cursor.close()
    conn.close()

    if product:
        cart.append({"id": product["id"], "name": product["name"], "price": float(product["price"]), "image": product["image"], "qty": 1})
        session.modified = True

    return redirect("/shop")


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

# PROFILE
@app.route("/profile")
def profile():
    if "user" not in session:
        return redirect("/login")

    conn = get_db()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM users WHERE username=%s", (session["user"],))
    user = cursor.fetchone()
    cursor.close()
    conn.close()

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

    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("""
            UPDATE users SET name=%s, email=%s, phone=%s, address=%s
            WHERE username=%s
        """, (name, email, phone, address, session["user"]))
        conn.commit()
    except Exception as e:
        return f"Error: {e}"
    finally:
        cursor.close()
        conn.close()

    return redirect("/profile")


# DELETE ACCOUNT
@app.route("/profile/delete", methods=["POST"])
def delete_account():
    if "user" not in session:
        return redirect("/login")

    conn = get_db()
    cursor = conn.cursor()
    try:
        cursor.execute("DELETE FROM users WHERE username=%s", (session["user"],))
        conn.commit()
    finally:
        cursor.close()
        conn.close()

    session.clear()
    return redirect("/signup")

# LOGOUT
@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")




if __name__ == "__main__":
    init_db()
    app.run(debug=True)
