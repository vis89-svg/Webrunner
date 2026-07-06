const API = "/api";
let deployPollTimer = null;

function toast(msg, type = "info") {
    const t = document.createElement("div");
    t.className = `toast toast-${type}`;
    t.textContent = msg;
    document.body.appendChild(t);
    setTimeout(() => t.remove(), 4000);
}

async function apiFetch(path, opts = {}) {
    try {
        const res = await fetch(`${API}${path}`, {
            headers: { "Content-Type": "application/json" },
            ...opts,
        });
        if (!res.ok) {
            const err = await res.json().catch(() => ({ detail: res.statusText }));
            throw new Error(err.detail || `HTTP ${res.status}`);
        }
        return await res.json();
    } catch (e) {
        if (e.message === "Failed to fetch") {
            toast("Cannot reach the API server. Make sure WebRunner is running (python main.py) and the terminal window is open.", "error");
        } else {
            toast(e.message, "error");
        }
        throw e;
    }
}

function statusDot(status) { return `status-${status}`; }
function statusLabel(status) {
    return { live: "Live", deploying: "Deploying...", error: "Error", pending: "Pending" }[status] || status;
}
function badgeClass(fw) { return { django: "badge-django", flask: "badge-flask", fastapi: "badge-fastapi" }[fw] || "badge-python"; }

// --- Dashboard ---

function renderProjects(projects) {
    const list = document.getElementById("project-list");
    const empty = document.getElementById("empty-state");
    if (!list) return;
    if (!projects || projects.length === 0) {
        list.innerHTML = "";
        if (empty) empty.style.display = "block";
        return;
    }
    if (empty) empty.style.display = "none";

    list.innerHTML = projects.map(p => {
        const isLive = p.status === "live";
        return `
            <div class="project-card" data-id="${p.id}">
                <div class="project-info">
                    <div class="project-name">${p.name}</div>
                    <div class="project-meta">
                        <span class="badge ${badgeClass(p.framework)}">${p.framework || "python"}</span>
                        ${p.frontend_framework ? `<span>+ ${p.frontend_framework}</span>` : ""}
                        <span>${p.account_name || ""}</span>
                        ${p.github_repo ? `<span>repo</span>` : ""}
                    </div>
                    ${p.status === "deploying" ? `<div class="deploy-detail" id="prog-${p.id}">Starting deployment...</div>` : ""}
                </div>
                <div class="project-actions">
                    <div class="project-status">
                        <span class="status-dot ${statusDot(p.status)}"></span>
                        ${statusLabel(p.status)}
                    </div>
                    ${p.deploy_url && isLive ? `<a href="${p.deploy_url}" target="_blank" class="project-url">Open ↗</a>` : ""}
                    ${!isLive && p.status !== "deploying" ? `<button class="btn btn-primary btn-sm" onclick="deployProject(${p.id})">Deploy</button>` : ""}
                    <button class="btn btn-danger btn-sm" onclick="deleteProject(${p.id})">Remove</button>
                </div>
            </div>
        `;
    }).join("");

    // Start polling for deploying projects
    projects.filter(p => p.status === "deploying").forEach(p => {
        startDeployPoll(p.id);
    });
}

async function loadDashboard() {
    try {
        const [projects, accounts] = await Promise.all([
            apiFetch("/projects"),
            apiFetch("/accounts"),
        ]);
        renderProjects(projects);
        document.getElementById("total-projects").textContent = projects.length;
        document.getElementById("live-projects").textContent = projects.filter(p => p.status === "live").length;
        document.getElementById("total-accounts").textContent = accounts.length;
    } catch (e) {}
}

async function deployProject(id) {
    const btn = document.querySelector(`.project-card[data-id="${id}"] .btn-primary`);
    if (btn) { btn.disabled = true; btn.textContent = "Starting..."; }
    try {
        await apiFetch("/projects/deploy", {
            method: "POST",
            body: JSON.stringify({ project_id: id }),
        });
        toast("Deployment started! Building...", "success");
        loadDashboard();
    } catch (e) {
        if (btn) { btn.disabled = false; btn.textContent = "Deploy"; }
    }
}

async function deleteProject(id) {
    if (!confirm("Remove this project?")) return;
    try {
        await apiFetch("/projects/delete", { method: "POST", body: JSON.stringify({ project_id: id }) });
        toast("Project removed", "info");
        loadDashboard();
    } catch (e) {}
}

// --- Deploy Progress Polling ---

function startDeployPoll(projectId) {
    const detail = document.getElementById(`prog-${projectId}`);
    if (!detail) return;

    const poll = async () => {
        try {
            const p = await apiFetch(`/projects/${projectId}/deploy-progress`);
            if (detail) {
                const bar = detail.closest(".project-card")?.querySelector(".progress-bar-container .progress-bar");
                if (p.message) detail.textContent = p.message;
                if (bar) bar.style.width = `${p.pct || 0}%`;
            }
            // Update project card status
            const card = document.querySelector(`.project-card[data-id="${projectId}"]`);
            if (card && p.step === "live") {
                const statusEl = card.querySelector(".project-status");
                if (statusEl) {
                    statusEl.innerHTML = '<span class="status-dot status-live"></span> Live';
                }
                const urlBtn = card.querySelector(".project-url");
                if (!urlBtn && p.url) {
                    const actions = card.querySelector(".project-actions");
                    if (actions) {
                        const link = document.createElement("a");
                        link.href = p.url;
                        link.target = "_blank";
                        link.className = "project-url";
                        link.textContent = "Open ↗";
                        actions.insertBefore(link, actions.firstChild);
                    }
                }
                setTimeout(loadDashboard, 2000);
                return;
            }
            if (p.step === "error") {
                setTimeout(loadDashboard, 2000);
                return;
            }
            setTimeout(poll, 3000);
        } catch {
            setTimeout(poll, 5000);
        }
    };
    setTimeout(poll, 2000);
}

// --- Add Project Page ---

let scannedData = null;

async function scanFolder() {
    const path = document.getElementById("folder-path").value.trim();
    if (!path) { toast("Enter a folder path", "error"); return; }

    const btn = document.getElementById("scan-btn");
    btn.disabled = true;
    btn.textContent = "Scanning...";

    try {
        const data = await apiFetch("/scan", { method: "POST", body: JSON.stringify({ folder_path: path }) });
        scannedData = data;

        document.getElementById("scan-result").style.display = "block";
        document.getElementById("detected-framework").textContent = data.framework || "Not detected";
        document.getElementById("detected-frontend").textContent = data.frontend_framework || "None";
        document.getElementById("detected-entry").textContent = data.entry_point || "Auto-detected";
        document.getElementById("detected-deps").textContent =
            data.dependencies ? data.dependencies.length + " packages" : "requirements.txt not found";

        const folderName = path.split("\\").pop() || path.split("/").pop() || "";
        document.getElementById("project-name").value = folderName;

        document.getElementById("step2").style.display = "block";
        document.getElementById("step2").scrollIntoView({ behavior: "smooth" });

        await loadAccountsDropdown();
    } catch (e) {
    } finally {
        btn.disabled = false;
        btn.textContent = "Scan Again";
    }
}

async function loadAccountsDropdown() {
    const select = document.getElementById("account-select");
    try {
        const accounts = await apiFetch("/accounts");
        if (accounts.length === 0) {
            select.innerHTML = '<option value="">No accounts — add one first</option>';
            document.getElementById("no-account-msg").style.display = "block";
            return;
        }
        document.getElementById("no-account-msg").style.display = "none";

        const hasGithub = accounts.some(a => a.github_token);
        if (!hasGithub) {
            toast("Some accounts are missing a GitHub token. Deploy may fail.", "info");
        }

        select.innerHTML = accounts.map(a =>
            `<option value="${a.id}" data-has-gh="${!!a.github_token}">${a.name} (${a.provider})${a.github_token ? " ✓ GH" : " ⚠ no GH token"}</option>`
        ).join("");
    } catch (e) {
        select.innerHTML = '<option value="">Error loading accounts</option>';
    }
}

async function createProject() {
    const name = document.getElementById("project-name").value.trim();
    const folderPath = document.getElementById("folder-path").value.trim();
    const accountId = document.getElementById("account-select").value;

    if (!name) { toast("Enter a project name", "error"); return; }
    if (!accountId) { toast("Select an account", "error"); return; }

    // Check if account has GitHub token
    const sel = document.getElementById("account-select");
    const option = sel.options[sel.selectedIndex];
    if (option && option.dataset.hasGh === "false") {
        toast("This account has no GitHub token. Add one in Accounts page.", "error");
        return;
    }

    const btn = document.getElementById("deploy-btn");
    btn.disabled = true;
    btn.textContent = "Creating...";

    try {
        const result = await apiFetch("/projects", {
            method: "POST",
            body: JSON.stringify({ name, folder_path: folderPath, account_id: parseInt(accountId) }),
        });
        toast("Project created! Deploying...", "success");

        // Show progress panel
        document.getElementById("deploy-progress-panel").style.display = "block";
        document.getElementById("progress-message").textContent = "Starting deployment...";

        await apiFetch("/projects/deploy", { method: "POST", body: JSON.stringify({ project_id: result.id }) });

        // Poll progress
        const pollProgress = async () => {
            try {
                const p = await apiFetch(`/projects/${result.id}/deploy-progress`);
                const bar = document.getElementById("progress-bar");
                const msg = document.getElementById("progress-message");
                if (bar) bar.style.width = `${p.pct || 0}%`;
                if (msg) msg.textContent = p.message || "Working...";
                if (bar) {
                    bar.className = "progress-bar";
                    if (p.step === "error") bar.classList.add("error");
                    if (p.step === "live") bar.classList.add("live");
                }
                if (p.step === "live") {
                    setTimeout(() => window.location.href = "/", 2000);
                    return;
                }
                if (p.step === "error") {
                    btn.disabled = false;
                    btn.textContent = "Retry";
                    setTimeout(() => window.location.href = "/", 4000);
                    return;
                }
                setTimeout(pollProgress, 2500);
            } catch {
                setTimeout(pollProgress, 5000);
            }
        };
        setTimeout(pollProgress, 1500);
    } catch (e) {
        btn.disabled = false;
        btn.textContent = "Create & Deploy";
        document.getElementById("deploy-progress-panel").style.display = "none";
    }
}

// --- Accounts Page ---

async function loadAccountsPage() {
    try {
        const accounts = await apiFetch("/accounts");
        const list = document.getElementById("accounts-list");
        if (!list) return;

        if (accounts.length === 0) {
            list.innerHTML = '<div class="empty-state"><div class="icon">🔑</div><h3>No accounts yet</h3><p>Add a Render.com account with a GitHub token to deploy projects.</p></div>';
            return;
        }

        list.innerHTML = accounts.map(a => `
            <div class="project-card">
                <div class="project-info">
                    <div class="project-name">${a.name}</div>
                    <div class="project-meta">
                        <span class="badge badge-${a.provider}">${a.provider}</span>
                        ${a.email ? `<span>${a.email}</span>` : ""}
                        <span style="color: ${a.github_token ? 'var(--green)' : 'var(--red)'}">
                            ${a.github_token ? "✓ GitHub connected" : "✗ No GitHub token"}
                        </span>
                    </div>
                </div>
                <div class="project-actions">
                    <button class="btn btn-danger btn-sm" onclick="deleteAccount(${a.id})">Remove</button>
                </div>
            </div>
        `).join("");
    } catch (e) {}
}

async function addAccount() {
    const name = document.getElementById("acc-name").value.trim();
    const apiKey = document.getElementById("acc-key").value.trim();
    const ghToken = document.getElementById("acc-gh-token").value.trim();
    const email = document.getElementById("acc-email").value.trim();

    if (!name || !apiKey) { toast("Name and API key required", "error"); return; }

    try {
        await apiFetch("/accounts", {
            method: "POST",
            body: JSON.stringify({ name, provider: "render", api_key: apiKey, email, github_token: ghToken }),
        });
        toast("Account added!", "success");
        document.getElementById("acc-name").value = "";
        document.getElementById("acc-key").value = "";
        document.getElementById("acc-gh-token").value = "";
        document.getElementById("acc-email").value = "";
        loadAccountsPage();
    } catch (e) {}
}

async function deleteAccount(id) {
    if (!confirm("Remove this account?")) return;
    try {
        await apiFetch("/accounts", { method: "DELETE", body: JSON.stringify({ account_id: id }) });
        toast("Account removed", "info");
        loadAccountsPage();
    } catch (e) {}
}

// --- Connection check ---

async function checkConnection() {
    const statusEl = document.getElementById("conn-status");
    if (!statusEl) return;
    try {
        const res = await fetch("/api/health");
        if (res.ok) {
            statusEl.style.display = "none";
        } else {
            statusEl.style.display = "block";
            statusEl.style.background = "#e1705511";
            statusEl.style.border = "1px solid #e17055";
            statusEl.style.color = "#e17055";
            statusEl.innerHTML = "API server error. Restart WebRunner.";
        }
    } catch {
        statusEl.style.display = "block";
        statusEl.style.background = "#fdcb6e11";
        statusEl.style.border = "1px solid #fdcb6e";
        statusEl.style.color = "#fdcb6e";
        statusEl.innerHTML = 'Cannot reach API. Run <b>python main.py</b> and open <a href="http://127.0.0.1:8777" style="color:#6c5ce7;">http://127.0.0.1:8777</a>';
    }
}

// --- file:// detection ---

if (window.location.protocol === "file:") {
    document.body.innerHTML = `
        <div style="display:flex;align-items:center;justify-content:center;min-height:100vh;background:#0f1117;color:#e4e6f0;font-family:sans-serif;padding:40px;text-align:center;">
            <div>
                <h1 style="color:#6c5ce7;margin-bottom:16px;">WebRunner</h1>
                <h2 style="margin-bottom:12px;">Open via the server, not the file</h2>
                <p style="color:#8b8fa3;margin-bottom:20px;max-width:500px;">
                    You opened this HTML file directly. Run WebRunner through its Python server.
                </p>
                <code style="display:block;background:#1a1d27;padding:12px 20px;border-radius:6px;border:1px solid #2e3345;margin-bottom:20px;">
                    cd C:\\Users\\visha\\OneDrive\\Desktop\\Webrunner<br>
                    python main.py
                </code>
                <p style="color:#8b8fa3;">
                    Then open <a href="http://127.0.0.1:8777" style="color:#6c5ce7;">http://127.0.0.1:8777</a>
                </p>
            </div>
        </div>
    `;
    throw new Error("file:// access detected");
}

// Init
document.addEventListener("DOMContentLoaded", () => {
    if (document.getElementById("project-list")) loadDashboard();
    if (document.getElementById("accounts-list")) loadAccountsPage();
    if (document.getElementById("folder-path")) checkConnection();
});
