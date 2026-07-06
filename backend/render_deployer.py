import httpx
import json
import os
import re
import time

RENDER_API_BASE = "https://api.render.com/v1"

def _headers(api_key):
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

def _parse_render_error(response):
    try:
        data = response.json()
        if isinstance(data, dict):
            return data.get("message", data.get("error", str(response.text)))
    except:
        pass
    return response.text[:200]

def validate_api_key(api_key):
    try:
        resp = httpx.get(f"{RENDER_API_BASE}/owners", headers=_headers(api_key), timeout=10)
        return resp.status_code == 200
    except:
        return False

def get_owner_id(api_key):
    resp = httpx.get(f"{RENDER_API_BASE}/owners", headers=_headers(api_key), timeout=10)
    if resp.status_code != 200:
        raise Exception(f"Failed to get owner: {_parse_render_error(resp)}")
    owners = resp.json()
    if not owners:
        raise Exception("No Render owners found. Create a team or workspace first.")
    return owners[0]["id"], owners[0]["name"]

def _generate_render_yaml(project_name, framework, entry_point, has_requirements):
    services = []
    service = {
        "type": "web",
        "name": project_name.lower().replace(" ", "-"),
        "env": "python",
        "buildCommand": "pip install -r requirements.txt" if has_requirements else "pip install -r requirements.txt 2>/dev/null || pip install gunicorn",
        "startCommand": "",
        "plan": "free",
    }

    if framework == "django":
        settings_module = f"{project_name.lower().replace('-', '_')}.settings"
        service["startCommand"] = f"gunicorn {project_name.lower().replace('-', '_')}.wsgi:application"
    elif framework == "flask":
        app_module = entry_point.replace(".py", "")
        service["startCommand"] = f"gunicorn {app_module}:app"
    elif framework == "fastapi":
        app_module = entry_point.replace(".py", "")
        service["startCommand"] = f"uvicorn {app_module}:app --host 0.0.0.0 --port 10000"
    else:
        service["startCommand"] = f"python {entry_point}"

    services.append(service)

    yaml_lines = []
    for svc in services:
        yaml_lines.append(f"services:")
        yaml_lines.append(f"  - type: {svc['type']}")
        yaml_lines.append(f"    name: {svc['name']}")
        yaml_lines.append(f"    env: {svc['env']}")
        yaml_lines.append(f"    plan: {svc['plan']}")
        yaml_lines.append(f"    buildCommand: {svc['buildCommand']}")
        yaml_lines.append(f"    startCommand: {svc['startCommand']}")

    return "\n".join(yaml_lines)

def _generate_dockerfile(framework, entry_point):
    lines = ["FROM python:3.11-slim", "WORKDIR /app"]
    lines.append("COPY requirements.txt .")
    lines.append("RUN pip install --no-cache-dir -r requirements.txt")
    lines.append("COPY . .")

    if framework == "django":
        lines.append(f'CMD ["gunicorn", "--bind", "0.0.0.0:10000", "mysite.wsgi:application"]')
    elif framework == "flask":
        app_module = entry_point.replace(".py", "")
        lines.append(f'CMD ["gunicorn", "--bind", "0.0.0.0:10000", "{app_module}:app"]')
    elif framework == "fastapi":
        app_module = entry_point.replace(".py", "")
        lines.append(f'CMD ["uvicorn", "{app_module}:app", "--host", "0.0.0.0", "--port", "10000"]')
    else:
        lines.append(f'CMD ["python", "{entry_point}"]')

    return "\n".join(lines)

def prepare_project_files(project_path, project_name, framework, entry_point, has_requirements):
    render_yaml_path = os.path.join(project_path, "render.yaml")
    if not os.path.exists(render_yaml_path):
        content = _generate_render_yaml(project_name, framework, entry_point, has_requirements)
        with open(render_yaml_path, "w") as f:
            f.write(content)

    dockerfile_path = os.path.join(project_path, "Dockerfile")
    if not os.path.exists(dockerfile_path):
        content = _generate_dockerfile(framework, entry_point)
        with open(dockerfile_path, "w") as f:
            f.write(content)

def create_service(api_key, project_name, project_path):
    owner_id, owner_name = get_owner_id(api_key)

    repo_name = project_name.lower().replace(" ", "-").replace("_", "-")
    service_name = f"wr-{repo_name}"

    if not os.path.isdir(project_path):
        raise Exception(f"Project path does not exist: {project_path}")

    render_yaml_path = os.path.join(project_path, "render.yaml")
    if not os.path.exists(render_yaml_path):
        raise Exception("render.yaml not found. Run prepare_project_files first.")

    try:
        import subprocess
        import tempfile
        import shutil
        import uuid

        deploy_id = str(uuid.uuid4())[:8]
        temp_dir = os.path.join(tempfile.gettempdir(), f"wr-deploy-{deploy_id}")
        if os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)
        shutil.copytree(project_path, temp_dir, ignore=shutil.ignore_patterns("__pycache__", ".git", ".env", "node_modules"))

        subprocess.run(["git", "init"], cwd=temp_dir, capture_output=True)
        subprocess.run(["git", "config", "user.email", "webrunner@local.dev"], cwd=temp_dir, capture_output=True)
        subprocess.run(["git", "config", "user.name", "WebRunner"], cwd=temp_dir, capture_output=True)
        subprocess.run(["git", "add", "-A"], cwd=temp_dir, capture_output=True)
        subprocess.run(["git", "commit", "-m", "Initial commit from WebRunner"], cwd=temp_dir, capture_output=True)

        payload = {
            "type": "web_service",
            "name": service_name,
            "repo": None,
            "autoDeploy": "yes",
            "branch": "main",
            "serviceDetails": {
                "env": "python",
                "buildCommand": "pip install -r requirements.txt",
                "startCommand": "",
                "plan": "free",
                "pullRequestPreviewsEnabled": "no",
            }
        }

        resp = httpx.post(
            f"{RENDER_API_BASE}/services",
            headers=_headers(api_key),
            json=payload,
            timeout=30,
        )

        if resp.status_code not in (200, 201):
            raise Exception(f"Render API error: {_parse_render_error(resp)}")

        data = resp.json()
        service_id = data.get("id")
        service_url = data.get("serviceDetails", {}).get("url", "")

        return service_id, service_url, temp_dir

    except Exception as e:
        raise Exception(f"Deployment failed: {str(e)}")

def create_manual_service(api_key, project_name):
    owner_id, owner_name = get_owner_id(api_key)
    service_name = f"wr-{project_name.lower().replace(' ', '-')}"

    payload = {
        "type": "web_service",
        "name": service_name,
        "autoDeploy": "yes",
        "branch": "main",
        "serviceDetails": {
            "env": "python",
            "buildCommand": "pip install -r requirements.txt",
            "startCommand": "",
            "plan": "free",
        }
    }

    resp = httpx.post(
        f"{RENDER_API_BASE}/services",
        headers=_headers(api_key),
        json=payload,
        timeout=30,
    )

    if resp.status_code not in (200, 201):
        raise Exception(f"Create service failed: {_parse_render_error(resp)}")

    data = resp.json()
    return data.get("id"), data.get("serviceDetails", {}).get("url", "")

def get_service_status(api_key, service_id):
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

def delete_service(api_key, service_id):
    resp = httpx.delete(
        f"{RENDER_API_BASE}/services/{service_id}",
        headers=_headers(api_key),
        timeout=10,
    )
    return resp.status_code in (200, 204)
