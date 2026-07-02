import os
import re
import sqlite3
from datetime import timedelta
from functools import wraps

from dotenv import load_dotenv
from flask import (
    Flask,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from flask_bcrypt import Bcrypt
from markupsafe import escape

load_dotenv()

app = Flask(__name__)
bcrypt = Bcrypt(app)

app.config["SECRET_KEY"] = os.getenv(
    "SECRET_KEY",
    os.urandom(64).hex(),
)
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["SESSION_COOKIE_SECURE"] = os.getenv("ENV", "development") == "production"
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(minutes=30)
app.config["SESSION_PERMANENT"] = True
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024

DB_PATH = os.path.join(os.path.dirname(__file__), "users.db")


def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db():
    with get_db() as db:
        db.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                email TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            CREATE UNIQUE INDEX IF NOT EXISTS idx_users_username ON users(username);
            CREATE UNIQUE INDEX IF NOT EXISTS idx_users_email ON users(email);
        """)


init_db()


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "user_id" not in session:
            flash("Please log in to access this page.", "warning")
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


def validate_username(username):
    if not username or len(username) < 3 or len(username) > 30:
        return False, "Username must be between 3 and 30 characters."
    if not re.match(r"^[a-zA-Z0-9_]+$", username):
        return False, "Username can only contain letters, numbers, and underscores."
    return True, ""


def validate_email(email):
    if not email or "@" not in email or "." not in email:
        return False, "Please provide a valid email address."
    if len(email) > 120:
        return False, "Email address is too long."
    return True, ""


def validate_password(password):
    if not password or len(password) < 8 or len(password) > 128:
        return False, "Password must be between 8 and 128 characters."
    if not re.search(r"[A-Z]", password):
        return False, "Password must contain at least one uppercase letter."
    if not re.search(r"[a-z]", password):
        return False, "Password must contain at least one lowercase letter."
    if not re.search(r"[0-9]", password):
        return False, "Password must contain at least one digit."
    if not re.search(r"[!@#$%^&*(),.?\":{}|<>_\-+]", password):
        return False, "Password must contain at least one special character."
    return True, ""


@app.route("/")
def index():
    return render_template("index.html")


@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm_password", "")

        valid, msg = validate_username(username)
        if not valid:
            flash(msg, "danger")
            return render_template("register.html")

        valid, msg = validate_email(email)
        if not valid:
            flash(msg, "danger")
            return render_template("register.html")

        valid, msg = validate_password(password)
        if not valid:
            flash(msg, "danger")
            return render_template("register.html")

        if password != confirm:
            flash("Passwords do not match.", "danger")
            return render_template("register.html")

        password_hash = bcrypt.generate_password_hash(password).decode("utf-8")

        try:
            with get_db() as db:
                db.execute(
                    "INSERT INTO users (username, email, password_hash) VALUES (?, ?, ?)",
                    (username, email, password_hash),
                )
            flash("Registration successful! Please log in.", "success")
            return redirect(url_for("login"))
        except sqlite3.IntegrityError:
            flash("Username or email already taken.", "danger")
            return render_template("register.html")

    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        if not username or not password:
            flash("Please fill in all fields.", "danger")
            return render_template("login.html")

        with get_db() as db:
            user = db.execute(
                "SELECT * FROM users WHERE username = ? OR email = ?",
                (username, username),
            ).fetchone()

        if user is None:
            flash("Invalid username/email or password.", "danger")
            return render_template("login.html")

        if not bcrypt.check_password_hash(user["password_hash"], password):
            flash("Invalid username/email or password.", "danger")
            return render_template("login.html")

        session.permanent = True
        session["user_id"] = user["id"]
        session["username"] = user["username"]
        session["logged_in"] = True

        flash(f"Welcome back, {escape(user['username'])}!", "success")
        return redirect(url_for("dashboard"))

    return render_template("login.html")


@app.route("/dashboard")
@login_required
def dashboard():
    with get_db() as db:
        user = db.execute(
            "SELECT username, email, created_at FROM users WHERE id = ?",
            (session["user_id"],),
        ).fetchone()
    return render_template("dashboard.html", user=user)


@app.route("/logout")
@login_required
def logout():
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for("index"))


@app.errorhandler(404)
def not_found(e):
    return render_template("index.html"), 404


@app.errorhandler(405)
def method_not_allowed(e):
    flash("Method not allowed.", "warning")
    return redirect(url_for("index"))


@app.errorhandler(500)
def server_error(e):
    flash("An internal error occurred. Please try again.", "danger")
    return redirect(url_for("index"))


if __name__ == "__main__":
    app.run(
        host=os.getenv("HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", 5000)),
        debug=os.getenv("ENV", "development") == "development",
    )
