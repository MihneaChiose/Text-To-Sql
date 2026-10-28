import sqlite3
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
DB_PATH = PROJECT_ROOT / "data" / "test_db.sqlite"

DB_PATH.parent.mkdir(parents=True, exist_ok=True)

conn = sqlite3.connect(DB_PATH)

try:
    conn.execute("PRAGMA foreign_keys = ON")

    conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            signup_date DATE
        );

        CREATE TABLE IF NOT EXISTS orders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            order_date DATE,
            total_amount REAL,
            FOREIGN KEY (user_id) REFERENCES users (id)
        );

        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            product_name TEXT NOT NULL,
            price REAL,
            stock INTEGER
        );
    """)

    tables = ("users", "orders", "products")
    counts = [
        conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] for table in tables
    ]

    if all(count == 0 for count in counts):
        conn.executemany(
            "INSERT INTO users (name, email, signup_date) VALUES (?, ?, ?)",
            [
                ("Ion Popescu", "ion@example.com", "2023-01-15"),
                ("Maria Ionescu", "maria@example.com", "2023-02-20"),
                ("Andrei Radu", "andrei@test.com", "2023-03-10"),
            ],
        )

        conn.executemany(
            "INSERT INTO products (product_name, price, stock) VALUES (?, ?, ?)",
            [
                ("Laptop Gaming", 1200.50, 10),
                ("Mouse Wireless", 25.00, 50),
                ("Monitor 4K", 300.00, 15),
                ("Tastatura Mecanica", 80.00, 30),
            ],
        )

        conn.executemany(
            "INSERT INTO orders (user_id, order_date, total_amount) VALUES (?, ?, ?)",
            [
                (1, "2023-04-01", 1225.50),
                (1, "2023-05-01", 80.00),
                (2, "2023-04-15", 300.00),
            ],
        )

        print("Baza de date a fost populată cu date de test.")

    else:
        print("Baza de date conține deja date; nu au fost suprascrise.")

    conn.commit()

finally:
    conn.close()

print(f"Baza de date este disponibilă la: {DB_PATH}")
