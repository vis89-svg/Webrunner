import os
import re

def scan_project(folder_path):
    if not os.path.isdir(folder_path):
        return {"error": "Folder does not exist"}

    result = {
        "framework": None,
        "frontend_framework": None,
        "entry_point": None,
        "has_requirements": False,
        "has_package_json": False,
        "python_version": None,
        "dependencies": [],
    }

    files = set()
    for root, dirs, fnames in os.walk(folder_path):
        for f in fnames:
            files.add(os.path.join(root, f))

    rel_files = {os.path.relpath(f, folder_path) for f in files}

    # --- Backend detection ---
    if "manage.py" in rel_files:
        result["framework"] = "django"
        result["entry_point"] = "manage.py"
    elif "app.py" in rel_files:
        result["framework"] = "flask"
        result["entry_point"] = "app.py"
    elif "main.py" in rel_files:
        with open(os.path.join(folder_path, "main.py"), "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
        if "FastAPI" in content or "fastapi" in content:
            result["framework"] = "fastapi"
        elif "Flask" in content or "flask" in content:
            result["framework"] = "flask"
        else:
            result["framework"] = "python"
        result["entry_point"] = "main.py"
    else:
        py_files = [f for f in rel_files if f.endswith(".py")]
        if py_files:
            for f in sorted(py_files):
                with open(os.path.join(folder_path, f), "r", encoding="utf-8", errors="ignore") as fh:
                    content = fh.read()
                if "FastAPI" in content or "fastapi" in content:
                    result["framework"] = "fastapi"
                    result["entry_point"] = f
                    break
                elif "Flask" in content or "flask" in content:
                    result["framework"] = "flask"
                    result["entry_point"] = f
                    break
                elif "django" in content or "Django" in content:
                    if "wsgi" in content or "asgi" in content:
                        result["framework"] = "django"
                        result["entry_point"] = f
                        break

    if "requirements.txt" in rel_files:
        result["has_requirements"] = True
        with open(os.path.join(folder_path, "requirements.txt"), "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
        deps = [line.strip() for line in content.split("\n") if line.strip() and not line.startswith("#")]
        result["dependencies"] = deps
        for dep in deps:
            m = re.match(r"^([a-zA-Z][a-zA-Z0-9_.-]*)", dep)
            if m:
                pkg = m.group(1).lower()
                if pkg in ("django", "flask", "fastapi", "uvicorn", "gunicorn"):
                    pass

    # --- Frontend detection ---
    if "package.json" in rel_files:
        result["has_package_json"] = True
        with open(os.path.join(folder_path, "package.json"), "r", encoding="utf-8", errors="ignore") as f:
            content = f.read()
        if '"react"' in content:
            result["frontend_framework"] = "react"
        elif '"vue"' in content or '"nuxt"' in content:
            result["frontend_framework"] = "vue"
        elif '"svelte"' in content:
            result["frontend_framework"] = "svelte"
        elif '"next"' in content or '"nextjs"' in content:
            result["frontend_framework"] = "nextjs"
        elif '"angular"' in content:
            result["frontend_framework"] = "angular"
        else:
            result["frontend_framework"] = "javascript"

    # Check for index.html as static site fallback
    if not result["frontend_framework"]:
        for f in rel_files:
            if f.endswith(".html"):
                result["frontend_framework"] = "static"
                break

    # Check for Dockerfile
    if "Dockerfile" in rel_files:
        result["has_dockerfile"] = True

    return result
