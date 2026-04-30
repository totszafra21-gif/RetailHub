import os
import random
import re
import smtplib
import ssl
import sys
import time
from email.message import EmailMessage

root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, root)

from flask import Flask, render_template, request, redirect, session
from supabase import create_client, Client
from werkzeug.security import check_password_hash, generate_password_hash

app = Flask(__name__,
    template_folder=os.path.join(root, "templates"),
    static_folder=os.path.join(root, "static")
)

app.secret_key = os.environ.get("SECRET_KEY", "retailhub_secret")
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax"
)

SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://xfeehkqvaxdrwvsgoaqv.supabase.co")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InhmZWVoa3F2YXhkcnd2c2dvYXF2Iiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzU0NjE5NTcsImV4cCI6MjA5MTAzNzk1N30.mnsrn9RO5Lg2fanSaae-1FgOz0lN3SCWzkUUSv6zi9A")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "admin123"
EMAIL_PATTERN = re.compile(r"^[A-Z0-9._%+\-]+@[A-Z0-9.\-]+\.[A-Z]{2,}$", re.IGNORECASE)


def load_env_file(path):
    if not os.path.exists(path):
        return

    with open(path, "r", encoding="utf-8") as env_file:
        for raw_line in env_file:
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key and key not in os.environ:
                os.environ[key] = value


load_env_file(os.path.join(root, ".env.local"))


def require_admin():
    if not session.get("admin"):
        return redirect("/admin")
    return None


def clean_text(value, max_length=None):
    text = (value or "").strip()
    if max_length is not None:
        text = text[:max_length]
    return text


def normalize_email(value):
    return clean_text(value, 254).lower()


def is_valid_email(email):
    if not email or ".." in email:
        return False
    return bool(EMAIL_PATTERN.fullmatch(email))


def get_user_by_username(username):
    result = supabase.table("users").select("*").eq("username", username).execute()
    return result.data[0] if result.data else None


def get_user_by_email(email):
    result = supabase.table("users").select("*").eq("email", email).execute()
    return result.data[0] if result.data else None


def email_in_use(email, exclude_username=None):
    result = supabase.table("users").select("username").eq("email", email).execute()
    if not result.data:
        return False
    return any(user["username"] != exclude_username for user in result.data)


def username_in_use(username, exclude_email=None):
    result = supabase.table("users").select("email").eq("username", username).execute()
    if not result.data:
        return False
    return any(normalize_email(user["email"]) != exclude_email for user in result.data)


def generate_available_username(base_username, email):
    seed = clean_text(base_username, 50) or normalize_email(email).split("@")[0]
    candidate = seed[:50] or "user"
    suffix = 1
    while username_in_use(candidate, exclude_email=normalize_email(email)):
        suffix_text = str(suffix)
        candidate = f"{seed[:50 - len(suffix_text)]}{suffix_text}" or f"user{suffix_text}"
        suffix += 1
    return candidate


def get_signup_redirect_url():
    configured = os.environ.get("AUTH_EMAIL_REDIRECT_TO") or os.environ.get("SITE_URL")
    base_url = (configured or request.url_root).rstrip("/")
    return f"{base_url}/login"


def get_login_code_expiry_seconds():
    raw_value = clean_text(os.environ.get("LOGIN_CODE_EXPIRY_SECONDS"), 10)
    return int(raw_value) if raw_value.isdigit() else 600


def build_login_code_email(recipient_email, code):
    message = EmailMessage()
    sender_email = os.environ.get("MAIL_FROM") or os.environ.get("MAIL_USERNAME")
    sender_name = clean_text(os.environ.get("MAIL_FROM_NAME"), 120)
    if not sender_email:
        raise RuntimeError("Missing MAIL_USERNAME or MAIL_FROM environment variable.")

    message["Subject"] = "Your RetailHub login code"
    message["From"] = f"{sender_name} <{sender_email}>" if sender_name else sender_email
    message["To"] = recipient_email
    message.set_content(
        "\n".join(
            [
                "RetailHub login verification",
                "",
                f"Your 6-digit login code is: {code}",
                f"This code expires in {get_login_code_expiry_seconds() // 60} minutes.",
                "",
                "If you did not try to log in, you can ignore this email."
            ]
        )
    )
    return message


def resolve_mail_password(smtp_host):
    smtp_password = clean_text(os.environ.get("MAIL_PASSWORD"))
    placeholder = "PASTE_YOUR_16_CHARACTER_GOOGLE_APP_PASSWORD_HERE"
    if not smtp_password or smtp_password.upper() == placeholder:
        raise RuntimeError("Set MAIL_PASSWORD to your 16-character Google App Password.")

    if "gmail.com" in smtp_host.lower():
        smtp_password = smtp_password.replace(" ", "")
        if len(smtp_password) != 16 or not smtp_password.isalnum():
            raise RuntimeError("For Gmail SMTP, MAIL_PASSWORD must be a 16-character Google App Password.")

    return smtp_password


def send_email_message(message):
    smtp_host = clean_text(os.environ.get("MAIL_SERVER"))
    smtp_port_value = clean_text(os.environ.get("MAIL_PORT"), 6)
    smtp_username = clean_text(os.environ.get("MAIL_USERNAME"))
    use_tls = clean_text(os.environ.get("MAIL_USE_TLS", "true")).lower() != "false"
    use_ssl = clean_text(os.environ.get("MAIL_USE_SSL", "false")).lower() == "true"

    if not smtp_host or not smtp_port_value.isdigit():
        raise RuntimeError("Missing MAIL_SERVER or MAIL_PORT environment variables.")

    smtp_password = resolve_mail_password(smtp_host)

    smtp_port = int(smtp_port_value)

    if use_ssl:
        with smtplib.SMTP_SSL(smtp_host, smtp_port, context=ssl.create_default_context(), timeout=20) as smtp:
            if smtp_username and smtp_password:
                smtp.login(smtp_username, smtp_password)
            smtp.send_message(message)
        return

    with smtplib.SMTP(smtp_host, smtp_port, timeout=20) as smtp:
        if use_tls:
            smtp.starttls(context=ssl.create_default_context())
        if smtp_username and smtp_password:
            smtp.login(smtp_username, smtp_password)
        smtp.send_message(message)


def send_login_code_email(recipient_email, code):
    message = build_login_code_email(recipient_email, code)
    send_email_message(message)


def build_order_confirmation_email(recipient_email, order_id):
    message = EmailMessage()
    sender_email = os.environ.get("MAIL_FROM") or os.environ.get("MAIL_USERNAME")
    sender_name = clean_text(os.environ.get("MAIL_FROM_NAME"), 120)
    if not sender_email:
        raise RuntimeError("Missing MAIL_USERNAME or MAIL_FROM environment variable.")

    message["Subject"] = f"Order #{order_id} delivered confirmation"
    message["From"] = f"{sender_name} <{sender_email}>" if sender_name else sender_email
    message["To"] = recipient_email
    message.set_content(
        "\n".join(
            [
                "RetailHub order confirmation",
                "",
                f"Thanks for confirming you received Order #{order_id}.",
                "Your order is now marked as completed.",
                "",
                "If you did not make this request, please contact support."
            ]
        )
    )
    return message


def send_order_confirmation_email(recipient_email, order_id):
    message = build_order_confirmation_email(recipient_email, order_id)
    send_email_message(message)


def create_login_code():
    return f"{random.randint(0, 999999):06d}"


def store_pending_login(local_user, auth_refresh_token=None):
    session["pending_login_user"] = local_user["username"]
    session["pending_login_email"] = normalize_email(local_user["email"])
    session["pending_login_code"] = create_login_code()
    session["pending_login_expires_at"] = int(time.time()) + get_login_code_expiry_seconds()
    if auth_refresh_token:
        session["pending_auth_refresh_token"] = auth_refresh_token
    else:
        session.pop("pending_auth_refresh_token", None)


def clear_pending_login():
    for key in [
        "pending_login_user",
        "pending_login_email",
        "pending_login_code",
        "pending_login_expires_at",
        "pending_auth_refresh_token"
    ]:
        session.pop(key, None)


def pending_login_state():
    code = session.get("pending_login_code")
    username = session.get("pending_login_user")
    email = session.get("pending_login_email")
    expires_at = session.get("pending_login_expires_at")
    if not code or not username or not email or not expires_at:
        clear_pending_login()
        return None
    return {
        "code": str(code),
        "username": username,
        "email": email,
        "expires_at": int(expires_at)
    }


def format_auth_error(exc, fallback_message):
    details = clean_text(str(exc), 300)
    return details or fallback_message


def create_local_account(name, username, email, phone, address, raw_password):
    return sync_local_user(
        email,
        {
            "name": name,
            "username": username,
            "phone": phone,
            "address": address
        },
        preferred_username=username,
        extra_payload={"password": generate_password_hash(raw_password)}
    )


def persist_auth_session(auth_session):
    refresh_token = getattr(auth_session, "refresh_token", None)
    if refresh_token:
        session["auth_refresh_token"] = refresh_token
    else:
        session.pop("auth_refresh_token", None)


def extract_auth_user(auth_response):
    if not auth_response:
        return None

    direct_user_email = getattr(auth_response, "email", None)
    if direct_user_email is not None:
        return auth_response

    wrapped_user = getattr(auth_response, "user", None)
    if wrapped_user is not None:
        return wrapped_user

    wrapped_session = getattr(auth_response, "session", None)
    if wrapped_session is not None:
        return getattr(wrapped_session, "user", None)

    return getattr(auth_response, "user", None)


def restore_auth_session():
    refresh_token = session.get("auth_refresh_token")
    if not refresh_token:
        return None

    try:
        return supabase.auth.set_session(refresh_token=refresh_token)
    except Exception:
        session.pop("auth_refresh_token", None)
        return None


def sync_local_user(email, user_metadata, preferred_username=None, extra_payload=None):
    email = normalize_email(email)
    local_user = get_user_by_email(email)
    metadata = user_metadata or {}
    username_seed = preferred_username or metadata.get("username") or email.split("@")[0]
    username = generate_available_username(username_seed, email)
    payload = {
        "name": clean_text(metadata.get("name"), 120),
        "username": username,
        "email": email,
        "phone": clean_text(metadata.get("phone"), 30),
        "address": clean_text(metadata.get("address"), 255)
    }
    if extra_payload:
        payload.update(extra_payload)

    if local_user:
        supabase.table("users").update(payload).eq("email", email).execute()
    else:
        supabase.table("users").insert(payload).execute()

    return get_user_by_email(email) or payload


def fetch_table_rows(table_name, order_by=None, desc=False):
    try:
        query = supabase.table(table_name).select("*")
        if order_by:
            query = query.order(order_by, desc=desc)
        result = query.execute()
        return result.data or [], None
    except Exception:
        return [], f"{table_name.title()} data is temporarily unavailable."


def get_admin_overview_data():
    orders, orders_error = fetch_table_rows("orders", order_by="created_at", desc=True)
    users, users_error = fetch_table_rows("users")
    products, products_error = fetch_table_rows("products")
    contacts, contacts_error = fetch_table_rows("contacts", order_by="created_at", desc=True)

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
    admin_warnings = [
        error for error in [orders_error, users_error, products_error, contacts_error]
        if error
    ]

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
        "sales_values": sales_values,
        "admin_warnings": admin_warnings
    }


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


@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        name = clean_text(request.form["name"], 120)
        username = clean_text(request.form["username"], 50)
        email = normalize_email(request.form["email"])
        phone = clean_text(request.form["phone"], 30)
        address = clean_text(request.form["address"], 255)
        raw_password = request.form["password"]

        if not is_valid_email(email):
            return render_template("signup.html", error="Please enter a valid email address.")

        if email_in_use(email):
            return render_template("signup.html", error="That email is already linked to another account.")

        if username_in_use(username):
            return render_template("signup.html", error="That username is already taken.")

        try:
            create_local_account(name, username, email, phone, address, raw_password)
            return render_template(
                "signup.html",
                error=None,
                success_message="Account created. Log in and we will send a 6-digit code to your email."
            )
        except Exception as exc:
            return render_template("signup.html", error=format_auth_error(exc, "We couldn't create your account right now."))
    return render_template("signup.html", error=None, success_message=None)


@app.route("/login", methods=["GET", "POST"])
def login():
    pending_login = pending_login_state()

    if request.method == "POST":
        if request.form.get("step") == "verify_code":
            submitted_code = clean_text(request.form.get("code"), 6)
            pending_login = pending_login_state()

            if not pending_login:
                return render_template("login.html", error="Your login code expired. Please log in again.", notice=None, code_step=False)

            if time.time() > pending_login["expires_at"]:
                clear_pending_login()
                return render_template("login.html", error="Your login code expired. Please log in again.", notice=None, code_step=False)

            if submitted_code != pending_login["code"]:
                return render_template(
                    "login.html",
                    error="Invalid verification code.",
                    notice=f"We sent a 6-digit code to {pending_login['email']}.",
                    code_step=True
                )

            refresh_token = session.get("pending_auth_refresh_token")
            if refresh_token:
                session["auth_refresh_token"] = refresh_token
            else:
                session.pop("auth_refresh_token", None)

            session["user"] = pending_login["username"]
            session["user_email"] = pending_login["email"]
            clear_pending_login()
            return redirect("/shop")

        identifier = clean_text(request.form["username"], 254)
        password = request.form["password"]

        if identifier == ADMIN_USERNAME and password == ADMIN_PASSWORD:
            session["admin"] = True
            return redirect("/admin/dashboard")

        user = get_user_by_email(normalize_email(identifier)) if "@" in identifier else get_user_by_username(identifier)
        email = normalize_email(user["email"]) if user else normalize_email(identifier)

        if not is_valid_email(email):
            return render_template("login.html", error="Use your email or your existing username to log in.", notice=None, code_step=False)

        if user and user.get("password") and check_password_hash(user["password"], password):
            local_user = {
                "username": user["username"],
                "email": normalize_email(user["email"])
            }
            try:
                store_pending_login(local_user)
                send_login_code_email(local_user["email"], session["pending_login_code"])
                return render_template(
                    "login.html",
                    error=None,
                    notice=f"We sent a 6-digit code to {local_user['email']}.",
                    code_step=True
                )
            except Exception as exc:
                clear_pending_login()
                return render_template("login.html", error=format_auth_error(exc, "We couldn't send the login code right now. Check your email settings."), notice=None, code_step=False)

        try:
            auth_session = supabase.auth.sign_in(email=email, password=password)
        except Exception as exc:
            error_text = str(exc).lower()
            if "email not confirmed" in error_text or "email_not_confirmed" in error_text:
                return render_template("login.html", error="This account still depends on Supabase email confirmation. Confirm the email first or sign up again to use the 6-digit code flow.", notice=None, code_step=False)
            return render_template("login.html", error="Invalid credentials", notice=None, code_step=False)

        try:
            auth_user = getattr(auth_session, "user", None) or supabase.auth.user()
            local_user = sync_local_user(
                email,
                getattr(auth_user, "user_metadata", {}),
                preferred_username=user["username"] if user else None
            )
            store_pending_login(local_user, getattr(auth_session, "refresh_token", None))
            send_login_code_email(local_user["email"], session["pending_login_code"])
        except Exception as exc:
            clear_pending_login()
            return render_template("login.html", error=format_auth_error(exc, "We couldn't send the login code right now. Check your email settings."), notice=None, code_step=False)

        return render_template(
            "login.html",
            error=None,
            notice=f"We sent a 6-digit code to {local_user['email']}.",
            code_step=True
        )
    notice = "Email confirmed. Log in and we will send a 6-digit code to your email." if request.args.get("verified") else None
    return render_template("login.html", error=None, notice=notice, code_step=bool(pending_login))


@app.route("/shop")
def shop():
    category = request.args.get("category")
    if category:
        result = supabase.table("products").select("*").eq("category", category).execute()
    else:
        result = supabase.table("products").select("*").execute()
    return render_template("shop.html", products=result.data)


@app.route("/contact", methods=["GET", "POST"])
def contact():
    if "user" not in session:
        return redirect("/login")
    user = get_user_by_username(session["user"]) or {"name": "", "email": ""}
    if request.method == "POST":
        name = clean_text(request.form["name"], 120)
        email = normalize_email(user.get("email"))
        message = clean_text(request.form["message"], 2000)

        if not is_valid_email(email):
            return render_template("contact.html", sent=None, error="Add a valid email to your profile before sending a message.", user=user)

        supabase.table("contacts").insert({
            "name": name,
            "email": email,
            "message": message
        }).execute()
        return redirect("/contact?sent=1")
    return render_template("contact.html", sent=request.args.get("sent"), error=None, user=user)


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
    result = supabase.table("products").select("*").eq("id", item_id).execute()
    if result.data:
        p = result.data[0]
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
    user = get_user_by_username(session["user"]) or {"name": "", "email": "", "phone": "", "address": ""}
    if request.method == "POST":
        name = clean_text(request.form["name"], 120)
        email = normalize_email(request.form["email"])
        phone = clean_text(request.form["phone"], 30)
        address = clean_text(request.form["address"], 255)
        payment = clean_text(request.form["payment"], 20)

        if not is_valid_email(email):
            return render_template("checkout.html", success=False, error="Please enter a valid email address.", user=user, cart=cart, total=total)

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
        return render_template("checkout.html", success=True, error=None, user=user,
                               cart=ordered_items, total=ordered_total, payment=payment)
    return render_template("checkout.html", success=False, error=None, user=user, cart=cart, total=total)


@app.route("/orders")
def my_orders():
    if "user" not in session:
        return redirect("/login")
    orders = supabase.table("orders").select("*").eq("username", session["user"]).order("created_at", desc=True).execute()
    notice = None
    error = None
    if request.args.get("confirmed") == "1":
        notice = "Order confirmed. We sent a confirmation email and marked it as completed."
    elif request.args.get("error") == "not_delivered":
        error = "You can only confirm orders that are marked as Delivered."
    elif request.args.get("error") == "not_found":
        error = "Order not found."
    elif request.args.get("error") == "email":
        error = "We couldn't send the confirmation email. Please check your email settings and try again."
    return render_template("my_orders.html", orders=orders.data, notice=notice, error=error)


@app.route("/orders/confirm/<order_id>", methods=["POST"])
def confirm_order_delivery(order_id):
    if "user" not in session:
        return redirect("/login")

    result = supabase.table("orders").select("*").eq("id", order_id).execute()
    if not result.data:
        return redirect("/orders?error=not_found")

    order = result.data[0]
    if (order.get("username") or "") != session["user"]:
        return redirect("/orders?error=not_found")

    if (order.get("status") or "Pending") != "Delivered":
        return redirect("/orders?error=not_delivered")

    recipient_email = normalize_email(order.get("email"))
    if not is_valid_email(recipient_email):
        return redirect("/orders?error=email")

    try:
        send_order_confirmation_email(recipient_email, order_id)
    except Exception:
        return redirect("/orders?error=email")

    supabase.table("orders").update({"status": "Completed"}).eq("id", order_id).execute()
    return redirect("/orders?confirmed=1")


@app.route("/profile")
def profile():
    if "user" not in session:
        return redirect("/login")
    user = get_user_by_username(session["user"]) or {}
    return render_template("profile.html", user=user, error=None, notice=None)


@app.route("/profile/update", methods=["POST"])
def update_profile():
    if "user" not in session:
        return redirect("/login")
    name = clean_text(request.form["name"], 120)
    email = normalize_email(request.form["email"])
    phone = clean_text(request.form["phone"], 30)
    address = clean_text(request.form["address"], 255)
    current_user = get_user_by_username(session["user"]) or {}

    if not is_valid_email(email):
        current_user.update({"name": name, "email": email, "phone": phone, "address": address})
        return render_template("profile.html", user=current_user, error="Please enter a valid email address.", notice=None)

    if email_in_use(email, exclude_username=session["user"]):
        current_user.update({"name": name, "email": email, "phone": phone, "address": address})
        return render_template("profile.html", user=current_user, error="That email is already linked to another account.", notice=None)

    metadata = {
        "name": name,
        "username": session["user"],
        "phone": phone,
        "address": address
    }
    if email != normalize_email(current_user.get("email")):
        auth_session = restore_auth_session()
        if not auth_session:
            current_user.update({"name": name, "email": email, "phone": phone, "address": address})
            return render_template("profile.html", user=current_user, error="Log in again before changing your email address.", notice=None)

        supabase.auth.update({
            "email": email,
            "data": metadata
        })
        current_user.update({"name": name, "email": email, "phone": phone, "address": address})
        return render_template("profile.html", user=current_user, error=None, notice="Check your new email address to confirm the change.")

    supabase.table("users").update({
        "name": name,
        "email": email,
        "phone": phone,
        "address": address
    }).eq("username", session["user"]).execute()
    return redirect("/profile")


@app.route("/profile/delete", methods=["POST"])
def delete_account():
    if "user" not in session:
        return redirect("/login")
    supabase.table("users").delete().eq("username", session["user"]).execute()
    session.clear()
    return redirect("/signup")


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

    orders, _ = fetch_table_rows("orders", order_by="created_at", desc=True)
    return render_template("admin_orders.html", orders=orders, active_page="orders")


@app.route("/admin/users")
def admin_users():
    guard = require_admin()
    if guard:
        return guard

    users, _ = fetch_table_rows("users")
    return render_template("admin_users.html", users=users, active_page="users")


@app.route("/admin/products")
def admin_products():
    guard = require_admin()
    if guard:
        return guard

    products, _ = fetch_table_rows("products")
    return render_template("admin_products.html", products=products, active_page="products")


@app.route("/admin/contacts")
def admin_contacts():
    guard = require_admin()
    if guard:
        return guard

    contacts, _ = fetch_table_rows("contacts", order_by="created_at", desc=True)
    return render_template("admin_contacts.html", contacts=contacts, active_page="contacts")


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


@app.route("/admin/order/status", methods=["POST"])
def update_order_status():
    if not session.get("admin"):
        return redirect("/admin")
    supabase.table("orders").update({"status": request.form["status"]}).eq("id", request.form["order_id"]).execute()
    return redirect("/admin/orders")


@app.route("/admin/logout")
def admin_logout():
    session.pop("admin", None)
    return redirect("/login")


@app.route("/logout")
def logout():
    restore_auth_session()
    try:
        supabase.auth.sign_out()
    except Exception:
        pass
    session.clear()
    return redirect("/login")
