I'm currently in **plan mode** which means I can't create files yet. Let me lay out the full implementation plan, and once you give the go-ahead, I'll switch to implement mode and build everything.

---

## Full Implementation Plan

### Project Structure
```
C:\Users\visha\OneDrive\Desktop\Webrunner\
├── main.py                  # Entry point - starts everything
├── requirements.txt         # Python dependencies
│
├── backend/
│   ├── server.py            # FastAPI server
│   ├── scanner.py           # Project framework detector
│   ├── render_deployer.py   # Render.com API integration
│   ├── keep_alive.py        # GitHub Actions / ping setup
│   └── db.py               # SQLite database (projects + accounts)
│
├── frontend/
│   ├── index.html           # Dashboard page
│   ├── add-project.html     # New project wizard
│   ├── styles.css           # Styling
│   └── app.js               # Frontend logic (Alpine.js or vanilla JS)
│
└── static/
    └── icons/               # Framework icons (Django, Flask, etc.)
```

### What each file does

| File | Purpose |
|---|---|
| `main.py` | Launches FastAPI server + opens browser to dashboard |
| `backend/server.py` | API routes: list projects, add project, deploy, get status |
| `backend/scanner.py` | Scans project folder, detects Django/Flask/FastAPI/React/Vue, finds entry point |
| `backend/render_deployer.py` | Generates `render.yaml`, calls Render API, tracks deploy status |
| `backend/keep_alive.py` | Creates GitHub Actions workflow, manages pings |
| `backend/db.py` | SQLite schema: accounts table, projects table, CRUD operations |
| `frontend/index.html` | Dashboard showing all projects + accounts with live status |
| `frontend/add-project.html` | Step-by-step wizard: pick folder → detected framework → pick account → deploy |
| `frontend/app.js` | All frontend API calls, UI updates, form handling |
| `frontend/styles.css` | Modern, clean UI |

### API Routes (FastAPI)
```
GET    /api/projects         → List all projects with status
POST   /api/projects         → Add a new project
POST   /api/projects/{id}/deploy → Trigger deployment
GET    /api/projects/{id}    → Project details + URL
DELETE /api/projects/{id}    → Remove project

GET    /api/accounts         → List provider accounts (Render, etc.)
POST   /api/accounts         → Add a provider account
DELETE /api/accounts/{id}    → Remove account

POST   /api/scan             → Scan a folder and return detected framework
GET    /api/status           → Overall health / uptime of all projects
```

### Database Schema (SQLite)
```sql
CREATE TABLE accounts (
    id INTEGER PRIMARY KEY,
    name TEXT,              -- "My Render Account 1"
    provider TEXT,          -- "render" | "pythonanywhere"
    api_key TEXT,
    email TEXT,
    created_at TIMESTAMP
);

CREATE TABLE projects (
    id INTEGER PRIMARY KEY,
    name TEXT,              -- "My Django Blog"
    folder_path TEXT,
    framework TEXT,         -- "django" | "flask" | "fastapi"
    frontend_framework TEXT, -- "react" | "vue" | "none"
    account_id INTEGER REFERENCES accounts(id),
    deploy_url TEXT,        -- The live URL
    status TEXT,            -- "pending" | "deploying" | "live" | "error"
    render_service_id TEXT, -- Render service ID for management
    created_at TIMESTAMP,
    updated_at TIMESTAMP
);
```

### Deployment Flow (detailed)
1. User selects project folder → `/api/scan` detects framework
2. User selects or adds a provider account → `/api/accounts`
3. User clicks Deploy → `/api/projects` creates project record
4. Backend generates `render.yaml` in project folder (or Dockerfile)
5. Backend creates service via Render API → gets service ID + URL
6. Backend triggers initial deploy → polls until live
7. Backend creates `.github/workflows/keep-alive.yml` in the project repo
8. Dashboard shows URL as "live" → user copies link for LinkedIn

### Keep-Alive Strategy
GitHub Action workflow pings the URL every 14 minutes:
```yaml
name: Keep Alive
on:
  schedule:
    - cron: '*/14 * * * *'
jobs:
  ping:
    runs-on: ubuntu-latest
    steps:
      - run: curl -sSf <DEPLOY_URL> > /dev/null
```

1. User clicks "Create & Deploy"
2. WebRunner generates render.yaml + Dockerfile
3. Creates GitHub repo: "wr-{project-name}"
4. git init → add → commit → push to GitHub
5. Calls Render API: create service from GitHub repo
6. Render starts building (poll every 10 sec)
7. When deployed → URL is ready
8. Sets up GitHub Actions keep-alive
9. Project shows "Live" with URL