import sqlite3
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "webrunner.db")

def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_conn()
    # Migration: add has_requirements if missing (old projects default to True)
    try:
        conn.execute("ALTER TABLE projects ADD COLUMN has_requirements INTEGER")
        conn.execute("UPDATE projects SET has_requirements = 1 WHERE has_requirements IS NULL")
    except:
        pass

    conn.executescript("""
        CREATE TABLE IF NOT EXISTS accounts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            provider TEXT NOT NULL CHECK(provider IN ('render', 'pythonanywhere')),
            api_key TEXT NOT NULL,
            github_token TEXT DEFAULT '',
            email TEXT,
            is_active INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );

        CREATE TABLE IF NOT EXISTS projects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            folder_path TEXT NOT NULL,
            framework TEXT,
            frontend_framework TEXT,
            entry_point TEXT,
            account_id INTEGER REFERENCES accounts(id),
            deploy_url TEXT,
            has_requirements INTEGER DEFAULT 0,
            render_service_id TEXT,
            github_repo TEXT,
            status TEXT DEFAULT 'pending' CHECK(status IN ('pending','deploying','live','error','removed')),
            keep_alive_setup INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    conn.commit()
    conn.close()

def get_all_accounts():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM accounts WHERE is_active = 1 ORDER BY created_at DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]

def add_account(name, provider, api_key, email="", github_token=""):
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO accounts (name, provider, api_key, email, github_token) VALUES (?, ?, ?, ?, ?)",
        (name, provider, api_key, email, github_token)
    )
    conn.commit()
    id_ = cur.lastrowid
    conn.close()
    return id_

def update_account(account_id, **kwargs):
    allowed = ["github_token", "api_key", "name"]
    fields = {k: v for k, v in kwargs.items() if k in allowed}
    if not fields:
        return
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [account_id]
    conn = get_conn()
    conn.execute(f"UPDATE accounts SET {set_clause} WHERE id = ?", values)
    conn.commit()
    conn.close()

def delete_account(account_id):
    conn = get_conn()
    conn.execute("UPDATE accounts SET is_active = 0 WHERE id = ?", (account_id,))
    conn.commit()
    conn.close()

def get_all_projects():
    conn = get_conn()
    rows = conn.execute("""
        SELECT p.*, a.name as account_name, a.provider as account_provider,
               a.github_token
        FROM projects p
        LEFT JOIN accounts a ON p.account_id = a.id
        WHERE p.status != 'removed'
        ORDER BY p.updated_at DESC
    """).fetchall()
    conn.close()
    return [dict(r) for r in rows]

def get_project(project_id):
    conn = get_conn()
    row = conn.execute("""
        SELECT p.*, a.name as account_name, a.provider as account_provider,
               a.github_token, a.api_key
        FROM projects p
        LEFT JOIN accounts a ON p.account_id = a.id
        WHERE p.id = ?
    """, (project_id,)).fetchone()
    conn.close()
    return dict(row) if row else None

def add_project(name, folder_path, framework, frontend_framework, entry_point, account_id, has_requirements=0):
    conn = get_conn()
    cur = conn.execute(
        "INSERT INTO projects (name, folder_path, framework, frontend_framework, entry_point, account_id, has_requirements) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (name, folder_path, framework, frontend_framework, entry_point, account_id, int(has_requirements))
    )
    conn.commit()
    id_ = cur.lastrowid
    conn.close()
    return id_

def update_project(project_id, **kwargs):
    allowed = ["status", "deploy_url", "has_requirements", "render_service_id", "github_repo", "keep_alive_setup", "updated_at"]
    fields = {k: v for k, v in kwargs.items() if k in allowed}
    if not fields:
        return
    fields["updated_at"] = datetime.utcnow().isoformat()
    set_clause = ", ".join(f"{k} = ?" for k in fields)
    values = list(fields.values()) + [project_id]
    conn = get_conn()
    conn.execute(f"UPDATE projects SET {set_clause} WHERE id = ?", values)
    conn.commit()
    conn.close()

def delete_project(project_id):
    conn = get_conn()
    conn.execute("UPDATE projects SET status = 'removed', updated_at = ? WHERE id = ?",
                 (datetime.utcnow().isoformat(), project_id))
    conn.commit()
    conn.close()
