from datetime import datetime
import os
import re

import pymysql
from dotenv import load_dotenv
from flask import Flask, jsonify, request
from flask_cors import CORS

load_dotenv()

app = Flask(__name__)
CORS(app)


@app.errorhandler(Exception)
def handle_unexpected_error(error):
    app.logger.exception("Unhandled error: %s", error)
    return jsonify({"message": "Internal server error", "detail": str(error)}), 500


def get_connection():
    # Railway MySQL plugin uses MYSQLHOST/MYSQLUSER/... naming convention.
    # Fall back to DB_HOST/DB_USER/... for local / custom env vars.
    host = os.getenv("MYSQLHOST") or os.getenv("DB_HOST", "127.0.0.1")
    user = os.getenv("MYSQLUSER") or os.getenv("DB_USER", "root")
    password = os.getenv("MYSQLPASSWORD") or os.getenv("DB_PASSWORD", "1234")
    database = os.getenv("MYSQLDATABASE") or os.getenv("DB_NAME", "test")
    port = int(os.getenv("MYSQLPORT") or os.getenv("DB_PORT", 3306))
    return pymysql.connect(
        host=host,
        user=user,
        password=password,
        database=database,
        port=port,
        cursorclass=pymysql.cursors.DictCursor,
        charset="utf8mb4",
        autocommit=True,
    )


@app.get("/api/health")
def health():
    return jsonify({"status": "ok", "time": datetime.utcnow().isoformat() + "Z"})


@app.get("/api/products")
def get_products():
    keyword = request.args.get("q", "").strip()
    category = request.args.get("category", "").strip()
    gender = request.args.get("gender", "").strip()
    limit = min(max(int(request.args.get("limit", 24)), 1), 100)
    offset = max(int(request.args.get("offset", 0)), 0)

    where = []
    where_params = []
    relevance_params = []
    relevance_parts = ["0"]

    if keyword:
        normalized = " ".join(keyword.lower().split())
        terms = [t for t in re.split(r"\s+", normalized) if t][:5]

        where.append("(LOWER(`ProductTitle`) LIKE %s OR LOWER(`Usage`) LIKE %s)")
        where_params.extend([f"%{normalized}%", f"%{normalized}%"])

        # Weighted relevance: exact > prefix > contains, then token-level boosts.
        relevance_parts.extend(
            [
                "CASE WHEN LOWER(`ProductTitle`) = %s THEN 140 ELSE 0 END",
                "CASE WHEN LOWER(`Usage`) = %s THEN 120 ELSE 0 END",
                "CASE WHEN LOWER(`ProductTitle`) LIKE %s THEN 90 ELSE 0 END",
                "CASE WHEN LOWER(`Usage`) LIKE %s THEN 70 ELSE 0 END",
                "CASE WHEN LOWER(`ProductTitle`) LIKE %s THEN 45 ELSE 0 END",
                "CASE WHEN LOWER(`Usage`) LIKE %s THEN 35 ELSE 0 END",
                "CASE WHEN LOWER(`ProductType`) LIKE %s THEN 20 ELSE 0 END",
                "CASE WHEN LOWER(`SubCategory`) LIKE %s THEN 15 ELSE 0 END",
            ]
        )
        relevance_params.extend(
            [
                normalized,
                normalized,
                f"{normalized}%",
                f"{normalized}%",
                f"%{normalized}%",
                f"%{normalized}%",
                f"%{normalized}%",
                f"%{normalized}%",
            ]
        )

        for term in terms:
            relevance_parts.extend(
                [
                    "CASE WHEN LOWER(`ProductTitle`) LIKE %s THEN 14 ELSE 0 END",
                    "CASE WHEN LOWER(`Usage`) LIKE %s THEN 10 ELSE 0 END",
                ]
            )
            relevance_params.extend([f"%{term}%", f"%{term}%"])
    if category:
        where.append("Category = %s")
        where_params.append(category)
    if gender:
        where.append("Gender = %s")
        where_params.append(gender)

    where_sql = ""
    if where:
        where_sql = "WHERE " + " AND ".join(where)

    relevance_sql = " + ".join(relevance_parts)

    sql = f"""
        SELECT
            `ProductId`,
            `Gender`,
            `Category`,
            `SubCategory`,
            `ProductType`,
            `Colour`,
            CASE
                WHEN `ProductTitle` IN ('Casual', 'Sports', 'Ethnic', 'Formal', 'Smart Casual')
                THEN `Usage`
                ELSE `ProductTitle`
            END AS `ProductTitle`,
            CASE
                WHEN `ProductTitle` IN ('Casual', 'Sports', 'Ethnic', 'Formal', 'Smart Casual')
                THEN `ProductTitle`
                ELSE `Usage`
            END AS `Usage`,
            `Image`,
            `ImageURL`,
            ({relevance_sql}) AS `Relevance`
        FROM `fashion`
        {where_sql}
        ORDER BY `Relevance` DESC, `ProductId` DESC
        LIMIT %s OFFSET %s
    """
    params = [*relevance_params, *where_params, limit, offset]

    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(sql, params)
            rows = cursor.fetchall()

    return jsonify(rows)


@app.get("/api/filters")
def get_filters():
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute("SELECT DISTINCT Category FROM fashion ORDER BY Category")
            categories = [r["Category"] for r in cursor.fetchall()]

            cursor.execute("SELECT DISTINCT Gender FROM fashion ORDER BY Gender")
            genders = [r["Gender"] for r in cursor.fetchall()]

    return jsonify({"categories": categories, "genders": genders})


@app.post("/api/cart/events")
def create_cart_event():
    payload = request.get_json(silent=True) or {}
    user_id = payload.get("userId", "guest")
    product_id = payload.get("productId")
    action = payload.get("action", "add_to_cart")

    if not product_id:
        return jsonify({"message": "productId is required"}), 400

    # Recommendation-ready user behavior log table.
    with get_connection() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS user_behavior_events (
                    id BIGINT AUTO_INCREMENT PRIMARY KEY,
                    user_id VARCHAR(64) NOT NULL,
                    product_id BIGINT NOT NULL,
                    action VARCHAR(64) NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    INDEX idx_user_id (user_id),
                    INDEX idx_product_id (product_id),
                    INDEX idx_action (action)
                ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4
                """
            )
            cursor.execute(
                """
                INSERT INTO user_behavior_events (user_id, product_id, action)
                VALUES (%s, %s, %s)
                """,
                (user_id, product_id, action),
            )

    return jsonify({"ok": True})

@app.get("/api/recommendation-sql-example")
def recommendation_sql_example():
    return jsonify(
        {
            "note": "Run this SQL directly later for simple recommendation logic.",
            "sql": """
SELECT f2.ProductId, f2.ProductTitle, f2.ImageURL, COUNT(*) AS score
FROM user_behavior_events e1
JOIN user_behavior_events e2
  ON e1.user_id = e2.user_id
 AND e1.product_id <> e2.product_id
JOIN fashion f2
  ON f2.ProductId = e2.product_id
WHERE e1.user_id = %s
  AND e1.action = 'add_to_cart'
  AND e2.action = 'add_to_cart'
GROUP BY f2.ProductId, f2.ProductTitle, f2.ImageURL
ORDER BY score DESC
LIMIT 12;
            """.strip(),
        }
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)), debug=False)
