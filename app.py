from flask import Flask, render_template, request, redirect, url_for, session, jsonify, flash
from werkzeug.security import generate_password_hash, check_password_hash
import sqlite3
from functools import wraps
from datetime import datetime

app = Flask(__name__)
app.secret_key = "college-crm-secret-key-change-in-production"
DATABASE = "crm.db"

def get_db():
    conn = sqlite3.connect(DATABASE)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn

def init_db():
    conn = get_db()
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL UNIQUE,
        email TEXT NOT NULL UNIQUE,
        password_hash TEXT NOT NULL,
        role TEXT NOT NULL DEFAULT 'sales_rep'
    );

    CREATE TABLE IF NOT EXISTS customers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        email TEXT,
        phone TEXT,
        company TEXT,
        notes TEXT
    );

    CREATE TABLE IF NOT EXISTS leads (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        customer_id INTEGER NOT NULL,
        status TEXT NOT NULL DEFAULT 'New',
        assigned_to INTEGER,
        notes TEXT,
        FOREIGN KEY(customer_id) REFERENCES customers(id) ON DELETE CASCADE,
        FOREIGN KEY(assigned_to) REFERENCES users(id) ON DELETE SET NULL
    );

    CREATE TABLE IF NOT EXISTS interactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        lead_id INTEGER NOT NULL,
        interaction_type TEXT NOT NULL,
        description TEXT NOT NULL,
        date TEXT NOT NULL,
        FOREIGN KEY(lead_id) REFERENCES leads(id) ON DELETE CASCADE
    );
    """)
    # Create a demo admin account if no users exist.
    if conn.execute("SELECT COUNT(*) FROM users").fetchone()[0] == 0:
        conn.execute(
            "INSERT INTO users(username,email,password_hash,role) VALUES(?,?,?,?)",
            ("admin", "admin@crm.local", generate_password_hash("admin123"), "admin")
        )
        conn.execute(
            "INSERT INTO users(username,email,password_hash,role) VALUES(?,?,?,?)",
            ("sales", "sales@crm.local", generate_password_hash("sales123"), "sales_rep")
        )
    conn.commit()
    conn.close()

def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if "user_id" not in session:
            flash("Please log in to continue.", "warning")
            return redirect(url_for("login"))
        return view(*args, **kwargs)
    return wrapped

@app.route("/")
def index():
    if "user_id" in session:
        return redirect(url_for("dashboard"))
    return redirect(url_for("login"))

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"].strip()
        password = request.form["password"]
        conn = get_db()
        user = conn.execute("SELECT * FROM users WHERE username=?", (username,)).fetchone()
        conn.close()
        if user and check_password_hash(user["password_hash"], password):
            session["user_id"] = user["id"]
            session["username"] = user["username"]
            session["role"] = user["role"]
            return redirect(url_for("dashboard"))
        flash("Invalid username or password.", "danger")
    return render_template("login.html")

@app.route("/signup", methods=["GET", "POST"])
def signup():
    if request.method == "POST":
        username = request.form["username"].strip()
        email = request.form["email"].strip()
        password = request.form["password"]
        if len(password) < 6:
            flash("Password must contain at least 6 characters.", "danger")
            return render_template("signup.html")
        conn = get_db()
        try:
            conn.execute(
                "INSERT INTO users(username,email,password_hash,role) VALUES(?,?,?,?)",
                (username, email, generate_password_hash(password), "sales_rep")
            )
            conn.commit()
            flash("Account created successfully. Please log in.", "success")
            return redirect(url_for("login"))
        except sqlite3.IntegrityError:
            flash("Username or email already exists.", "danger")
        finally:
            conn.close()
    return render_template("signup.html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.route("/dashboard")
@login_required
def dashboard():
    conn = get_db()
    stats = {
        "customers": conn.execute("SELECT COUNT(*) FROM customers").fetchone()[0],
        "leads": conn.execute("SELECT COUNT(*) FROM leads").fetchone()[0],
        "interactions": conn.execute("SELECT COUNT(*) FROM interactions").fetchone()[0],
        "converted": conn.execute("SELECT COUNT(*) FROM leads WHERE status='Converted'").fetchone()[0],
    }
    status_rows = conn.execute(
        "SELECT status, COUNT(*) AS count FROM leads GROUP BY status"
    ).fetchall()
    recent = conn.execute("""
        SELECT i.*, c.name AS customer_name, l.status
        FROM interactions i
        JOIN leads l ON i.lead_id=l.id
        JOIN customers c ON l.customer_id=c.id
        ORDER BY i.id DESC LIMIT 5
    """).fetchall()
    conn.close()
    status_data = {row["status"]: row["count"] for row in status_rows}
    return render_template("dashboard.html", stats=stats, status_data=status_data, recent=recent)

@app.route("/customers")
@login_required
def customers():
    conn = get_db()
    rows = conn.execute("SELECT * FROM customers ORDER BY id DESC").fetchall()
    conn.close()
    return render_template("customers.html", customers=rows)

@app.route("/customers/add", methods=["GET", "POST"])
@login_required
def add_customer():
    if request.method == "POST":
        conn = get_db()
        conn.execute(
            "INSERT INTO customers(name,email,phone,company,notes) VALUES(?,?,?,?,?)",
            tuple(request.form.get(k, "").strip() for k in ["name","email","phone","company","notes"])
        )
        conn.commit()
        conn.close()
        flash("Customer added.", "success")
        return redirect(url_for("customers"))
    return render_template("customer_form.html", customer=None)

@app.route("/customers/edit/<int:customer_id>", methods=["GET", "POST"])
@login_required
def edit_customer(customer_id):
    conn = get_db()
    customer = conn.execute("SELECT * FROM customers WHERE id=?", (customer_id,)).fetchone()
    if not customer:
        conn.close()
        flash("Customer not found.", "danger")
        return redirect(url_for("customers"))
    if request.method == "POST":
        conn.execute(
            "UPDATE customers SET name=?,email=?,phone=?,company=?,notes=? WHERE id=?",
            (request.form["name"], request.form["email"], request.form["phone"],
             request.form["company"], request.form["notes"], customer_id)
        )
        conn.commit()
        conn.close()
        flash("Customer updated.", "success")
        return redirect(url_for("customers"))
    conn.close()
    return render_template("customer_form.html", customer=customer)

@app.route("/customers/delete/<int:customer_id>", methods=["POST"])
@login_required
def delete_customer(customer_id):
    conn = get_db()
    conn.execute("DELETE FROM customers WHERE id=?", (customer_id,))
    conn.commit()
    conn.close()
    flash("Customer deleted.", "success")
    return redirect(url_for("customers"))

@app.route("/leads")
@login_required
def leads():
    status = request.args.get("status", "")
    conn = get_db()
    query = """
        SELECT l.*, c.name AS customer_name, u.username AS assigned_name
        FROM leads l
        JOIN customers c ON l.customer_id=c.id
        LEFT JOIN users u ON l.assigned_to=u.id
    """
    params = ()
    if status:
        query += " WHERE l.status=?"
        params = (status,)
    query += " ORDER BY l.id DESC"
    rows = conn.execute(query, params).fetchall()
    conn.close()
    return render_template("leads.html", leads=rows, selected_status=status)

@app.route("/leads/add", methods=["GET", "POST"])
@login_required
def add_lead():
    conn = get_db()
    if request.method == "POST":
        conn.execute(
            "INSERT INTO leads(customer_id,status,assigned_to,notes) VALUES(?,?,?,?)",
            (request.form["customer_id"], request.form["status"],
             request.form.get("assigned_to") or None, request.form["notes"])
        )
        conn.commit()
        conn.close()
        flash("Lead created.", "success")
        return redirect(url_for("leads"))
    customers_list = conn.execute("SELECT * FROM customers ORDER BY name").fetchall()
    users = conn.execute("SELECT id,username FROM users ORDER BY username").fetchall()
    conn.close()
    return render_template("lead_form.html", customers=customers_list, users=users)

@app.route("/leads/edit/<int:lead_id>", methods=["GET", "POST"])
@login_required
def edit_lead(lead_id):
    conn = get_db()
    lead = conn.execute("SELECT * FROM leads WHERE id=?", (lead_id,)).fetchone()
    if not lead:
        conn.close()
        flash("Lead not found.", "danger")
        return redirect(url_for("leads"))
    if request.method == "POST":
        conn.execute(
            "UPDATE leads SET customer_id=?,status=?,assigned_to=?,notes=? WHERE id=?",
            (request.form["customer_id"], request.form["status"],
             request.form.get("assigned_to") or None, request.form["notes"], lead_id)
        )
        conn.commit()
        conn.close()
        flash("Lead updated.", "success")
        return redirect(url_for("leads"))
    customers_list = conn.execute("SELECT * FROM customers ORDER BY name").fetchall()
    users = conn.execute("SELECT id,username FROM users ORDER BY username").fetchall()
    conn.close()
    return render_template("lead_form.html", lead=lead, customers=customers_list, users=users)

@app.route("/leads/delete/<int:lead_id>", methods=["POST"])
@login_required
def delete_lead(lead_id):
    conn = get_db()
    conn.execute("DELETE FROM leads WHERE id=?", (lead_id,))
    conn.commit()
    conn.close()
    flash("Lead deleted.", "success")
    return redirect(url_for("leads"))

@app.route("/interactions", methods=["GET", "POST"])
@login_required
def interactions():
    conn = get_db()
    if request.method == "POST":
        conn.execute(
            "INSERT INTO interactions(lead_id,interaction_type,description,date) VALUES(?,?,?,?)",
            (request.form["lead_id"], request.form["interaction_type"],
             request.form["description"], datetime.now().strftime("%Y-%m-%d %H:%M"))
        )
        conn.commit()
        conn.close()
        flash("Interaction logged.", "success")
        return redirect(url_for("interactions"))
    rows = conn.execute("""
        SELECT i.*, c.name AS customer_name
        FROM interactions i
        JOIN leads l ON i.lead_id=l.id
        JOIN customers c ON l.customer_id=c.id
        ORDER BY i.id DESC
    """).fetchall()
    lead_rows = conn.execute("""
        SELECT l.id, c.name AS customer_name, l.status
        FROM leads l JOIN customers c ON l.customer_id=c.id
        ORDER BY c.name
    """).fetchall()
    conn.close()
    return render_template("interactions.html", interactions=rows, leads=lead_rows)

@app.route("/api/stats")
@login_required
def api_stats():
    conn = get_db()
    data = {
        "customers": conn.execute("SELECT COUNT(*) FROM customers").fetchone()[0],
        "leads": conn.execute("SELECT COUNT(*) FROM leads").fetchone()[0],
        "interactions": conn.execute("SELECT COUNT(*) FROM interactions").fetchone()[0],
        "converted": conn.execute("SELECT COUNT(*) FROM leads WHERE status='Converted'").fetchone()[0]
    }
    conn.close()
    return jsonify(data)

@app.route("/api/leads")
@login_required
def api_leads():
    conn = get_db()
    rows = conn.execute("""
        SELECT l.id, c.name AS customer, l.status, u.username AS assigned_to, l.notes
        FROM leads l
        JOIN customers c ON l.customer_id=c.id
        LEFT JOIN users u ON l.assigned_to=u.id
        ORDER BY l.id DESC
    """).fetchall()
    conn.close()
    return jsonify([dict(row) for row in rows])

@app.route("/seed-demo")
@login_required
def seed_demo():
    conn = get_db()
    if conn.execute("SELECT COUNT(*) FROM customers").fetchone()[0] == 0:
        customer_data = [
            ("Aarav Sharma", "aarav@example.com", "9876543210", "Aarav Technologies", "Interested in annual software plan."),
            ("Meera Gupta", "meera@example.com", "9876501234", "Bright Solutions", "Requested a product demo."),
            ("Rohan Verma", "rohan@example.com", "9812345678", "RV Enterprises", "Follow-up required next week.")
        ]
        conn.executemany(
            "INSERT INTO customers(name,email,phone,company,notes) VALUES(?,?,?,?,?)",
            customer_data
        )
    customers_rows = conn.execute("SELECT id FROM customers ORDER BY id").fetchall()
    sales_id = conn.execute("SELECT id FROM users WHERE username='sales'").fetchone()["id"]
    if conn.execute("SELECT COUNT(*) FROM leads").fetchone()[0] == 0 and customers_rows:
        statuses = ["New", "Contacted", "Qualified", "Converted"]
        for idx, c in enumerate(customers_rows[:4]):
            conn.execute(
                "INSERT INTO leads(customer_id,status,assigned_to,notes) VALUES(?,?,?,?)",
                (c["id"], statuses[idx % len(statuses)], sales_id, "Demo lead created for project presentation.")
            )
    conn.commit()
    conn.close()
    flash("Demo data loaded.", "success")
    return redirect(url_for("dashboard"))

if __name__ == "__main__":
    init_db()
    app.run(debug=True)
