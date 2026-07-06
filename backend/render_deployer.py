import httpx
import os

RENDER_API_BASE = "https://api.render.com/v1"

def _headers(api_key):
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

def validate_api_key(api_key):
    try:
        resp = httpx.get(f"{RENDER_API_BASE}/owners", headers=_headers(api_key), timeout=10)
        return resp.status_code == 200
    except:
        return False

def _generate_render_yaml(project_name, framework, entry_point, has_requirements):
    safe_name = project_name.lower().replace(" ", "-").replace("_", "-")

    if has_requirements:
        build_cmd = "pip install -r requirements.txt"
    else:
        build_cmd = "pip install gunicorn"

    if framework == "django":
        # Try common Django wsgi paths
        start_cmd = f"gunicorn {safe_name}.wsgi:application"
    elif framework == "flask":
        app_module = entry_point.replace(".py", "")
        start_cmd = f"gunicorn {app_module}:app"
    elif framework == "fastapi":
        app_module = entry_point.replace(".py", "")
        start_cmd = f"uvicorn {app_module}:app --host 0.0.0.0 --port 10000"
    else:
        start_cmd = f"python {entry_point}"

    return f"""services:
  - type: web
    name: {safe_name}
    env: python
    plan: free
    buildCommand: {build_cmd}
    startCommand: {start_cmd}
"""

def _generate_dockerfile(framework, entry_point):
    if framework == "django":
        entry_cmd = f'gunicorn mysite.wsgi:application --bind 0.0.0.0:10000'
    elif framework == "flask":
        app_module = entry_point.replace(".py", "")
        entry_cmd = f'gunicorn {app_module}:app --bind 0.0.0.0:10000'
    elif framework == "fastapi":
        app_module = entry_point.replace(".py", "")
        entry_cmd = f'uvicorn {app_module}:app --host 0.0.0.0 --port 10000'
    else:
        entry_cmd = f'python {entry_point}'

    return f"""FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
EXPOSE 10000
CMD [{', '.join(f'"{p}"' for p in entry_cmd.split())}]
"""

def _generate_gitignore():
    return """__pycache__/
*.py[cod]
.env
venv/
env/
.DS_Store
*.db
"""

def prepare_project_files(project_path, project_name, framework, entry_point, has_requirements):
    created = []

    render_yaml = os.path.join(project_path, "render.yaml")
    if not os.path.exists(render_yaml):
        with open(render_yaml, "w") as f:
            f.write(_generate_render_yaml(project_name, framework, entry_point, has_requirements))
        created.append("render.yaml")

    dockerfile = os.path.join(project_path, "Dockerfile")
    if not os.path.exists(dockerfile):
        with open(dockerfile, "w") as f:
            f.write(_generate_dockerfile(framework, entry_point))
        created.append("Dockerfile")

    gitignore = os.path.join(project_path, ".gitignore")
    if not os.path.exists(gitignore):
        with open(gitignore, "w") as f:
            f.write(_generate_gitignore())
        created.append(".gitignore")

    return created

def get_deploy_instructions(project_name):
    safe_name = project_name.lower().replace(" ", "-").replace("_", "-")
    return {
        "steps": [
            "1. Push your project to a GitHub repository",
            "2. Log in to https://dashboard.render.com",
            '3. Click "New +" → "Blueprint"',
            "4. Connect your GitHub repo",
            "5. Render will detect render.yaml and deploy automatically",
        ],
        "expected_url": f"https://{safe_name}.onrender.com",
        "dashboard_url": "https://dashboard.render.com",
    }

def create_service(api_key, project_name, project_path):
    owner_id, owner_name = get_owner_id(api_key)
    safe_name = project_name.lower().replace(" ", "-").replace("_", "-")
    service_name = f"wr-{safe_name}"

    prepare_project_files(project_path, project_name, None, "main.py", False)

    return None, None, None

def get_service_status(api_key, service_id):
    if not service_id:
        return {"status": "unknown", "url": ""}
    try:
        resp = httpx.get(
            f"{RENDER_API_BASE}/services/{service_id}",
            headers=_headers(api_key),
            timeout=10,
        )
        if resp.status_code != 200:
            return {"status": "unknown", "url": ""}
        data = resp.json()
        return {
            "status": data.get("serviceDetails", {}).get("state", "unknown"),
            "url": data.get("serviceDetails", {}).get("url", ""),
        }
    except:
        return {"status": "unknown", "url": ""}

def delete_service(api_key, service_id):
    if not service_id:
        return True
    try:
        resp = httpx.delete(
            f"{RENDER_API_BASE}/services/{service_id}",
            headers=_headers(api_key),
            timeout=10,
        )
        return resp.status_code in (200, 204)
    except:
        return False
