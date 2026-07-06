const API = "/api";

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

function statusLabel(status) {
    const map = {
        live: "Live",
        deploying: "Deploying...",
        error: "Error",
        pending: "Pending",
        removed: "Removed",
    };
    return map[status] || status;
}

function badgeClass(framework) {
    const map = { django: "badge-django", flask: "badge-flask", fastapi: "badge-fastapi" };
    return map[framework] || "badge-python";
}

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
        const fw = p.framework || "python";
        const isLive = p.status === "live";
        return `
            <div class="project-card" data-id="${p.id}">
                <div class="project-info">
                    <div class="project-name">${p.name}</div>
                    <div class="project-meta">
                        <span class="badge ${badgeClass(fw)}">${fw}</span>
                        ${p.frontend_framework ? `<span>+ ${p.frontend_framework}</span>` : ""}
                        <span>${p.account_name || "No account"}</span>
                        <span>${p.folder_path ? p.folder_path.split('\\').pop() || p.folder_path.split('/').pop() : ""}</span>
                    </div>
                </div>
                <div class="project-actions">
                    <div class="project-status">
                        <span class="status-dot status-${p.status}"></span>
                        ${statusLabel(p.status)}
                    </div>
                    ${p.deploy_url ? `<a href="${p.deploy_url}" target="_blank" class="project-url">Open ↗</a>` : ""}
                    ${!isLive ? `<button class="btn btn-primary btn-sm" onclick="deployProject(${p.id})">Deploy</button>` : ""}
                    <button class="btn btn-danger btn-sm" onclick="deleteProject(${p.id})">Remove</button>
                </div>
            </div>
        `;
    }).join("");
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
    } catch (e) {
        // error already toasted
    }
}

async function deployProject(id) {
    const btn = document.querySelector(`.project-card[data-id="${id}"] .btn-primary`);
    if (btn) { btn.disabled = true; btn.textContent = "Deploying..."; }
    try {
        await apiFetch("/projects/deploy", {
            method: "POST",
            body: JSON.stringify({ project_id: id }),
        });
        toast("Deployment started!", "success");
        setTimeout(loadDashboard, 2000);
    } catch (e) {
        if (btn) { btn.disabled = false; btn.textContent = "Deploy"; }
    }
}

async function deleteProject(id) {
    if (!confirm("Remove this project?")) return;
    try {
        await apiFetch("/projects/delete", {
            method: "POST",
            body: JSON.stringify({ project_id: id }),
        });
        toast("Project removed", "info");
        loadDashboard();
    } catch (e) {}
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
        const data = await apiFetch("/scan", {
            method: "POST",
            body: JSON.stringify({ folder_path: path }),
        });
        scannedData = data;

        document.getElementById("scan-result").style.display = "block";
        document.getElementById("detected-framework").textContent = data.framework || "Not detected";
        document.getElementById("detected-frontend").textContent = data.frontend_framework || "None";
        document.getElementById("detected-entry").textContent = data.entry_point || "Auto-detected";
        document.getElementById("detected-deps").textContent =
            data.dependencies ? data.dependencies.length + " packages" : "requirements.txt not found";

        // Auto-fill name from folder
        const folderName = path.split("\\").pop() || path.split("/").pop() || "";
        document.getElementById("project-name").value = folderName;

        document.getElementById("step2").style.display = "block";
        document.getElementById("step2").scrollIntoView({ behavior: "smooth" });

        loadAccountsDropdown();
    } catch (e) {
        // already toasted
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
        select.innerHTML = accounts.map(a =>
            `<option value="${a.id}">${a.name} (${a.provider})</option>`
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

    const btn = document.getElementById("deploy-btn");
    btn.disabled = true;
    btn.textContent = "Creating...";

    try {
        const result = await apiFetch("/projects", {
            method: "POST",
            body: JSON.stringify({
                name,
                folder_path: folderPath,
                account_id: parseInt(accountId),
            }),
        });

        toast("Project created! Deploying...", "success");

        await apiFetch("/projects/deploy", {
            method: "POST",
            body: JSON.stringify({ project_id: result.id }),
        });

        setTimeout(() => {
            window.location.href = "/";
        }, 1500);
    } catch (e) {
        btn.disabled = false;
        btn.textContent = "Create & Deploy";
    }
}

// --- Accounts Page ---
async function loadAccountsPage() {
    try {
        const accounts = await apiFetch("/accounts");
        const list = document.getElementById("accounts-list");
        if (!list) return;

        if (accounts.length === 0) {
            list.innerHTML = '<div class="empty-state"><div class="icon">🔑</div><h3>No accounts yet</h3><p>Add a Render.com account to deploy projects.</p></div>';
            return;
        }

        list.innerHTML = accounts.map(a => `
            <div class="project-card">
                <div class="project-info">
                    <div class="project-name">${a.name}</div>
                    <div class="project-meta">
                        <span class="badge badge-${a.provider}">${a.provider}</span>
                        ${a.email ? `<span>${a.email}</span>` : ""}
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
    const email = document.getElementById("acc-email").value.trim();

    if (!name || !apiKey) { toast("Name and API key required", "error"); return; }

    try {
        await apiFetch("/accounts", {
            method: "POST",
            body: JSON.stringify({
                name,
                provider: "render",
                api_key: apiKey,
                email,
            }),
        });
        toast("Account added!", "success");
        document.getElementById("acc-name").value = "";
        document.getElementById("acc-key").value = "";
        document.getElementById("acc-email").value = "";
        loadAccountsPage();
    } catch (e) {}
}

async function deleteAccount(id) {
    if (!confirm("Remove this account?")) return;
    try {
        await apiFetch("/accounts", {
            method: "DELETE",
            body: JSON.stringify({ account_id: id }),
        });
        toast("Account removed", "info");
        loadAccountsPage();
    } catch (e) {}
}

// Connectivity check
async function checkConnection() {
    const statusEl = document.getElementById("conn-status");
    if (!statusEl) return;
    try {
        const res = await fetch("http://localhost:8777/api/health");
        if (res.ok) {
            statusEl.style.display = "none";
        } else {
            statusEl.style.display = "block";
            statusEl.style.background = "#e1705511";
            statusEl.style.border = "1px solid #e17055";
            statusEl.style.color = "#e17055";
            statusEl.innerHTML = "API server responded but with an error. Try restarting WebRunner.";
        }
    } catch {
        statusEl.style.display = "block";
        statusEl.style.background = "#fdcb6e11";
        statusEl.style.border = "1px solid #fdcb6e";
        statusEl.style.color = "#fdcb6e";
        statusEl.innerHTML = 'Cannot reach the API server. Make sure WebRunner is running via <b>python main.py</b> and access this page at <a href="http://localhost:8777/add-project" style="color:#6c5ce7;">http://localhost:8777/add-project</a>';
    }
}

// Check if accessed via file:// protocol (user opened HTML directly)
if (window.location.protocol === "file:") {
    document.body.innerHTML = `
        <div style="display:flex;align-items:center;justify-content:center;min-height:100vh;background:#0f1117;color:#e4e6f0;font-family:sans-serif;padding:40px;text-align:center;">
            <div>
                <h1 style="color:#6c5ce7;margin-bottom:16px;">WebRunner</h1>
                <h2 style="margin-bottom:12px;">Open via the server, not the file</h2>
                <p style="color:#8b8fa3;margin-bottom:20px;max-width:500px;">
                    You opened this HTML file directly. WebRunner needs to run through its Python server.
                </p>
                <code style="display:block;background:#1a1d27;padding:12px 20px;border-radius:6px;border:1px solid #2e3345;margin-bottom:20px;">
                    cd C:\Users\visha\OneDrive\Desktop\Webrunner<br>
                    python main.py
                </code>
                <p style="color:#8b8fa3;">
                    Then open <a href="http://localhost:8777" style="color:#6c5ce7;">http://localhost:8777</a>
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
