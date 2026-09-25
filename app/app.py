import os
import socket
import time

import psycopg
from flask import Flask, request

app = Flask(__name__)

SCHEMA = """
CREATE TABLE IF NOT EXISTS notes (
    id         SERIAL PRIMARY KEY,
    body       TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
)
"""


def get_conn():
    """Open a new connection. All settings come from environment variables."""
    return psycopg.connect(
        host=os.environ.get("DB_HOST", "localhost"),
        port=os.environ.get("DB_PORT", "5432"),
        dbname=os.environ.get("DB_NAME", "notes"),
        user=os.environ.get("DB_USER", "postgres"),
        password=os.environ["DB_PASSWORD"],  # required: fail fast if missing
        connect_timeout=3,
    )


def init_db(retries=15, delay=2):
    """Create the table, retrying while the database starts up.

    We retry on any psycopg error because (a) the database may not be
    accepting connections yet, and (b) if several replicas start at the same
    moment, one of them may briefly collide with another's CREATE TABLE.
    """
    for attempt in range(1, retries + 1):
        try:
            with get_conn() as conn:
                conn.execute(SCHEMA)
            print("Database ready", flush=True)
            return
        except psycopg.Error as exc:
            print(f"DB not ready (attempt {attempt}/{retries}): {exc}", flush=True)
            time.sleep(delay)
    raise RuntimeError("Could not initialize the database")


init_db()


@app.get("/")
def index():
    return {
        "service": "notes-app",
        "message": "Hello it's me again!",
        "served_by": socket.gethostname(),
    }


@app.get("/healthz")
def healthz():
    """Liveness: is this process running? Does NOT touch the database."""
    return {"status": "ok"}


@app.get("/readyz")
def readyz():
    """Readiness: can this process actually serve requests (is the DB reachable)?"""
    try:
        with get_conn() as conn:
            conn.execute("SELECT 1")
    except psycopg.Error:
        return {"status": "database unavailable"}, 503
    return {"status": "ready"}


@app.get("/notes")
def list_notes():
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, body, created_at FROM notes ORDER BY id"
        ).fetchall()
    return [
        {"id": r[0], "body": r[1], "created_at": r[2].isoformat()} for r in rows
    ]


@app.post("/notes")
def add_note():
    data = request.get_json(silent=True) or {}
    body = str(data.get("body", "")).strip()
    if not body:
        return {"error": "body is required"}, 400
    with get_conn() as conn:
        row = conn.execute(
            "INSERT INTO notes (body) VALUES (%s) RETURNING id", (body,)
        ).fetchone()
    return {"id": row[0], "body": body}, 201