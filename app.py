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


# LOGOUT
@app.route("/logout")
def logout():
    session.clear()
    return redirect("/login")


if __name__ == "__main__":
    init_db()
    app.run(debug=True)
