import os
import json
import threading
import webbrowser
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel

from . import db
from . import scanner
from . import render_deployer
from . import keep_alive

app = FastAPI(title="WebRunner")

@app.on_event("startup")
def on_startup():
    db.init_db()

root_dir = os.path.dirname(os.path.dirname(__file__))
static_dir = os.path.join(root_dir, "frontend")
static_assets = os.path.join(root_dir, "static")

app.mount("/frontend", StaticFiles(directory=static_dir), name="frontend")
app.mount("/static", StaticFiles(directory=static_assets), name="static")

class AddAccountRequest(BaseModel):
    name: str
    provider: str
    api_key: str
    email: str = ""

class AddProjectRequest(BaseModel):
    name: str
    folder_path: str
    account_id: int

class ScanRequest(BaseModel):
    folder_path: str

class DeployRequest(BaseModel):
    project_id: int

class DeleteProjectRequest(BaseModel):
    project_id: int

class DeleteAccountRequest(BaseModel):
    account_id: int

# --- API Routes ---

@app.get("/api/health")
def health():
    return {"status": "ok"}

@app.get("/api/accounts")
def list_accounts():
    return db.get_all_accounts()

@app.post("/api/accounts")
def create_account(req: AddAccountRequest):
    valid = render_deployer.validate_api_key(req.api_key)
    if not valid:
        raise HTTPException(status_code=400, detail="Invalid Render API key")
    id_ = db.add_account(req.name, req.provider, req.api_key, req.email)
    return {"id": id_, "message": "Account added"}

@app.delete("/api/accounts")
def remove_account(req: DeleteAccountRequest):
    db.delete_account(req.account_id)
    return {"message": "Account removed"}

@app.post("/api/scan")
def scan_project(req: ScanRequest):
    result = scanner.scan_project(req.folder_path)
    if "error" in result:
        raise HTTPException(status_code=400, detail=result["error"])
    return result

@app.get("/api/projects")
def list_projects():
    return db.get_all_projects()

@app.get("/api/projects/{project_id}")
def get_project(project_id: int):
    project = db.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project

@app.post("/api/projects")
def create_project(req: AddProjectRequest):
    scan_result = scanner.scan_project(req.folder_path)
    if "error" in scan_result:
        raise HTTPException(status_code=400, detail=scan_result["error"])

    id_ = db.add_project(
        name=req.name,
        folder_path=req.folder_path,
        framework=scan_result.get("framework"),
        frontend_framework=scan_result.get("frontend_framework"),
        entry_point=scan_result.get("entry_point"),
        account_id=req.account_id,
    )
    return {
        "id": id_,
        "message": "Project created",
        "detected": scan_result,
    }

@app.post("/api/projects/deploy")
def deploy_project(req: DeployRequest):
    project = db.get_project(req.project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    account = next((a for a in db.get_all_accounts() if a["id"] == project["account_id"]), None)
    if not account:
        raise HTTPException(status_code=400, detail="No account assigned to this project")

    db.update_project(project["id"], status="deploying")

    def do_deploy():
        try:
            render_deployer.prepare_project_files(
                project_path=project["folder_path"],
                project_name=project["name"],
                framework=project["framework"],
                entry_point=project["entry_point"],
                has_requirements=True,
            )

            service_id, service_url, temp_dir = render_deployer.create_service(
                api_key=account["api_key"],
                project_name=project["name"],
                project_path=project["folder_path"],
            )

            db.update_project(
                project["id"],
                status="live",
                deploy_url=service_url,
                render_service_id=service_id,
            )

            try:
                keep_alive.setup_github_actions(
                    project_path=project["folder_path"],
                    project_name=project["name"],
                    deploy_url=service_url,
                )
                db.update_project(project["id"], keep_alive_setup=1)
            except:
                pass

        except Exception as e:
            db.update_project(project["id"], status="error")

    thread = threading.Thread(target=do_deploy, daemon=True)
    thread.start()

    return {"message": "Deployment started", "project_id": project["id"]}

@app.post("/api/projects/delete")
def remove_project(req: DeleteProjectRequest):
    project = db.get_project(req.project_id)
    if project and project.get("render_service_id"):
        account = next((a for a in db.get_all_accounts() if a["id"] == project["account_id"]), None)
        if account:
            try:
                render_deployer.delete_service(account["api_key"], project["render_service_id"])
            except:
                pass
    db.delete_project(req.project_id)
    return {"message": "Project removed"}

@app.get("/api/projects/{project_id}/status")
def check_status(project_id: int):
    project = db.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    if project.get("render_service_id") and project.get("account_id"):
        account = next((a for a in db.get_all_accounts() if a["id"] == project["account_id"]), None)
        if account:
            try:
                status = render_deployer.get_service_status(account["api_key"], project["render_service_id"])
                return status
            except:
                pass
    return {"status": project.get("status", "unknown"), "url": project.get("deploy_url", "")}

# --- Serve frontend ---

@app.get("/favicon.ico")
def favicon():
    return "", 204

@app.get("/")
def serve_index():
    return FileResponse(os.path.join(static_dir, "index.html"))

@app.get("/add-project")
def serve_add_project():
    return FileResponse(os.path.join(static_dir, "add-project.html"))

@app.get("/accounts")
def serve_accounts():
    return FileResponse(os.path.join(static_dir, "accounts.html"))

def open_browser():
    webbrowser.open("http://localhost:8777")

def start_server():
    import uvicorn
    db.init_db()
    print("=" * 50)
    print("  WebRunner - Desktop Deployer")
    print("  Open: http://localhost:8777")
    print("=" * 50)
    threading.Timer(1.5, open_browser).start()
    uvicorn.run(app, host="127.0.0.1", port=8777, log_level="info")
