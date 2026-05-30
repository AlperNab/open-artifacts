from __future__ import annotations
import os, sqlite3, json
from pathlib import Path
from datetime import datetime
from typing import Any
DB_PATH = Path(os.getenv('AI_SUITE_DB', './data/ai_suite.sqlite3'))
DB_PATH.parent.mkdir(parents=True, exist_ok=True)
def connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn
def init_db():
    with connect() as db:
        db.executescript('''
        CREATE TABLE IF NOT EXISTS provider_settings (name TEXT PRIMARY KEY, provider_type TEXT NOT NULL, model TEXT NOT NULL, encrypted_api_key TEXT, base_url TEXT, endpoint TEXT, deployment TEXT, enabled INTEGER NOT NULL DEFAULT 1, is_local INTEGER NOT NULL DEFAULT 0, default_temperature REAL NOT NULL DEFAULT 0.2, max_tokens INTEGER NOT NULL DEFAULT 4000, updated_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS jobs (id INTEGER PRIMARY KEY AUTOINCREMENT, project_slug TEXT NOT NULL, provider_name TEXT NOT NULL, model TEXT, status TEXT NOT NULL, inputs_json TEXT NOT NULL, customization_json TEXT NOT NULL, uploaded_file_ids_json TEXT NOT NULL, output TEXT, error TEXT, usage_json TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS uploaded_files (id INTEGER PRIMARY KEY AUTOINCREMENT, original_name TEXT NOT NULL, stored_path TEXT NOT NULL, mime_type TEXT, size_bytes INTEGER NOT NULL, extracted_text TEXT, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS workspace_settings (key TEXT PRIMARY KEY, value_json TEXT NOT NULL, updated_at TEXT NOT NULL);
        ''')
def now(): return datetime.utcnow().isoformat(timespec='seconds') + 'Z'
def upsert_provider(row: dict[str, Any]):
    with connect() as db:
        db.execute('''INSERT INTO provider_settings (name, provider_type, model, encrypted_api_key, base_url, endpoint, deployment, enabled, is_local, default_temperature, max_tokens, updated_at) VALUES (:name,:provider_type,:model,:encrypted_api_key,:base_url,:endpoint,:deployment,:enabled,:is_local,:default_temperature,:max_tokens,:updated_at) ON CONFLICT(name) DO UPDATE SET provider_type=excluded.provider_type, model=excluded.model, encrypted_api_key=excluded.encrypted_api_key, base_url=excluded.base_url, endpoint=excluded.endpoint, deployment=excluded.deployment, enabled=excluded.enabled, is_local=excluded.is_local, default_temperature=excluded.default_temperature, max_tokens=excluded.max_tokens, updated_at=excluded.updated_at''', row)
def list_providers():
    with connect() as db: return [dict(r) for r in db.execute('SELECT * FROM provider_settings ORDER BY is_local DESC, name ASC')]
def get_provider(name: str):
    with connect() as db:
        r=db.execute('SELECT * FROM provider_settings WHERE name=?',(name,)).fetchone(); return dict(r) if r else None
def create_job(project_slug, provider_name, model, inputs, customization, file_ids):
    t=now()
    with connect() as db:
        cur=db.execute('INSERT INTO jobs(project_slug,provider_name,model,status,inputs_json,customization_json,uploaded_file_ids_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)',(project_slug,provider_name,model,'running',json.dumps(inputs,ensure_ascii=False),json.dumps(customization,ensure_ascii=False),json.dumps(file_ids),t,t)); return cur.lastrowid
def finish_job(job_id, status, output=None, error=None, usage=None):
    with connect() as db: db.execute('UPDATE jobs SET status=?, output=?, error=?, usage_json=?, updated_at=? WHERE id=?',(status,output,error,json.dumps(usage or {},ensure_ascii=False),now(),job_id))
def list_jobs(limit=100):
    with connect() as db: return [dict(r) for r in db.execute('SELECT * FROM jobs ORDER BY id DESC LIMIT ?',(limit,))]
def get_job(job_id:int):
    with connect() as db:
        r=db.execute('SELECT * FROM jobs WHERE id=?',(job_id,)).fetchone(); return dict(r) if r else None
def save_uploaded_file(original_name, stored_path, mime_type, size_bytes, extracted_text):
    t=now()
    with connect() as db:
        cur=db.execute('INSERT INTO uploaded_files(original_name,stored_path,mime_type,size_bytes,extracted_text,created_at) VALUES(?,?,?,?,?,?)',(original_name,stored_path,mime_type,size_bytes,extracted_text,t)); return cur.lastrowid
def get_uploaded_files(ids:list[int]):
    if not ids: return []
    q=','.join('?' for _ in ids)
    with connect() as db: return [dict(r) for r in db.execute(f'SELECT * FROM uploaded_files WHERE id IN ({q})', ids)]
