import httpx
import os
import subprocess
import tempfile
import shutil
import uuid
import time

GITHUB_API = "https://api.github.com"
RENDER_API = "https://api.render.com/v1"

# --- Helpers ---

def _gh_headers(token):
    return {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "User-Agent": "WebRunner",
    }

def _r_headers(api_key):
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

def _parse_error(resp):
    try:
        data = resp.json()
        if isinstance(data, dict):
            return data.get("message", data.get("error", str(resp.text)))
    except:
        pass
    return resp.text[:200]

# --- GitHub API ---

def get_github_username(token):
    resp = httpx.get(f"{GITHUB_API}/user", headers=_gh_headers(token), timeout=10)
    if resp.status_code != 200:
        raise Exception(f"GitHub auth failed (HTTP {resp.status_code}): {_parse_error(resp)}")
    return resp.json()["login"]

def create_github_repo(token, repo_name, private=True):
    resp = httpx.post(
        f"{GITHUB_API}/user/repos",
        headers=_gh_headers(token),
        json={
            "name": repo_name,
            "private": private,
            "auto_init": False,
            "description": "Deployed by WebRunner",
        },
        timeout=15,
    )
    if resp.status_code in (201, 200):
        return resp.json()["clone_url"]
    if resp.status_code == 422:
        err = _parse_error(resp)
        if "already exists" in err.lower():
            raise Exception(f"GitHub repo '{repo_name}' already exists. Delete it or use a different project name.")
        raise Exception(f"GitHub error (HTTP 422): {err}")
    raise Exception(f"GitHub repo creation failed (HTTP {resp.status_code}): {_parse_error(resp)}")

def get_repo_clone_url(token, username, repo_name):
    resp = httpx.get(
        f"{GITHUB_API}/repos/{username}/{repo_name}",
        headers=_gh_headers(token),
        timeout=10,
    )
    if resp.status_code != 200:
        raise Exception(f"Repo '{repo_name}' not found")
    return resp.json()["clone_url"]

def push_to_github(token, username, repo_name, project_path):
    deploy_id = str(uuid.uuid4())[:8]
    temp_dir = os.path.join(tempfile.gettempdir(), f"wr-{deploy_id}")
    if os.path.exists(temp_dir):
        shutil.rmtree(temp_dir)

    shutil.copytree(
        project_path, temp_dir,
        ignore=shutil.ignore_patterns(
            "__pycache__", ".git", ".env", "node_modules", "venv", ".venv",
            ".pytest_cache", ".mypy_cache", "__pycache__", "*.pyc", "*.pyo",
            ".DS_Store", "Thumbs.db", "*.db", "*.sqlite3",
            "dist", "build", "*.egg-info", ".tox",
        ),
    )

    repo_url = f"https://{token}@github.com/{username}/{repo_name}.git"

    try:
        subprocess.run(["git", "init"], cwd=temp_dir, capture_output=True, check=True, timeout=30)
        subprocess.run(["git", "config", "user.email", "webrunner@local.dev"], cwd=temp_dir, capture_output=True, check=True, timeout=10)
        subprocess.run(["git", "config", "user.name", "WebRunner"], cwd=temp_dir, capture_output=True, check=True, timeout=10)
        subprocess.run(["git", "add", "-A"], cwd=temp_dir, capture_output=True, check=True, timeout=120)
        subprocess.run(["git", "commit", "-m", "Initial commit from WebRunner"], cwd=temp_dir, capture_output=True, check=True, timeout=60)
        subprocess.run(["git", "remote", "add", "origin", repo_url], cwd=temp_dir, capture_output=True, check=True, timeout=10)
        push_timeout = 600
        result = subprocess.run(
            ["git", "push", "-uf", "origin", "main"],
            cwd=temp_dir,
            capture_output=True,
            timeout=push_timeout,
        )
        if result.returncode != 0:
            stderr = result.stderr.decode("utf-8", errors="replace")
            if "couldn't find remote ref" in stderr or "src refspec" in stderr:
                subprocess.run(["git", "branch", "-M", "main"], cwd=temp_dir, capture_output=True, timeout=10)
                result = subprocess.run(
                    ["git", "push", "-uf", "origin", "main"],
                    cwd=temp_dir, capture_output=True, timeout=push_timeout,
                )
            elif "failed to push" in stderr or "rejected" in stderr.lower():
                result = subprocess.run(
                    ["git", "push", "-uf", "origin", "main"],
                    cwd=temp_dir, capture_output=True, timeout=push_timeout,
                )
            if result.returncode != 0:
                raise Exception(f"Git push failed: {result.stderr.decode('utf-8', errors='replace')[:300]}")
    except subprocess.TimeoutExpired:
        raise Exception("Git push timed out after 10 minutes. The project might contain large files (>100MB each). Consider removing build artifacts, database files, or media uploads from the project folder.")
    except FileNotFoundError:
        raise Exception("Git is not installed or not in PATH. Install git from https://git-scm.com")
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)

    return repo_url

# --- Render API ---

def validate_api_key(api_key):
    try:
        resp = httpx.get(f"{RENDER_API}/owners", headers=_r_headers(api_key), timeout=10)
        return resp.status_code == 200
    except:
        return False

def get_owner_id(api_key):
    resp = httpx.get(f"{RENDER_API}/owners", headers=_r_headers(api_key), timeout=10)
    if resp.status_code != 200:
        raise Exception(f"Render auth failed: {_parse_error(resp)}")
    owners = resp.json()
    if not owners:
        raise Exception("No Render owners found. Create a team or workspace first.")
    return owners[0]["id"], owners[0]["name"]

def create_render_service(api_key, project_name, framework, entry_point, github_repo_url, has_requirements):
    owner_id, owner_name = get_owner_id(api_key)
    safe_name = project_name.lower().replace(" ", "-").replace("_", "-")
    service_name = f"wr-{safe_name}"

    build_cmd = _get_build_cmd(has_requirements, framework)

    if framework == "django":
        start_cmd = f"gunicorn {safe_name}.wsgi:application"
    elif framework == "flask":
        app_module = entry_point.replace(".py", "") if entry_point else "app"
        start_cmd = f"gunicorn {app_module}:app"
    elif framework == "fastapi":
        app_module = entry_point.replace(".py", "") if entry_point else "main"
        start_cmd = f"uvicorn {app_module}:app --host 0.0.0.0 --port 10000"
    else:
        start_cmd = f"python {entry_point or 'main.py'}"

    payload = {
        "type": "web_service",
        "name": service_name,
        "repo": github_repo_url,
        "autoDeploy": "yes",
        "branch": "main",
        "serviceDetails": {
            "env": "python",
            "buildCommand": build_cmd,
            "startCommand": start_cmd,
            "plan": "free",
            "pullRequestPreviewsEnabled": "no",
        },
    }

    resp = httpx.post(
        f"{RENDER_API}/services",
        headers=_r_headers(api_key),
        json=payload,
        timeout=30,
    )

    if resp.status_code not in (200, 201):
        raise Exception(f"Render API error: {_parse_error(resp)}")

    data = resp.json()
    service_id = data.get("id")
    service_url = data.get("serviceDetails", {}).get("url", "")

    return service_id, service_url

def wait_for_deploy(api_key, service_id, progress_callback=None):
    max_attempts = 60
    for attempt in range(max_attempts):
        try:
            resp = httpx.get(
                f"{RENDER_API}/services/{service_id}/deploys",
                headers=_r_headers(api_key),
                timeout=10,
            )
            if resp.status_code == 200:
                deploys = resp.json()
                if deploys:
                    latest = deploys[0]
                    status = latest.get("status", "")
                    deploy_id = latest.get("id", "")

                    if status == "live":
                        # Get the service URL
                        svc_resp = httpx.get(
                            f"{RENDER_API}/services/{service_id}",
                            headers=_r_headers(api_key),
                            timeout=10,
                        )
                        if svc_resp.status_code == 200:
                            svc_data = svc_resp.json()
                            url = svc_data.get("serviceDetails", {}).get("url", "")
                            if progress_callback:
                                progress_callback("live", "Deployment complete!", 100)
                            return url, deploy_id

                    elif status == "build_in_progress":
                        if progress_callback:
                            progress_callback("building", "Building on Render...", 40 + (attempt * 2))
                    elif status == "deploy_in_progress":
                        if progress_callback:
                            progress_callback("deploying", "Deploying...", 70 + attempt)
                    elif status == "failed":
                        if progress_callback:
                            progress_callback("error", "Render deployment failed", 0)
                        return None, deploy_id
        except:
            pass

        if progress_callback:
            progress_callback("waiting", "Waiting for Render...", 30)

        time.sleep(5)

    if progress_callback:
        progress_callback("error", "Deployment timed out", 0)
    return None, None

# --- Config file generation ---

def _get_build_cmd(has_requirements, framework):
    if has_requirements:
        return "pip install -r requirements.txt"
    framework_pkgs = {"django": "django gunicorn", "flask": "flask gunicorn", "fastapi": "fastapi uvicorn gunicorn"}
    return f"pip install {framework_pkgs.get(framework, 'gunicorn')}"

def _generate_render_yaml(project_name, framework, entry_point, has_requirements):
    safe_name = project_name.lower().replace(" ", "-").replace("_", "-")
    build_cmd = _get_build_cmd(has_requirements, framework)

    if framework == "django":
        start_cmd = f"gunicorn {safe_name}.wsgi:application"
    elif framework == "flask":
        app_module = entry_point.replace(".py", "") if entry_point else "app"
        start_cmd = f"gunicorn {app_module}:app"
    elif framework == "fastapi":
        app_module = entry_point.replace(".py", "") if entry_point else "main"
        start_cmd = f"uvicorn {app_module}:app --host 0.0.0.0 --port 10000"
    else:
        start_cmd = f"python {entry_point or 'main.py'}"

    return f"""services:
  - type: web
    name: {safe_name}
    env: python
    plan: free
    buildCommand: {build_cmd}
    startCommand: {start_cmd}
"""

def prepare_project_files(project_path, project_name, framework, entry_point, has_requirements):
    created = []
    render_yaml = os.path.join(project_path, "render.yaml")
    if not os.path.exists(render_yaml):
        with open(render_yaml, "w") as f:
            f.write(_generate_render_yaml(project_name, framework, entry_point, has_requirements))
        created.append("render.yaml")

    gitignore = os.path.join(project_path, ".gitignore")
    if not os.path.exists(gitignore):
        with open(gitignore, "w") as f:
            f.write("__pycache__/\n*.py[cod]\n.env\nvenv/\nenv/\n.DS_Store\n*.db\n")
        created.append(".gitignore")

    return created
