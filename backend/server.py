import os
import sys
import threading
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from . import db
from . import scanner
from . import render_deployer
from . import keep_alive

app = FastAPI(title="WebRunner")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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
    github_token: str = ""

class UpdateGithubTokenRequest(BaseModel):
    account_id: int
    github_token: str

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

# In-memory deploy progress tracker
deploy_progress = {}

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
    if req.github_token:
        try:
            render_deployer.get_github_username(req.github_token)
        except Exception as e:
            raise HTTPException(status_code=400, detail=f"Invalid GitHub token: {e}")
    id_ = db.add_account(req.name, req.provider, req.api_key, req.email, req.github_token)
    return {"id": id_, "message": "Account added"}

@app.post("/api/accounts/github-token")
def update_github_token(req: UpdateGithubTokenRequest):
    try:
        username = render_deployer.get_github_username(req.github_token)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid GitHub token: {e}")
    db.update_account(req.account_id, github_token=req.github_token)
    return {"message": f"GitHub token updated for @{username}"}

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

def _update_progress(project_id, step, message, pct):
    deploy_progress[project_id] = {"step": step, "message": message, "pct": pct}

@app.post("/api/projects/deploy")
def deploy_project(req: DeployRequest):
    project = db.get_project(req.project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    account = db.get_project(req.project_id)  # includes api_key, github_token
    if not account:
        raise HTTPException(status_code=404, detail="Project not found")
    if not account.get("api_key"):
        raise HTTPException(status_code=400, detail="No Render API key found for this account")
    if not account.get("github_token"):
        raise HTTPException(status_code=400, detail="No GitHub token set. Add it in Accounts page.")

    api_key = account["api_key"]
    github_token = account["github_token"]

    db.update_project(project["id"], status="deploying")

    def do_deploy():
        try:
            _update_progress(project["id"], "preparing", "Preparing deployment files...", 5)
            render_deployer.prepare_project_files(
                project_path=project["folder_path"],
                project_name=project["name"],
                framework=project["framework"],
                entry_point=project["entry_point"],
                has_requirements=True,
            )

            _update_progress(project["id"], "github", "Getting GitHub username...", 10)
            username = render_deployer.get_github_username(github_token)
            safe_name = project["name"].lower().replace(" ", "-").replace("_", "-")
            repo_name = f"wr-{safe_name}"

            _update_progress(project["id"], "github", f"Creating GitHub repo '{repo_name}'...", 20)
            clone_url = render_deployer.create_github_repo(github_token, repo_name)

            _update_progress(project["id"], "github", "Pushing code to GitHub...", 30)
            render_deployer.push_to_github(github_token, username, repo_name, project["folder_path"])

            github_repo_url = f"https://github.com/{username}/{repo_name}"
            db.update_project(project["id"], github_repo=github_repo_url)

            _update_progress(project["id"], "render", "Creating Render service...", 45)
            service_id, service_url = render_deployer.create_render_service(
                api_key=api_key,
                project_name=project["name"],
                framework=project["framework"],
                entry_point=project["entry_point"],
                github_repo_url=github_repo_url,
                has_requirements=True,
            )

            db.update_project(project["id"], render_service_id=service_id, deploy_url=service_url)

            _update_progress(project["id"], "building", "Waiting for Render to build (2-5 min)...", 55)

            def progress_callback(step, msg, pct):
                _update_progress(project["id"], step, msg, pct)

            final_url, deploy_id = render_deployer.wait_for_deploy(api_key, service_id, progress_callback)

            if final_url:
                _update_progress(project["id"], "live", "Deployment complete!", 100)
                db.update_project(project["id"], status="live", deploy_url=final_url)

                try:
                    keep_alive.setup_github_actions(
                        project_path=project["folder_path"],
                        project_name=project["name"],
                        deploy_url=final_url,
                    )
                    db.update_project(project["id"], keep_alive_setup=1)
                except:
                    pass
            else:
                _update_progress(project["id"], "error", "Deployment failed on Render side", 0)
                db.update_project(project["id"], status="error")

        except Exception as e:
            _update_progress(project["id"], "error", str(e), 0)
            db.update_project(project["id"], status="error")

    thread = threading.Thread(target=do_deploy, daemon=True)
    thread.start()

    return {"message": "Deployment started", "project_id": project["id"]}

@app.get("/api/projects/{project_id}/deploy-progress")
def get_deploy_progress(project_id: int):
    progress = deploy_progress.get(project_id)
    if not progress:
        project = db.get_project(project_id)
        if project:
            status = project.get("status", "unknown")
            if status == "live":
                return {"step": "live", "message": "Deployment complete!", "pct": 100}
            elif status == "error":
                return {"step": "error", "message": "Deployment failed", "pct": 0}
            elif status == "deploying":
                return {"step": "starting", "message": "Starting deployment...", "pct": 0}
            else:
                return {"step": "idle", "message": "", "pct": 0}
        return {"step": "not_found", "message": "", "pct": 0}
    return progress

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

def _serve_html(filename):
    path = os.path.join(static_dir, filename)
    if not os.path.isfile(path):
        return HTMLResponse(
            f"<html><body><h1>File not found</h1><p>{filename} not at {path}</p>"
            f"<p>static_dir = {static_dir}</p></body></html>",
            status_code=404,
        )
    return FileResponse(path)

@app.get("/")
def serve_index():
    return _serve_html("index.html")

@app.get("/add-project")
def serve_add_project():
    return _serve_html("add-project.html")

@app.get("/accounts")
def serve_accounts():
    return _serve_html("accounts.html")

def start_server():
    import uvicorn
    import socket

    db.init_db()

    # Find available port
    port = 8777
    for attempt in range(10):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("127.0.0.1", port))
                break
            except OSError:
                port += 1
    else:
        print("ERROR: Could not find a free port")
        input("Press Enter to exit...")
        return

    print()
    print("=" * 56)
    print("  WebRunner - Desktop Deployer")
    print()
    print(f"    >>>  http://127.0.0.1:{port}  <<<")
    print()
    print(f"  Frontend files: {static_dir}")
    for f in ("index.html", "add-project.html", "accounts.html"):
        p = os.path.join(static_dir, f)
        ok = "OK" if os.path.isfile(p) else "MISSING"
        print(f"    [{ok}] {f}")
    print("=" * 56)
    print("  Press Ctrl+C in this window to stop WebRunner")
    print("=" * 56)
    print()
    try:
        uvicorn.run(app, host="127.0.0.1", port=port, log_level="info")
    except KeyboardInterrupt:
        print("\nWebRunner stopped.")
    except Exception as e:
        print(f"\nWebRunner error: {e}")
        import traceback
        traceback.print_exc()
        input("\nPress Enter to exit...")
