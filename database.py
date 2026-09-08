import sqlite3
from datetime import datetime, timedelta
from config import PANEL_DB_PATH


def get_db():
    conn = sqlite3.connect(PANEL_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_admin_auth_table(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS admin_auth (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        email TEXT, password_hash TEXT
    )""")
    conn.execute("INSERT OR IGNORE INTO admin_auth (id, email, password_hash) VALUES (1, NULL, NULL)")


def init_db():
    conn = get_db()

    conn.execute("""CREATE TABLE IF NOT EXISTS nodes (
        id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT UNIQUE, ip TEXT,
        ssh_user TEXT DEFAULT 'root', ssh_port INTEGER DEFAULT 22,
        ram_total TEXT, cpu_total TEXT, disk_total TEXT, created_at TEXT
    )""")

    conn.execute("""CREATE TABLE IF NOT EXISTS vps_customers (
        id INTEGER PRIMARY KEY AUTOINCREMENT, node_id INTEGER, discord_id TEXT,
        container_name TEXT UNIQUE, os_image TEXT, ssh_port INTEGER,
        ssh_username TEXT DEFAULT 'root', ssh_password TEXT,
        ram_limit TEXT, cpu_limit TEXT, disk_limit TEXT, plan TEXT, price TEXT,
        renewal_date TEXT, status TEXT DEFAULT 'active', rating INTEGER,
        cancel_reason TEXT, created_at TEXT
    )""")

    conn.execute("""CREATE TABLE IF NOT EXISTS delivery_queue (
        id INTEGER PRIMARY KEY AUTOINCREMENT, vps_id INTEGER,
        status TEXT DEFAULT 'pending', created_at TEXT, sent_at TEXT
    )""")

    conn.execute("""CREATE TABLE IF NOT EXISTS bot_config (
        id INTEGER PRIMARY KEY CHECK (id = 1), token TEXT, last_heartbeat TEXT
    )""")
    conn.execute("INSERT OR IGNORE INTO bot_config (id, token) VALUES (1, NULL)")

    conn.execute("""CREATE TABLE IF NOT EXISTS api_keys (
        id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, key_value TEXT UNIQUE,
        created_at TEXT, last_used TEXT
    )""")

    conn.execute("""CREATE TABLE IF NOT EXISTS branding (
        id INTEGER PRIMARY KEY CHECK (id = 1),
        logo_url TEXT, background_theme TEXT DEFAULT 'grid'
    )""")
    conn.execute("INSERT OR IGNORE INTO branding (id, logo_url, background_theme) VALUES (1, NULL, 'grid')")

    conn.execute("""CREATE TABLE IF NOT EXISTS violation_queue (
        id INTEGER PRIMARY KEY AUTOINCREMENT, vps_id INTEGER, reason TEXT,
        status TEXT DEFAULT 'pending', created_at TEXT, sent_at TEXT
    )""")

    init_admin_auth_table(conn)

    conn.commit()
    conn.close()


def get_branding():
    conn = get_db()
    row = conn.execute("SELECT logo_url, background_theme FROM branding WHERE id=1").fetchone()
    conn.close()
    return dict(row) if row else {"logo_url": None, "background_theme": "grid"}


def save_branding(logo_url=None, background_theme=None):
    conn = get_db()
    if logo_url is not None:
        conn.execute("UPDATE branding SET logo_url=? WHERE id=1", (logo_url,))
    if background_theme is not None:
        conn.execute("UPDATE branding SET background_theme=? WHERE id=1", (background_theme,))
    conn.commit()
    conn.close()


def set_admin_credentials(email, password_hash):
    conn = get_db()
    conn.execute("UPDATE admin_auth SET email=?, password_hash=? WHERE id=1", (email, password_hash))
    conn.commit()
    conn.close()


def get_admin_credentials():
    conn = get_db()
    row = conn.execute("SELECT email, password_hash FROM admin_auth WHERE id=1").fetchone()
    conn.close()
    return dict(row) if row else {"email": None, "password_hash": None}


def add_node(name, ip, ssh_user, ssh_port, ram_total, cpu_total, disk_total, ssh_password=None):
    conn = get_db()
    conn.execute(
        "INSERT INTO nodes (name, ip, ssh_user, ssh_port, ram_total, cpu_total, disk_total, ssh_password, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
        (name, ip, ssh_user, ssh_port, ram_total, cpu_total, disk_total, ssh_password, datetime.utcnow().isoformat())
    )
    conn.commit()
    conn.close()

def list_nodes():
    conn = get_db()
    rows = conn.execute("SELECT * FROM nodes ORDER BY id").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_node(node_id):
    conn = get_db()
    row = conn.execute("SELECT * FROM nodes WHERE id=?", (node_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def delete_node(node_id):
    conn = get_db()
    conn.execute("DELETE FROM nodes WHERE id=?", (node_id,))
    conn.commit()
    conn.close()


def next_free_port(node_id, start=20000, end=21000):
    conn = get_db()
    used = {r["ssh_port"] for r in conn.execute("SELECT ssh_port FROM vps_customers WHERE node_id=?", (node_id,)).fetchall()}
    conn.close()
    for p in range(start, end):
        if p not in used:
            return p
    raise RuntimeError("No free ports left on this node")


def add_vps(node_id, discord_id, container_name, os_image, ssh_port, ssh_password,
            ram_limit, cpu_limit, disk_limit, plan, price, time_days):
    renewal_date = (datetime.utcnow() + timedelta(days=int(time_days))).date().isoformat()
    conn = get_db()
    conn.execute("""INSERT INTO vps_customers
        (node_id, discord_id, container_name, os_image, ssh_port, ssh_password, ram_limit, cpu_limit, disk_limit, plan, price, renewal_date, created_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (node_id, discord_id, container_name, os_image, ssh_port, ssh_password, ram_limit, cpu_limit, disk_limit, plan, price, renewal_date, datetime.utcnow().isoformat()))
    conn.commit()
    vps_id = conn.execute("SELECT id FROM vps_customers WHERE container_name=?", (container_name,)).fetchone()["id"]
    conn.close()
    return vps_id, renewal_date


def list_vps():
    conn = get_db()
    rows = conn.execute("""
        SELECT v.*, n.name as node_name, n.ip as node_ip
        FROM vps_customers v LEFT JOIN nodes n ON v.node_id = n.id ORDER BY v.id DESC
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_vps(vps_id):
    conn = get_db()
    row = conn.execute("""
        SELECT v.*, n.name as node_name, n.ip as node_ip, n.ssh_user as node_ssh_user, n.ssh_port as node_ssh_port
        FROM vps_customers v LEFT JOIN nodes n ON v.node_id = n.id WHERE v.id=?
    """, (vps_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def get_vps_by_container(container_name):
    conn = get_db()
    row = conn.execute("""
        SELECT v.*, n.ip as node_ip, n.ssh_user as node_ssh_user, n.ssh_port as node_ssh_port
        FROM vps_customers v LEFT JOIN nodes n ON v.node_id = n.id WHERE v.container_name=?
    """, (container_name,)).fetchone()
    conn.close()
    return dict(row) if row else None


def update_vps(vps_id, **fields):
    if not fields:
        return
    conn = get_db()
    set_clause = ", ".join(f"{k}=?" for k in fields)
    conn.execute(f"UPDATE vps_customers SET {set_clause} WHERE id=?", (*fields.values(), vps_id))
    conn.commit()
    conn.close()


def delete_vps(vps_id):
    conn = get_db()
    conn.execute("DELETE FROM vps_customers WHERE id=?", (vps_id,))
    conn.commit()
    conn.close()


def get_due_renewals(today_str):
    conn = get_db()
    rows = conn.execute("SELECT * FROM vps_customers WHERE renewal_date=? AND status='active'", (today_str,)).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def set_vps_status(vps_id, status, rating=None, reason=None):
    conn = get_db()
    conn.execute("UPDATE vps_customers SET status=?, rating=?, cancel_reason=? WHERE id=?", (status, rating, reason, vps_id))
    conn.commit()
    conn.close()


def queue_delivery(vps_id):
    conn = get_db()
    conn.execute("INSERT INTO delivery_queue (vps_id, created_at) VALUES (?,?)", (vps_id, datetime.utcnow().isoformat()))
    conn.commit()
    conn.close()


def get_pending_deliveries():
    conn = get_db()
    rows = conn.execute("SELECT * FROM delivery_queue WHERE status='pending'").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def mark_delivered(delivery_id, status="sent"):
    conn = get_db()
    conn.execute("UPDATE delivery_queue SET status=?, sent_at=? WHERE id=?", (status, datetime.utcnow().isoformat(), delivery_id))
    conn.commit()
    conn.close()


def get_delivery_log():
    conn = get_db()
    rows = conn.execute("""
        SELECT d.id, d.status, d.created_at, d.sent_at, v.container_name, v.discord_id
        FROM delivery_queue d JOIN vps_customers v ON d.vps_id = v.id ORDER BY d.id DESC LIMIT 30
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def save_bot_token(token):
    conn = get_db()
    conn.execute("UPDATE bot_config SET token=? WHERE id=1", (token,))
    conn.commit()
    conn.close()


def get_bot_token():
    conn = get_db()
    row = conn.execute("SELECT token FROM bot_config WHERE id=1").fetchone()
    conn.close()
    return row["token"] if row else None


def get_bot_heartbeat():
    conn = get_db()
    row = conn.execute("SELECT last_heartbeat FROM bot_config WHERE id=1").fetchone()
    conn.close()
    return row["last_heartbeat"] if row else None


def update_heartbeat():
    conn = get_db()
    conn.execute("UPDATE bot_config SET last_heartbeat=? WHERE id=1", (datetime.utcnow().isoformat(),))
    conn.commit()
    conn.close()


def create_api_key(name):
    import secrets
    key_value = "legacy_" + secrets.token_urlsafe(32)
    conn = get_db()
    conn.execute("INSERT INTO api_keys (name, key_value, created_at) VALUES (?,?,?)",
                 (name, key_value, datetime.utcnow().isoformat()))
    conn.commit()
    conn.close()
    return key_value


def list_api_keys():
    conn = get_db()
    rows = conn.execute("SELECT id, name, key_value, created_at, last_used FROM api_keys ORDER BY id DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def validate_api_key(key_value):
    conn = get_db()
    row = conn.execute("SELECT id FROM api_keys WHERE key_value=?", (key_value,)).fetchone()
    if row:
        conn.execute("UPDATE api_keys SET last_used=? WHERE id=?", (datetime.utcnow().isoformat(), row["id"]))
        conn.commit()
    conn.close()
    return row is not None


def revoke_api_key(key_id):
    conn = get_db()
    conn.execute("DELETE FROM api_keys WHERE id=?", (key_id,))
    conn.commit()
    conn.close()


def queue_violation(vps_id, reason):
    conn = get_db()
    conn.execute("INSERT INTO violation_queue (vps_id, reason, created_at) VALUES (?,?,?)",
                 (vps_id, reason, datetime.utcnow().isoformat()))
    conn.commit()
    conn.close()


def get_pending_violations():
    conn = get_db()
    rows = conn.execute("SELECT * FROM violation_queue WHERE status='pending'").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def mark_violation_sent(violation_id):
    conn = get_db()
    conn.execute("UPDATE violation_queue SET status='sent', sent_at=? WHERE id=?", (datetime.utcnow().isoformat(), violation_id))
    conn.commit()
    conn.close()
