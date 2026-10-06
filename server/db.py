import sqlite3
import uuid
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Dict, Any, Optional

from server.config import DB_PATH, AGENT_OFFLINE_THRESHOLD_SECONDS, DEFAULT_CHECKIN_INTERVAL


def get_db_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=10.0)
    conn.row_factory = sqlite3.Row
    # write ahead logging for web server
    conn.execute("PRAGMA journal_mode = WAL;")
    conn.execute("PRAGMA busy_timeout = 5000;")
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def init_db():
    Path(DB_PATH).parent.mkdir(parents=True, exist_ok=True)
    with get_db_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS agents (
                agent_id TEXT PRIMARY KEY,
                hostname TEXT,
                ip_address TEXT,
                os_name TEXT,
                os_version TEXT,
                arch TEXT,
                username TEXT,
                first_seen TEXT,
                last_seen TEXT,
                status TEXT DEFAULT 'active',
                metadata TEXT DEFAULT '{}'
            );
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS tasks (
                id TEXT PRIMARY KEY,
                agent_id TEXT NOT NULL,
                command TEXT NOT NULL,
                status TEXT DEFAULT 'pending',
                created_at TEXT NOT NULL,
                dispatched_at TEXT,
                completed_at TEXT,
                exit_code INTEGER,
                stdout TEXT,
                stderr TEXT,
                error_message TEXT,
                FOREIGN KEY(agent_id) REFERENCES agents(agent_id) ON DELETE CASCADE
            );
        """)
        conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_agent_status ON tasks(agent_id, status);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_created_at ON tasks(created_at);")
        conn.commit()


def _utc_now_str() -> str:
    return datetime.now(timezone.utc).isoformat()


def upsert_agent(agent_data: Dict[str, Any]) -> Dict[str, Any]:
    now = _utc_now_str()
    agent_id = agent_data["agent_id"]
    hostname = agent_data.get("hostname", "unknown")
    ip_address = agent_data.get("ip_address", "127.0.0.1")
    os_name = agent_data.get("os_name", "unknown")
    os_version = agent_data.get("os_version", "")
    arch = agent_data.get("arch", "")
    username = agent_data.get("username", "")
    metadata = json.dumps(agent_data.get("metadata", {}))

    with get_db_connection() as conn:
        conn.execute("""
            INSERT INTO agents (
                agent_id, hostname, ip_address, os_name, os_version, arch, username, first_seen, last_seen, status, metadata
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'active', ?)
            ON CONFLICT(agent_id) DO UPDATE SET
                hostname = excluded.hostname,
                ip_address = excluded.ip_address,
                os_name = excluded.os_name,
                os_version = excluded.os_version,
                arch = excluded.arch,
                username = excluded.username,
                last_seen = excluded.last_seen,
                status = 'active',
                metadata = excluded.metadata;
        """, (agent_id, hostname, ip_address, os_name, os_version, arch, username, now, now, metadata))
        conn.commit()

    return get_agent(agent_id)


def is_agent_online(last_seen_str: Optional[str]) -> bool:
    if not last_seen_str:
        return False
    try:
        last_seen = datetime.fromisoformat(last_seen_str)
        delta = datetime.now(timezone.utc) - last_seen
        return delta.total_seconds() <= AGENT_OFFLINE_THRESHOLD_SECONDS
    except Exception:
        return False


def get_agents() -> List[Dict[str, Any]]:
    with get_db_connection() as conn:
        cursor = conn.execute("SELECT * FROM agents ORDER BY last_seen DESC;")
        rows = cursor.fetchall()
        result = []
        for row in rows:
            d = dict(row)
            d["is_online"] = is_agent_online(d["last_seen"])
            d["metadata"] = json.loads(d.get("metadata") or "{}")
            result.append(d)
        return result


def get_agent(agent_id: str) -> Optional[Dict[str, Any]]:
    with get_db_connection() as conn:
        cursor = conn.execute("SELECT * FROM agents WHERE agent_id = ?;", (agent_id,))
        row = cursor.fetchone()
        if not row:
            return None
        d = dict(row)
        d["is_online"] = is_agent_online(d["last_seen"])
        d["metadata"] = json.loads(d.get("metadata") or "{}")
        return d


def queue_task(agent_id: str, command: str) -> List[Dict[str, Any]]:
    """Queue a task for a single agent, or for all agents if agent_id == 'all'."""
    now = _utc_now_str()
    created_tasks = []

    with get_db_connection() as conn:
        if agent_id.lower() == "all":
            cursor = conn.execute("SELECT agent_id FROM agents;")
            target_agents = [row["agent_id"] for row in cursor.fetchall()]
        else:
            target_agents = [agent_id]

        for aid in target_agents:
            task_id = str(uuid.uuid4())
            conn.execute("""
                INSERT INTO tasks (id, agent_id, command, status, created_at)
                VALUES (?, ?, ?, 'pending', ?);
            """, (task_id, aid, command, now))
            created_tasks.append({
                "id": task_id,
                "agent_id": aid,
                "command": command,
                "status": "pending",
                "created_at": now
            })
        conn.commit()

    return created_tasks


def fetch_and_dispatch_pending_tasks(agent_id: str, max_tasks: int = 10) -> List[Dict[str, Any]]:
    """
    Called when an agent checks in.
    Atomically retrieves pending tasks and marks them as 'dispatched'.
    """
    now = _utc_now_str()
    dispatched_tasks = []

    with get_db_connection() as conn:
        cursor = conn.execute("""
            SELECT id, agent_id, command, status, created_at
            FROM tasks
            WHERE agent_id = ? AND status = 'pending'
            ORDER BY created_at ASC
            LIMIT ?;
        """, (agent_id, max_tasks))
        rows = cursor.fetchall()

        if rows:
            task_ids = [row["id"] for row in rows]
            placeholders = ",".join("?" * len(task_ids))
            conn.execute(f"""
                UPDATE tasks
                SET status = 'dispatched', dispatched_at = ?
                WHERE id IN ({placeholders});
            """, [now] + task_ids)
            conn.commit()

            for row in rows:
                t = dict(row)
                t["status"] = "dispatched"
                t["dispatched_at"] = now
                dispatched_tasks.append(t)

    return dispatched_tasks


def record_task_result(
    task_id: str,
    agent_id: str,
    status: str,
    exit_code: Optional[int] = None,
    stdout: Optional[str] = None,
    stderr: Optional[str] = None,
    error_message: Optional[str] = None
) -> Optional[Dict[str, Any]]:
    now = _utc_now_str()

    
    final_status = "completed" if status in ("completed", "success") else "failed"

    with get_db_connection() as conn:
        cursor = conn.execute("""
            UPDATE tasks
            SET status = ?,
                exit_code = ?,
                stdout = ?,
                stderr = ?,
                error_message = ?,
                completed_at = ?
            WHERE id = ? AND agent_id = ?;
        """, (final_status, exit_code, stdout, stderr, error_message, now, task_id, agent_id))
        conn.commit()

        if cursor.rowcount == 0:
            return None

    return get_task(task_id)


def get_tasks(
    agent_id: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 100,
    offset: int = 0
) -> List[Dict[str, Any]]:
    query = "SELECT * FROM tasks WHERE 1=1"
    params = []

    if agent_id:
        query += " AND agent_id = ?"
        params.append(agent_id)
    if status:
        query += " AND status = ?"
        params.append(status)

    query += " ORDER BY created_at DESC LIMIT ? OFFSET ?;"
    params.extend([limit, offset])

    with get_db_connection() as conn:
        cursor = conn.execute(query, params)
        return [dict(row) for row in cursor.fetchall()]


def get_task(task_id: str) -> Optional[Dict[str, Any]]:
    with get_db_connection() as conn:
        cursor = conn.execute("SELECT * FROM tasks WHERE id = ?;", (task_id,))
        row = cursor.fetchone()
        return dict(row) if row else None


def cancel_task(task_id: str) -> bool:
    with get_db_connection() as conn:
        cursor = conn.execute("""
            UPDATE tasks
            SET status = 'cancelled'
            WHERE id = ? AND status = 'pending';
        """, (task_id,))
        conn.commit()
        return cursor.rowcount > 0


def delete_agent(agent_id: str) -> bool:
    with get_db_connection() as conn:
        cursor = conn.execute("DELETE FROM agents WHERE agent_id = ?;", (agent_id,))
        conn.commit()
        return cursor.rowcount > 0


def get_system_stats() -> Dict[str, Any]:
    with get_db_connection() as conn:
        agents = get_agents()
        total_agents = len(agents)
        online_agents = sum(1 for a in agents if a["is_online"])

        c = conn.cursor()
        c.execute("SELECT status, COUNT(*) FROM tasks GROUP BY status;")
        task_counts = {row[0]: row[1] for row in c.fetchall()}

        return {
            "total_agents": total_agents,
            "online_agents": online_agents,
            "offline_agents": total_agents - online_agents,
            "tasks_pending": task_counts.get("pending", 0),
            "tasks_dispatched": task_counts.get("dispatched", 0),
            "tasks_completed": task_counts.get("completed", 0),
            "tasks_failed": task_counts.get("failed", 0),
            "tasks_cancelled": task_counts.get("cancelled", 0),
            "total_tasks": sum(task_counts.values())
        }
