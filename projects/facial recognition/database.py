import sqlite3

DB_PATH = "users.db"


def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            first_name TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            face_image_path TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_login TIMESTAMP
        )
    """)
    # migrate existing databases that don't have the column yet
    try:
        c.execute("ALTER TABLE users ADD COLUMN last_login TIMESTAMP")
    except sqlite3.OperationalError:
        pass  # column already exists
    conn.commit()
    conn.close()


def add_user(first_name, password_hash, face_image_path):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    try:
        c.execute(
            "INSERT INTO users (first_name, password_hash, face_image_path) VALUES (?, ?, ?)",
            (first_name.lower(), password_hash, face_image_path),
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()


def get_user(first_name):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "SELECT id, first_name, password_hash, face_image_path, created_at FROM users WHERE first_name = ?",
        (first_name.lower(),),
    )
    user = c.fetchone()
    conn.close()
    return user


def update_last_login(first_name):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "UPDATE users SET last_login = CURRENT_TIMESTAMP WHERE first_name = ?",
        (first_name.lower(),),
    )
    conn.commit()
    conn.close()


def get_all_users():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, first_name, created_at, last_login FROM users ORDER BY created_at DESC")
    users = c.fetchall()
    conn.close()
    return users
