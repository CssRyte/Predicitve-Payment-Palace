import os
from datetime import date, datetime
from functools import wraps
from typing import Any

import mysql.connector
from dotenv import load_dotenv
from flask import (
    Flask,
    Response,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
)
from werkzeug.security import check_password_hash, generate_password_hash

from services.conversion import calculate_packages_needed
from services.csv_import import parse_sales_csv
from services.forecasting import forecast_for_menu_item
from services.ollama_service import generate_prep_explanation, generate_reorder_explanation

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv("FLASK_SECRET_KEY", "predictive-payment-palace-dev-key")

DEFAULT_BUSINESS_ID = 1
PREP_BUFFER = 0.06
DEMO_EMAIL = "mama@soulfood.com"
DEMO_PASSWORD = "soulfood123"


def get_db_connection():
    return mysql.connector.connect(
        host=os.getenv("MYSQL_HOST", "localhost"),
        port=int(os.getenv("MYSQL_PORT", "3306")),
        database=os.getenv("MYSQL_DATABASE", "predictive_payment_palace"),
        user=os.getenv("MYSQL_USER", "palace_app"),
        password=os.getenv("MYSQL_PASSWORD", ""),
    )


def column_exists(cursor, table: str, column: str) -> bool:
    cursor.execute(
        """
        SELECT COUNT(*) AS n
        FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA = DATABASE()
          AND TABLE_NAME = %s
          AND COLUMN_NAME = %s
        """,
        (table, column),
    )
    return int(cursor.fetchone()["n"]) > 0


def ensure_schema_upgrades() -> None:
    """Idempotent upgrades for databases created before Week-3 columns."""
    try:
        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)

        if not column_exists(cur, "menu_items", "current_prep"):
            cur.execute(
                "ALTER TABLE menu_items ADD COLUMN current_prep INT NOT NULL DEFAULT 0"
            )
        if not column_exists(cur, "menu_items", "portion_note"):
            cur.execute(
                "ALTER TABLE menu_items ADD COLUMN portion_note VARCHAR(150) NULL"
            )
        if not column_exists(cur, "menu_items", "price"):
            cur.execute(
                "ALTER TABLE menu_items ADD COLUMN price DECIMAL(10,2) NULL"
            )
        if not column_exists(cur, "businesses", "email"):
            cur.execute("ALTER TABLE businesses ADD COLUMN email VARCHAR(150) NULL")
        if not column_exists(cur, "businesses", "phone"):
            cur.execute("ALTER TABLE businesses ADD COLUMN phone VARCHAR(40) NULL")

        cur.execute(
            """
            UPDATE businesses
            SET email = COALESCE(email, %s),
                phone = COALESCE(phone, %s)
            WHERE id = %s
            """,
            (DEMO_EMAIL, "(404) 555-1234", DEFAULT_BUSINESS_ID),
        )

        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id INT PRIMARY KEY AUTO_INCREMENT,
                business_id INT NOT NULL,
                email VARCHAR(150) NOT NULL UNIQUE,
                password_hash VARCHAR(255) NOT NULL,
                display_name VARCHAR(100),
                FOREIGN KEY (business_id) REFERENCES businesses(id)
            )
            """
        )

        defaults = [
            (12, "2 pcs chicken + 2 sides", 14.00, 1),
            (8, "8 oz", 4.50, 2),
            (6, "6 oz", 4.00, 3),
            (4, "6 oz", 4.00, 4),
            (10, "1 piece", 1.50, 5),
        ]
        for current_prep, portion_note, price, item_id in defaults:
            cur.execute(
                """
                UPDATE menu_items
                SET current_prep = COALESCE(NULLIF(current_prep, 0), %s),
                    portion_note = COALESCE(portion_note, %s),
                    price = COALESCE(price, %s)
                WHERE id = %s
                """,
                (current_prep, portion_note, price, item_id),
            )

        cur.execute("SELECT id FROM users WHERE email = %s", (DEMO_EMAIL,))
        if not cur.fetchone():
            cur.execute(
                """
                INSERT INTO users (business_id, email, password_hash, display_name)
                VALUES (%s, %s, %s, %s)
                """,
                (
                    DEFAULT_BUSINESS_ID,
                    DEMO_EMAIL,
                    generate_password_hash(DEMO_PASSWORD),
                    "Mama Soul",
                ),
            )

        conn.commit()
        cur.close()
        conn.close()
    except mysql.connector.Error:
        pass


ensure_schema_upgrades()


def business_initials(name: str) -> str:
    parts = [p for p in name.replace("'", " ").split() if p]
    if not parts:
        return "PP"
    if len(parts) == 1:
        return parts[0][:2].upper()
    return (parts[0][0] + parts[1][0]).upper()


def unit_label(selling_unit: str) -> str:
    unit = (selling_unit or "").lower()
    mapping = {
        "plate": "plates",
        "serving": "servings",
        "piece": "pieces",
    }
    return mapping.get(unit, selling_unit)


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if not session.get("user_id"):
            return redirect(url_for("login"))
        return view(*args, **kwargs)

    return wrapped


def fetch_business(cursor, business_id: int = DEFAULT_BUSINESS_ID) -> dict[str, Any] | None:
    cursor.execute("SELECT * FROM businesses WHERE id = %s", (business_id,))
    return cursor.fetchone()


def fetch_last_updated(cursor, business_id: int) -> str:
    cursor.execute(
        """
        SELECT MAX(sold_at) AS last_sold
        FROM transactions
        WHERE business_id = %s
        """,
        (business_id,),
    )
    row = cursor.fetchone()
    if row and row.get("last_sold"):
        ts = row["last_sold"]
        if isinstance(ts, datetime):
            return ts.strftime("%b %-d, %Y")
        return str(ts)
    return date.today().strftime("%b %-d, %Y")


def fetch_menu_items(cursor, business_id: int) -> list[dict[str, Any]]:
    cursor.execute(
        """
        SELECT id, name, selling_unit, current_prep, portion_note, price
        FROM menu_items
        WHERE business_id = %s
        ORDER BY id
        """,
        (business_id,),
    )
    return cursor.fetchall()


def fetch_dow_sales(
    cursor,
    business_id: int,
    menu_item_id: int,
    meal_period: str,
    weekday: int,
    before: date | None = None,
) -> list[int]:
    params: list[Any] = [business_id, menu_item_id, meal_period, weekday]
    before_clause = ""
    if before is not None:
        before_clause = "AND DATE(sold_at) < %s"
        params.append(before.isoformat())
    cursor.execute(
        f"""
        SELECT quantity
        FROM transactions
        WHERE business_id = %s
          AND menu_item_id = %s
          AND meal_period = %s
          AND WEEKDAY(sold_at) = %s
          {before_clause}
        ORDER BY sold_at DESC
        """,
        tuple(params),
    )
    return [int(row["quantity"]) for row in cursor.fetchall()]


def build_prep_recommendations(
    cursor,
    business_id: int,
    target: date,
    meal_period: str,
) -> list[dict[str, Any]]:
    weekday = target.weekday()
    recommendations: list[dict[str, Any]] = []

    for item in fetch_menu_items(cursor, business_id):
        sales = fetch_dow_sales(cursor, business_id, item["id"], meal_period, weekday)
        forecast = forecast_for_menu_item(sales, PREP_BUFFER)
        recommendations.append(
            {
                "menu_item_id": item["id"],
                "name": item["name"],
                "unit": item["selling_unit"],
                "unit_label": unit_label(item["selling_unit"]),
                "current_prep": int(item.get("current_prep") or 0),
                "price": float(item["price"] or 0) if item.get("price") is not None else 0.0,
                **forecast,
            }
        )
    return recommendations


def count_reorder_needs(cursor, business_id: int, recommendations: list[dict]) -> tuple[int, int]:
    high_priority = 0
    needing = 0
    for rec in recommendations:
        cursor.execute(
            """
            SELECT i.id, i.current_quantity, r.amount_per_serving,
                   sp.quantity_per_package, sp.package_cost
            FROM recipes r
            JOIN ingredients i ON i.id = r.ingredient_id
            LEFT JOIN supplier_packages sp ON sp.ingredient_id = i.id
            WHERE r.menu_item_id = %s
            LIMIT 1
            """,
            (rec["menu_item_id"],),
        )
        row = cursor.fetchone()
        if not row or not row.get("quantity_per_package"):
            continue
        packages = calculate_packages_needed(
            rec["recommended_prep"],
            float(row["amount_per_serving"]),
            float(row["current_quantity"] or 0),
            float(row["quantity_per_package"]),
        )
        if packages > 0:
            needing += 1
            if float(row["current_quantity"] or 0) < rec["recommended_prep"] * float(
                row["amount_per_serving"]
            ) * 0.25:
                high_priority += 1
    return needing, high_priority


def build_history_context(cursor, business_id: int) -> dict[str, Any]:
    cursor.execute(
        """
        SELECT mi.name, SUM(t.quantity) AS total_qty
        FROM transactions t
        JOIN menu_items mi ON mi.id = t.menu_item_id
        WHERE t.business_id = %s
        GROUP BY mi.id, mi.name
        ORDER BY total_qty DESC
        """,
        (business_id,),
    )
    mix_rows = cursor.fetchall()
    grand = sum(float(r["total_qty"]) for r in mix_rows) or 1.0
    sales_mix = [
        {
            "name": r["name"],
            "percent": round(100.0 * float(r["total_qty"]) / grand),
        }
        for r in mix_rows
    ]

    cursor.execute(
        """
        SELECT dow_inner AS dow, AVG(day_total) AS avg_qty
        FROM (
            SELECT DATE(sold_at) AS sale_day, WEEKDAY(sold_at) AS dow_inner,
                   SUM(quantity) AS day_total
            FROM transactions
            WHERE business_id = %s AND meal_period = 'Dinner'
            GROUP BY DATE(sold_at), WEEKDAY(sold_at)
        ) daily
        GROUP BY dow_inner
        ORDER BY dow
        """,
        (business_id,),
    )
    by_dow = {int(r["dow"]): float(r["avg_qty"]) for r in cursor.fetchall()}
    max_avg = max(by_dow.values()) if by_dow else 1.0
    dow_labels = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    demand_by_day = [
        {
            "label": dow_labels[i],
            "height": int(round(100 * by_dow.get(i, 0) / max_avg)) if max_avg else 0,
            "value": int(round(by_dow.get(i, 0))),
        }
        for i in range(7)
    ]

    cursor.execute(
        """
        SELECT DATE(sold_at) AS sale_day, SUM(quantity) AS total_qty
        FROM transactions
        WHERE business_id = %s AND meal_period = 'Dinner'
        GROUP BY DATE(sold_at)
        ORDER BY sale_day
        """,
        (business_id,),
    )
    volume_rows = cursor.fetchall()
    volume_max = max((float(r["total_qty"]) for r in volume_rows), default=1.0)
    volume_points = []
    for idx, row in enumerate(volume_rows):
        x = 0 if len(volume_rows) == 1 else int(round(400 * idx / (len(volume_rows) - 1)))
        y = int(round(140 - (120 * float(row["total_qty"]) / volume_max)))
        volume_points.append(f"{x},{y}")
    volume_polyline = " ".join(volume_points)

    comparisons: list[dict[str, Any]] = []
    cursor.execute(
        """
        SELECT DATE(t.sold_at) AS sale_day, t.menu_item_id, mi.name, mi.price,
               SUM(t.quantity) AS actual
        FROM transactions t
        JOIN menu_items mi ON mi.id = t.menu_item_id
        WHERE t.business_id = %s AND t.meal_period = 'Dinner'
        GROUP BY DATE(t.sold_at), t.menu_item_id, mi.name, mi.price
        ORDER BY sale_day DESC
        LIMIT 8
        """,
        (business_id,),
    )
    recent = cursor.fetchall()
    over_units = 0
    under_units = 0
    abs_errors: list[int] = []
    over_cost = 0.0

    for row in recent:
        sale_day = row["sale_day"]
        if isinstance(sale_day, datetime):
            sale_day = sale_day.date()
        elif isinstance(sale_day, str):
            sale_day = date.fromisoformat(sale_day)

        prior = fetch_dow_sales(
            cursor,
            business_id,
            int(row["menu_item_id"]),
            "Dinner",
            sale_day.weekday(),
            before=sale_day,
        )
        forecast = forecast_for_menu_item(prior, PREP_BUFFER)
        actual = int(row["actual"])
        predicted = forecast["recommended_prep"]
        diff = actual - predicted
        price = float(row["price"] or 0)
        money_diff = abs(diff) * price
        abs_errors.append(abs(diff))
        if diff < 0:
            over_units += abs(diff)
            over_cost += money_diff
        elif diff > 0:
            under_units += diff

        comparisons.append(
            {
                "date": sale_day.strftime("%b %-d"),
                "item": row["name"],
                "forecast": predicted,
                "actual": actual,
                "difference": f"{diff:+d}",
                "difference_money": f"${money_diff:.2f}",
            }
        )

    avg_error = round(sum(abs_errors) / len(abs_errors), 1) if abs_errors else 0
    accuracy = 0
    if abs_errors:
        # Rough accuracy: 100 - mean absolute % error capped
        mape_proxy = []
        for row, err in zip(recent, abs_errors):
            actual = max(int(row["actual"]), 1)
            mape_proxy.append(100.0 * err / actual)
        accuracy = max(0, int(round(100 - (sum(mape_proxy) / len(mape_proxy)))))

    return {
        "sales_mix": sales_mix,
        "demand_by_day": demand_by_day,
        "volume_polyline": volume_polyline,
        "comparisons": comparisons,
        "accuracy": {
            "overall": f"{accuracy}%",
            "over_prep": f"{over_units} units",
            "over_cost": f"${over_cost:.2f}",
            "under_prep": f"{under_units} units",
            "avg_error": f"{avg_error} units",
        },
    }


def dashboard_context(business: dict[str, Any] | None, last_updated: str) -> dict[str, Any]:
    name = business["name"] if business else "Mama's Soul Food"
    return {
        "business_name": name,
        "business_initials": business_initials(name),
        "last_updated": last_updated,
        "logged_in": bool(session.get("user_id")),
        "user_email": session.get("user_email"),
    }


def parse_target_date(raw: str | None) -> date:
    if raw:
        try:
            return date.fromisoformat(raw)
        except ValueError:
            pass
    return date(2026, 8, 5)


@app.route("/", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        email = (request.form.get("email") or "").strip().lower()
        password = request.form.get("password") or ""
        try:
            conn = get_db_connection()
            cur = conn.cursor(dictionary=True)
            cur.execute("SELECT * FROM users WHERE email = %s", (email,))
            user = cur.fetchone()
            cur.close()
            conn.close()
            if user and check_password_hash(user["password_hash"], password):
                session["user_id"] = user["id"]
                session["user_email"] = user["email"]
                session["business_id"] = user["business_id"]
                return redirect(url_for("prep"))
            error = "Invalid email or password."
        except mysql.connector.Error:
            # Fallback demo login if users table is unavailable
            if email == DEMO_EMAIL and password == DEMO_PASSWORD:
                session["user_id"] = 1
                session["user_email"] = DEMO_EMAIL
                session["business_id"] = DEFAULT_BUSINESS_ID
                return redirect(url_for("prep"))
            error = "Could not verify login. Check MySQL, then try again."
    elif session.get("user_id"):
        return redirect(url_for("prep"))

    return render_template(
        "login.html",
        error=error,
        demo_email=DEMO_EMAIL,
        demo_password=DEMO_PASSWORD,
    )


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/onboarding")
@login_required
def onboarding():
    ctx = {"active_nav": "onboarding"}
    try:
        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)
        business = fetch_business(cur)
        ctx.update(dashboard_context(business, fetch_last_updated(cur, DEFAULT_BUSINESS_ID)))
        cur.close()
        conn.close()
    except mysql.connector.Error:
        ctx.update(dashboard_context(None, date.today().strftime("%b %-d, %Y")))
    return render_template("onboarding.html", **ctx)


@app.route("/menu-suppliers")
@login_required
def menu_suppliers():
    tab = request.args.get("tab", "menu")
    ctx: dict[str, Any] = {
        "active_nav": "menu_suppliers",
        "tab": tab,
        "menu_items": [],
        "ingredients": [],
        "suppliers": [],
        "ingredient_options": [],
    }
    try:
        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)
        business = fetch_business(cur)
        ctx.update(dashboard_context(business, fetch_last_updated(cur, DEFAULT_BUSINESS_ID)))
        ctx["menu_items"] = fetch_menu_items(cur, DEFAULT_BUSINESS_ID)

        cur.execute(
            """
            SELECT i.id, i.name, i.inventory_unit, i.current_quantity,
                   r.amount_per_serving, mi.name AS menu_item_name, mi.id AS menu_item_id
            FROM ingredients i
            LEFT JOIN recipes r ON r.ingredient_id = i.id
            LEFT JOIN menu_items mi ON mi.id = r.menu_item_id
            WHERE i.business_id = %s
            ORDER BY i.id
            """,
            (DEFAULT_BUSINESS_ID,),
        )
        ctx["ingredients"] = cur.fetchall()

        cur.execute(
            """
            SELECT id, name, inventory_unit
            FROM ingredients
            WHERE business_id = %s
            ORDER BY name
            """,
            (DEFAULT_BUSINESS_ID,),
        )
        ctx["ingredient_options"] = cur.fetchall()

        cur.execute(
            """
            SELECT sp.id, sp.supplier_name, sp.package_unit, sp.quantity_per_package,
                   sp.package_cost, i.name AS ingredient_name, i.inventory_unit
            FROM supplier_packages sp
            JOIN ingredients i ON i.id = sp.ingredient_id
            WHERE i.business_id = %s
            ORDER BY sp.supplier_name, i.name
            """,
            (DEFAULT_BUSINESS_ID,),
        )
        ctx["suppliers"] = cur.fetchall()

        cur.close()
        conn.close()
    except mysql.connector.Error:
        ctx.update(dashboard_context(None, date.today().strftime("%b %-d, %Y")))
    return render_template("menu-suppliers.html", **ctx)


@app.route("/menu-suppliers/add-item", methods=["POST"])
@login_required
def add_menu_item():
    name = (request.form.get("name") or "").strip()
    unit = (request.form.get("selling_unit") or "serving").strip()
    portion = (request.form.get("portion_note") or "").strip() or None
    try:
        price = float(request.form.get("price") or 0)
        current_prep = int(request.form.get("current_prep") or 0)
    except ValueError:
        flash("Price and current prep must be numbers.", "error")
        return redirect(url_for("menu_suppliers", tab="menu"))

    if not name:
        flash("Menu item name is required.", "error")
        return redirect(url_for("menu_suppliers", tab="menu"))

    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO menu_items
                (business_id, name, selling_unit, current_prep, portion_note, price)
            VALUES (%s, %s, %s, %s, %s, %s)
            """,
            (DEFAULT_BUSINESS_ID, name, unit, current_prep, portion, price),
        )
        conn.commit()
        cur.close()
        conn.close()
        flash(f"Added menu item “{name}”.", "success")
    except mysql.connector.Error as exc:
        flash(f"Could not add menu item: {exc}", "error")
    return redirect(url_for("menu_suppliers", tab="menu"))


@app.route("/menu-suppliers/update-item", methods=["POST"])
@login_required
def update_menu_item():
    try:
        item_id = int(request.form.get("item_id") or 0)
        current_prep = int(request.form.get("current_prep") or 0)
        price = float(request.form.get("price") or 0)
    except ValueError:
        flash("Invalid item values.", "error")
        return redirect(url_for("menu_suppliers", tab="menu"))

    portion = (request.form.get("portion_note") or "").strip() or None
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE menu_items
            SET current_prep = %s, price = %s, portion_note = %s
            WHERE id = %s AND business_id = %s
            """,
            (current_prep, price, portion, item_id, DEFAULT_BUSINESS_ID),
        )
        conn.commit()
        cur.close()
        conn.close()
        flash("Menu item updated.", "success")
    except mysql.connector.Error as exc:
        flash(f"Could not update item: {exc}", "error")
    return redirect(url_for("menu_suppliers", tab="menu"))


@app.route("/menu-suppliers/add-ingredient", methods=["POST"])
@login_required
def add_ingredient():
    name = (request.form.get("name") or "").strip()
    unit = (request.form.get("inventory_unit") or "lb").strip()
    try:
        on_hand = float(request.form.get("current_quantity") or 0)
        amount = float(request.form.get("amount_per_serving") or 0)
        menu_item_id = int(request.form.get("menu_item_id") or 0)
    except ValueError:
        flash("Quantity fields must be numbers.", "error")
        return redirect(url_for("menu_suppliers", tab="ingredients"))

    if not name or menu_item_id <= 0 or amount <= 0:
        flash("Ingredient name, menu item, and amount per serving are required.", "error")
        return redirect(url_for("menu_suppliers", tab="ingredients"))

    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO ingredients (business_id, name, inventory_unit, current_quantity)
            VALUES (%s, %s, %s, %s)
            """,
            (DEFAULT_BUSINESS_ID, name, unit, on_hand),
        )
        ingredient_id = cur.lastrowid
        cur.execute(
            """
            INSERT INTO recipes (menu_item_id, ingredient_id, amount_per_serving)
            VALUES (%s, %s, %s)
            """,
            (menu_item_id, ingredient_id, amount),
        )
        conn.commit()
        cur.close()
        conn.close()
        flash(f"Added ingredient “{name}” with conversion rule.", "success")
    except mysql.connector.Error as exc:
        flash(f"Could not add ingredient: {exc}", "error")
    return redirect(url_for("menu_suppliers", tab="ingredients"))


@app.route("/menu-suppliers/add-supplier", methods=["POST"])
@login_required
def add_supplier_package():
    supplier = (request.form.get("supplier_name") or "").strip()
    package_unit = (request.form.get("package_unit") or "case").strip()
    try:
        ingredient_id = int(request.form.get("ingredient_id") or 0)
        qty = float(request.form.get("quantity_per_package") or 0)
        cost = float(request.form.get("package_cost") or 0)
    except ValueError:
        flash("Package quantity and cost must be numbers.", "error")
        return redirect(url_for("menu_suppliers", tab="suppliers"))

    if not supplier or ingredient_id <= 0 or qty <= 0:
        flash("Supplier, ingredient, and quantity per package are required.", "error")
        return redirect(url_for("menu_suppliers", tab="suppliers"))

    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO supplier_packages
                (ingredient_id, supplier_name, package_unit, quantity_per_package, package_cost)
            VALUES (%s, %s, %s, %s, %s)
            """,
            (ingredient_id, supplier, package_unit, qty, cost),
        )
        conn.commit()
        cur.close()
        conn.close()
        flash(f"Added supplier package from {supplier}.", "success")
    except mysql.connector.Error as exc:
        flash(f"Could not add supplier package: {exc}", "error")
    return redirect(url_for("menu_suppliers", tab="suppliers"))


@app.route("/data-source", methods=["GET", "POST"])
@login_required
def data_source():
    ctx: dict[str, Any] = {
        "active_nav": "data_source",
        "transaction_count": 0,
        "upload_summary": None,
    }

    if request.method == "POST":
        upload = request.files.get("sales_csv")
        if not upload or not upload.filename:
            flash("Choose a CSV file to upload.", "error")
            return redirect(url_for("data_source"))

        rows, errors = parse_sales_csv(upload)
        if errors and not rows:
            for err in errors[:5]:
                flash(err, "error")
            return redirect(url_for("data_source"))

        try:
            conn = get_db_connection()
            cur = conn.cursor(dictionary=True)
            cur.execute(
                "SELECT id, name FROM menu_items WHERE business_id = %s",
                (DEFAULT_BUSINESS_ID,),
            )
            name_to_id = {r["name"].lower(): r["id"] for r in cur.fetchall()}

            inserted = 0
            skipped = 0
            for row in rows:
                menu_id = name_to_id.get(row["menu_item"].lower())
                if not menu_id:
                    skipped += 1
                    errors.append(f"Unknown menu item: {row['menu_item']}")
                    continue
                cur.execute(
                    """
                    INSERT INTO transactions
                        (business_id, menu_item_id, quantity, meal_period, sold_at)
                    VALUES (%s, %s, %s, %s, %s)
                    """,
                    (
                        DEFAULT_BUSINESS_ID,
                        menu_id,
                        row["quantity"],
                        row["meal_period"],
                        row["sold_at"],
                    ),
                )
                inserted += 1
            conn.commit()
            cur.close()
            conn.close()
            ctx["upload_summary"] = {
                "inserted": inserted,
                "skipped": skipped,
                "warnings": errors[:8],
            }
            flash(
                f"Imported {inserted} transaction(s)"
                + (f"; skipped {skipped}." if skipped else "."),
                "success" if inserted else "error",
            )
        except mysql.connector.Error as exc:
            flash(f"Upload failed: {exc}", "error")
            return redirect(url_for("data_source"))

    try:
        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)
        business = fetch_business(cur)
        ctx.update(dashboard_context(business, fetch_last_updated(cur, DEFAULT_BUSINESS_ID)))
        cur.execute(
            "SELECT COUNT(*) AS n FROM transactions WHERE business_id = %s",
            (DEFAULT_BUSINESS_ID,),
        )
        ctx["transaction_count"] = int(cur.fetchone()["n"])
        cur.close()
        conn.close()
    except mysql.connector.Error:
        ctx.update(dashboard_context(None, date.today().strftime("%b %-d, %Y")))
    return render_template("data-source.html", **ctx)


@app.route("/data-source/sample.csv")
@login_required
def download_sample_csv():
    path = os.path.join(app.root_path, "database", "sample_sales_upload.csv")
    with open(path, encoding="utf-8") as handle:
        content = handle.read()
    return Response(
        content,
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=sample_sales_upload.csv"},
    )


@app.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    ctx: dict[str, Any] = {"active_nav": "settings"}

    if request.method == "POST":
        name = (request.form.get("name") or "").strip()
        email = (request.form.get("email") or "").strip()
        phone = (request.form.get("phone") or "").strip()
        address = (request.form.get("address") or "").strip()
        business_type = (request.form.get("business_type") or "Restaurant").strip()
        if not name:
            flash("Business name is required.", "error")
            return redirect(url_for("settings"))
        try:
            conn = get_db_connection()
            cur = conn.cursor()
            cur.execute(
                """
                UPDATE businesses
                SET name = %s, email = %s, phone = %s, address = %s, business_type = %s
                WHERE id = %s
                """,
                (name, email, phone, address, business_type, DEFAULT_BUSINESS_ID),
            )
            conn.commit()
            cur.close()
            conn.close()
            flash("Business settings saved.", "success")
        except mysql.connector.Error as exc:
            flash(f"Could not save settings: {exc}", "error")
        return redirect(url_for("settings"))

    try:
        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)
        business = fetch_business(cur)
        ctx.update(dashboard_context(business, fetch_last_updated(cur, DEFAULT_BUSINESS_ID)))
        if business:
            ctx["business"] = business
        cur.close()
        conn.close()
    except mysql.connector.Error:
        ctx.update(dashboard_context(None, date.today().strftime("%b %-d, %Y")))
        ctx["business"] = {
            "name": "Mama's Soul Food",
            "address": "123 Lakewood Ave, Atlanta, GA",
            "email": DEMO_EMAIL,
            "phone": "(404) 555-1234",
            "business_type": "Restaurant",
        }
    return render_template("settings.html", **ctx)


@app.route("/prep")
@login_required
def prep():
    target = parse_target_date(request.args.get("date"))
    meal_period = request.args.get("meal_period", "Dinner")
    weekday_name = target.strftime("%A")

    ctx: dict[str, Any] = {
        "active_nav": "prep",
        "target_date": target.isoformat(),
        "meal_period": meal_period,
        "recommendations": [],
        "ollama_connected": False,
        "ai_paragraphs": [
            "Connect MySQL and load seed data to compute live prep recommendations.",
        ],
        "metrics": {
            "predicted_orders": 0,
            "predicted_orders_trend": f"For {weekday_name} {meal_period.lower()}",
            "recommended_prep_total": 0,
            "items_needing_reorder": 0,
            "reorder_priority_note": "—",
            "waste_avoided": 0,
        },
    }

    try:
        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)
        business = fetch_business(cur)
        ctx.update(dashboard_context(business, fetch_last_updated(cur, DEFAULT_BUSINESS_ID)))

        recommendations = build_prep_recommendations(
            cur, DEFAULT_BUSINESS_ID, target, meal_period
        )
        ctx["recommendations"] = recommendations

        predicted = sum(r["forecasted_demand"] for r in recommendations)
        recommended_total = sum(r["recommended_prep"] for r in recommendations)
        needing, high_priority = count_reorder_needs(cur, DEFAULT_BUSINESS_ID, recommendations)
        waste_units = sum(
            max(r["recommended_prep"] - r["forecasted_demand"], 0) for r in recommendations
        )

        ctx["metrics"] = {
            "predicted_orders": predicted,
            "predicted_orders_trend": f"Based on past {weekday_name} {meal_period.lower()} sales",
            "recommended_prep_total": recommended_total,
            "items_needing_reorder": needing,
            "reorder_priority_note": (
                f"{high_priority} are high priority" if high_priority else "None urgent"
            ),
            "waste_avoided": int(round(waste_units * 2.5)),
        }

        business_name = business["name"] if business else "Mama's Soul Food"
        ai_text, connected = generate_prep_explanation(
            business_name,
            meal_period,
            target.isoformat(),
            recommendations,
        )
        ctx["ollama_connected"] = connected
        ctx["ai_paragraphs"] = [p.strip() for p in ai_text.split("\n\n") if p.strip()]

        cur.close()
        conn.close()
    except mysql.connector.Error:
        ctx.update(dashboard_context(None, date.today().strftime("%b %-d, %Y")))

    return render_template("prep.html", **ctx)


@app.route("/reorder")
@login_required
def reorder():
    target = parse_target_date(request.args.get("date"))
    meal_period = request.args.get("meal_period", "Dinner")

    ctx: dict[str, Any] = {
        "active_nav": "reorder",
        "target_date": target.isoformat(),
        "meal_period": meal_period,
        "reorder_rows": [],
        "estimated_total": "$0.00",
        "ollama_connected": False,
        "ai_paragraphs": ["Load MySQL seed data to compute reorder quantities."],
    }

    try:
        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)
        business = fetch_business(cur)
        ctx.update(dashboard_context(business, fetch_last_updated(cur, DEFAULT_BUSINESS_ID)))

        recommendations = build_prep_recommendations(
            cur, DEFAULT_BUSINESS_ID, target, meal_period
        )
        rec_by_item = {r["menu_item_id"]: r for r in recommendations}

        cur.execute(
            """
            SELECT i.id, i.name, i.inventory_unit, i.current_quantity,
                   r.menu_item_id, r.amount_per_serving,
                   sp.supplier_name, sp.package_unit, sp.quantity_per_package, sp.package_cost
            FROM ingredients i
            JOIN recipes r ON r.ingredient_id = i.id
            LEFT JOIN supplier_packages sp ON sp.ingredient_id = i.id
            WHERE i.business_id = %s
            ORDER BY i.id
            """,
            (DEFAULT_BUSINESS_ID,),
        )
        rows = []
        total = 0.0
        for row in cur.fetchall():
            rec = rec_by_item.get(row["menu_item_id"])
            if not rec or not row.get("quantity_per_package"):
                continue
            needed_amount = rec["recommended_prep"] * float(row["amount_per_serving"])
            packages = calculate_packages_needed(
                rec["recommended_prep"],
                float(row["amount_per_serving"]),
                float(row["current_quantity"] or 0),
                float(row["quantity_per_package"]),
            )
            cost = packages * float(row["package_cost"] or 0)
            total += cost
            unit = row["package_unit"]
            rows.append(
                {
                    "ingredient": row["name"],
                    "needed_amount": f"{needed_amount:.0f} {row['inventory_unit']}",
                    "order_unit": (
                        f"{unit} ({row['quantity_per_package']:.0f} {row['inventory_unit']})"
                    ),
                    "reorder_quantity": f"{packages} {unit}" + ("" if packages == 1 else "s"),
                    "estimated_cost": f"${cost:.2f}",
                    "supplier": row["supplier_name"] or "—",
                    "packages": packages,
                }
            )

        ctx["reorder_rows"] = rows
        ctx["estimated_total"] = f"${total:.2f}"

        business_name = business["name"] if business else "Mama's Soul Food"
        ai_text, connected = generate_reorder_explanation(
            business_name,
            target.isoformat(),
            rows,
        )
        ctx["ollama_connected"] = connected
        ctx["ai_paragraphs"] = [p.strip() for p in ai_text.split("\n\n") if p.strip()]

        cur.close()
        conn.close()
    except mysql.connector.Error:
        ctx.update(dashboard_context(None, date.today().strftime("%b %-d, %Y")))

    return render_template("reorder.html", **ctx)


@app.route("/history")
@login_required
def history():
    ctx: dict[str, Any] = {
        "active_nav": "history",
        "sales_mix": [],
        "demand_by_day": [],
        "volume_polyline": "",
        "comparisons": [],
        "accuracy": {
            "overall": "—",
            "over_prep": "—",
            "over_cost": "—",
            "under_prep": "—",
            "avg_error": "—",
        },
    }
    try:
        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)
        business = fetch_business(cur)
        ctx.update(dashboard_context(business, fetch_last_updated(cur, DEFAULT_BUSINESS_ID)))
        ctx.update(build_history_context(cur, DEFAULT_BUSINESS_ID))
        cur.close()
        conn.close()
    except mysql.connector.Error:
        ctx.update(dashboard_context(None, date.today().strftime("%b %-d, %Y")))
    return render_template("history.html", **ctx)


@app.route("/history/export.csv")
@login_required
def history_export():
    import csv
    import io

    try:
        conn = get_db_connection()
        cur = conn.cursor(dictionary=True)
        history_data = build_history_context(cur, DEFAULT_BUSINESS_ID)
        cur.close()
        conn.close()
    except mysql.connector.Error as exc:
        flash(f"Could not export history: {exc}", "error")
        return redirect(url_for("history"))

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(["date", "item", "forecast", "actual", "difference", "difference_money"])
    for row in history_data["comparisons"]:
        writer.writerow(
            [
                row["date"],
                row["item"],
                row["forecast"],
                row["actual"],
                row["difference"],
                row["difference_money"],
            ]
        )
    return Response(
        buffer.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=forecast_vs_actual.csv"},
    )


@app.route("/test-database")
def test_database():
    connection = get_db_connection()
    cursor = connection.cursor(dictionary=True)
    cursor.execute("SELECT * FROM businesses LIMIT 1")
    business = cursor.fetchone()
    cursor.close()
    connection.close()
    return jsonify(business)


if __name__ == "__main__":
    app.run(debug=True)
