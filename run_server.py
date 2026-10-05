import uvicorn
from server.config import SERVER_HOST, SERVER_PORT

if __name__ == "__main__":
    print(f"[*] Starting C2 Server on http://{SERVER_HOST}:{SERVER_PORT}")
    print(f"[*] Web UI Dashboard: http://localhost:{SERVER_PORT}/")
    print(f"[*] API Docs:         http://localhost:{SERVER_PORT}/docs")
    uvicorn.run("server.app:app", host=SERVER_HOST, port=SERVER_PORT, reload=False)
