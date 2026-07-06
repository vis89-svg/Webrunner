import os
import re

GITHUB_ACTIONS_TEMPLATE = """name: WebRunner Keep Alive
on:
  schedule:
    - cron: '*/14 * * * *'
  workflow_dispatch:

jobs:
  ping:
    runs-on: ubuntu-latest
    steps:
      - name: Ping {project_name}
        run: curl -sSf "{deploy_url}" > /dev/null 2>&1 || echo "Ping completed (non-200 response)"
"""

def setup_github_actions(project_path, project_name, deploy_url):
    github_dir = os.path.join(project_path, ".github", "workflows")
    os.makedirs(github_dir, exist_ok=True)

    workflow_path = os.path.join(github_dir, "keep-alive.yml")
    content = GITHUB_ACTIONS_TEMPLATE.format(
        project_name=re.sub(r'[^a-zA-Z0-9\s-]', '', project_name),
        deploy_url=deploy_url
    )

    with open(workflow_path, "w") as f:
        f.write(content)

    return workflow_path

def setup_uptimerobot_monitor(api_key, monitor_url, friendly_name):
    try:
        import httpx
        resp = httpx.post(
            "https://api.uptimerobot.com/v2/newMonitor",
            data={
                "api_key": api_key,
                "format": "json",
                "type": 1,
                "url": monitor_url,
                "friendly_name": friendly_name,
                "interval": 300,
            },
            timeout=10,
        )
        return resp.json() if resp.status_code == 200 else None
    except:
        return None
