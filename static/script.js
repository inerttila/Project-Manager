const API_BASE = "http://localhost:5000/api";

let currentProjectId = null;
let currentLinksProjectIndex = null;
let projects = [];
let draggingProjectIndex = null;
let currentOdooConfigVersion = "17";
let searchQuery = "";

// Load projects on page load
document.addEventListener("DOMContentLoaded", () => {
  loadProjects();
  initSearch();
});

// Load all projects
async function loadProjects() {
  try {
    const response = await fetch(`${API_BASE}/projects`);
    projects = await response.json();
    renderProjects();
  } catch (error) {
    console.error("Error loading projects:", error);
    showNotification("Failed to load projects", "error");
  }
}

// Get projects filtered by active search query
function getFilteredProjects() {
  const query = searchQuery.trim().toLowerCase();
  const indexedProjects = projects.map((project, index) => ({
    ...project,
    originalIndex: index,
  }));

  if (!query) {
    return indexedProjects;
  }

  return indexedProjects.filter((project) => {
    const nameMatch = project.name && project.name.toLowerCase().includes(query);
    const pathMatch = project.path && project.path.toLowerCase().includes(query);
    return nameMatch || pathMatch;
  });
}

// Check if any modal is currently open
function isModalOpen() {
  const modals = document.querySelectorAll(".modal");
  for (const modal of modals) {
    if (modal.style.display && modal.style.display !== "none") {
      return true;
    }
  }
  return false;
}

// Check if an input, textarea or editable element is focused
function isInputElement(el) {
  if (!el) return false;
  const tag = el.tagName;
  return tag === "INPUT" || tag === "TEXTAREA" || el.isContentEditable;
}

// Update floating quick search HUD
function updateSearchStatus(filteredCount, totalCount) {
  const hud = document.getElementById("quickSearchHud");
  const queryEl = document.getElementById("hudQuery");
  const countEl = document.getElementById("hudCount");
  if (!hud || !queryEl || !countEl) return;

  if (!searchQuery.trim()) {
    hud.style.display = "none";
    return;
  }

  hud.style.display = "flex";
  queryEl.textContent = searchQuery;

  if (filteredCount === 0) {
    countEl.textContent = "0 found";
    countEl.className = "hud-count empty";
  } else {
    countEl.textContent = `${filteredCount} of ${totalCount}`;
    countEl.className = "hud-count";
  }
}

// Clear active quick search
function clearQuickSearch() {
  searchQuery = "";
  renderProjects();
}

// Initialize type-to-search keyboard listener
function initSearch() {
  window.addEventListener("keydown", (e) => {
    // If user is focused on an input/textarea or a modal is currently open, do not intercept
    if (isInputElement(document.activeElement) || isModalOpen()) {
      return;
    }

    // Escape: clear search
    if (e.key === "Escape") {
      if (searchQuery) {
        e.preventDefault();
        clearQuickSearch();
      }
      return;
    }

    // Backspace: remove last character
    if (e.key === "Backspace") {
      if (searchQuery.length > 0) {
        e.preventDefault();
        searchQuery = searchQuery.slice(0, -1);
        renderProjects();
      }
      return;
    }

    // Ignore shortcut modifier keys (Ctrl, Alt, Meta)
    if (e.ctrlKey || e.altKey || e.metaKey) {
      return;
    }

    // Printable single characters (letters, numbers, symbols)
    if (e.key && e.key.length === 1) {
      // Don't start a fresh search with a space
      if (searchQuery.length === 0 && e.key === " ") {
        return;
      }
      e.preventDefault();
      searchQuery += e.key;
      renderProjects();
    }
  });
}

// Render projects as cards
function renderProjects() {
  const container = document.getElementById("projects-container");

  if (projects.length === 0) {
    container.innerHTML =
      '<p style="text-align: center; color: white; font-size: 1.2rem; grid-column: 1 / -1;">No projects added yet. Click "Add Project" to get started!</p>';
    updateSearchStatus(0, 0);
    return;
  }

  const filtered = getFilteredProjects();
  const isFiltered = searchQuery.trim().length > 0;
  updateSearchStatus(filtered.length, projects.length);

  if (filtered.length === 0) {
    container.className = "projects-grid";
    container.innerHTML = `
      <div class="no-search-results">
        <p>No projects found matching "<strong>${escapeHtml(searchQuery)}</strong>"</p>
        <button type="button" class="btn-clear-search" onclick="clearQuickSearch()">Clear search (Esc)</button>
      </div>
    `;
    return;
  }

  // If 3 or under 3 search results during active search, center them on screen
  if (isFiltered && filtered.length <= 3) {
    container.className = "projects-grid centered-results";
  } else {
    container.className = "projects-grid";
  }

  container.innerHTML = filtered
    .map(
      (project) => `
        <div class="project-card" 
             draggable="${isFiltered ? "false" : "true"}"
             data-project-index="${project.originalIndex}"
             onclick="openProjectActions(${project.originalIndex})"
             ${
               !isFiltered
                 ? `ondragstart="handleDragStart(event, ${project.originalIndex})"
             ondragover="handleDragOver(event, ${project.originalIndex})"
             ondragleave="handleDragLeave(event)"
             ondrop="handleDrop(event, ${project.originalIndex})"
             ondragend="handleDragEnd(event)"`
                 : ""
             }>
            <div class="project-menu" onclick="event.stopPropagation(); showProjectMenu(${project.originalIndex}, event)">⋯</div>
            <button type="button" class="project-links-icon-btn" onclick="event.stopPropagation(); openLinksModal(${project.originalIndex})" title="Open Links"><span class="project-icon">📁</span></button>
            <div class="project-name">${escapeHtml(project.name)}</div>
            <div class="project-path">${escapeHtml(project.path)}</div>
        </div>
    `,
    )
    .join("");
}

function handleDragStart(event, projectIndex) {
  // Close menu if open
  const menu = document.querySelector(".project-menu-dropdown");
  if (menu) menu.remove();

  draggingProjectIndex = projectIndex;
  event.dataTransfer.effectAllowed = "move";
  event.dataTransfer.setData("text/plain", String(projectIndex));

  const card = event.currentTarget;
  card.classList.add("dragging");
}

function handleDragOver(event, overIndex) {
  // Allow drop
  event.preventDefault();

  const card = event.currentTarget;
  // Don’t highlight the card we’re currently dragging
  if (draggingProjectIndex !== null && overIndex !== draggingProjectIndex) {
    card.classList.add("drag-over");
  }
}

function handleDragLeave(event) {
  const card = event.currentTarget;
  card.classList.remove("drag-over");
}

async function handleDrop(event, dropIndex) {
  event.preventDefault();

  const card = event.currentTarget;
  card.classList.remove("drag-over");

  const fromIndexRaw = event.dataTransfer.getData("text/plain");
  const fromIndex = Number(fromIndexRaw);

  if (
    !Number.isInteger(fromIndex) ||
    fromIndex < 0 ||
    fromIndex >= projects.length
  )
    return;
  if (dropIndex === fromIndex) return;

  // Reorder locally (move item)
  const [moved] = projects.splice(fromIndex, 1);
  projects.splice(dropIndex, 0, moved);

  // Re-render to reflect new order + correct indexes / handlers
  renderProjects();

  // Persist order to backend (stable key: path)
  try {
    await persistProjectOrder();
  } catch (e) {
    console.error("Failed to persist project order:", e);
    showNotification("Order changed (not saved)", "error");
  }
}

function handleDragEnd(event) {
  draggingProjectIndex = null;

  // Remove visual state
  document
    .querySelectorAll(".project-card.drag-over")
    .forEach((el) => el.classList.remove("drag-over"));
  const card = event.currentTarget;
  card.classList.remove("dragging");
}

async function persistProjectOrder() {
  const orderedPaths = projects.map((p) => p.path);
  const response = await fetch(`${API_BASE}/projects/reorder`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ordered_paths: orderedPaths }),
  });

  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(data.error || "Failed to save order");
  }
}

// Show project menu (delete option)
function showProjectMenu(projectId, event) {
  event.stopPropagation();

  // Remove existing menu if any
  const existingMenu = document.querySelector(".project-menu-dropdown");
  if (existingMenu) {
    existingMenu.remove();
    return;
  }

  // Get project data
  const project = projects[projectId];
  const hasGitRemote =
    project.git_remote_url && project.git_remote_url.trim() !== "";

  // Determine the Git hosting platform for display
  let gitPlatformName = "Git";
  if (project.git_remote_url) {
    if (project.git_remote_url.includes("github.com")) {
      gitPlatformName = "GitHub";
    } else if (
      project.git_remote_url.includes("gitlab.com") ||
      project.git_remote_url.includes("gitlab")
    ) {
      gitPlatformName = "GitLab";
    } else if (project.git_remote_url.includes("bitbucket.org")) {
      gitPlatformName = "Bitbucket";
    }
  }

  // Create menu dropdown
  const menu = document.createElement("div");
  menu.className = "project-menu-dropdown";
  menu.innerHTML = `
        <div class="menu-item" onclick="startProject(${projectId})">
            <span>▶️</span>
            <span>Start</span>
        </div>
        <div class="menu-item" onclick="openCursor(${projectId})">
            <span>💻</span>
            <span>Open Cursor</span>
        </div>
        <div class="menu-item" onclick="openTerminal(${projectId})">
            <span>⌨️</span>
            <span>Open Terminal</span>
        </div>
        ${
          hasGitRemote
            ? `
        <div class="menu-item" onclick="openGitRepository(${projectId})">
            <span>🔗</span>
            <span>Open on ${gitPlatformName}</span>
        </div>
        `
            : ""
        }
        <div class="menu-item" onclick="deleteProject(${projectId})">
            <span>🗑️</span>
            <span>Delete</span>
        </div>
    `;

  // Position menu
  const card = event.target.closest(".project-card");
  const rect = card.getBoundingClientRect();
  menu.style.top = rect.top + 40 + "px";
  menu.style.left = rect.right - 120 + "px";

  document.body.appendChild(menu);

  // Close menu when clicking outside
  setTimeout(() => {
    const closeMenu = (e) => {
      if (!menu.contains(e.target) && !card.contains(e.target)) {
        menu.remove();
        document.removeEventListener("click", closeMenu);
      }
    };
    document.addEventListener("click", closeMenu);
  }, 10);
}

// Open Git repository in browser (GitHub, GitLab, Bitbucket, etc.)
function openGitRepository(projectId) {
  // Remove menu if open
  const menu = document.querySelector(".project-menu-dropdown");
  if (menu) menu.remove();

  const project = projects[projectId];

  if (project && project.git_remote_url) {
    // Open Git repository URL in browser
    window.open(project.git_remote_url, "_blank");

    // Determine platform for notification
    let platformName = "repository";
    if (project.git_remote_url.includes("github.com")) {
      platformName = "GitHub";
    } else if (
      project.git_remote_url.includes("gitlab.com") ||
      project.git_remote_url.includes("gitlab")
    ) {
      platformName = "GitLab";
    } else if (project.git_remote_url.includes("bitbucket.org")) {
      platformName = "Bitbucket";
    }

    showNotification(`Opening ${platformName}...`, "success");
  } else {
    showNotification("Git repository URL not found for this project", "error");
  }
}

// Open Cursor at project path
async function openCursor(projectId) {
  // Remove menu if open
  const menu = document.querySelector(".project-menu-dropdown");
  if (menu) menu.remove();

  try {
    const response = await fetch(
      `${API_BASE}/projects/${projectId}/open-cursor`,
      {
        method: "POST",
      },
    );

    const data = await response.json();

    if (response.ok) {
      showNotification("Opening Cursor...", "success");
    } else {
      showNotification(data.error || "Failed to open Cursor", "error");
    }
  } catch (error) {
    console.error("Error opening Cursor:", error);
    showNotification("Failed to open Cursor", "error");
  }
}

// Open Terminal (PowerShell on Windows) in project directory
async function openTerminal(projectId) {
  const menu = document.querySelector(".project-menu-dropdown");
  if (menu) menu.remove();

  try {
    const response = await fetch(
      `${API_BASE}/projects/${projectId}/open-terminal`,
      {
        method: "POST",
      },
    );
    const data = await response.json();

    if (response.ok) {
      showNotification("Opening terminal in project...", "success");
    } else {
      showNotification(data.error || "Failed to open terminal", "error");
    }
  } catch (error) {
    console.error("Error opening terminal:", error);
    showNotification("Failed to open terminal", "error");
  }
}

// Start project using .vscode/launch.json (opens PowerShell with logs)
async function startProject(projectId) {
  const menu = document.querySelector(".project-menu-dropdown");
  if (menu) menu.remove();

  try {
    const response = await fetch(`${API_BASE}/projects/${projectId}/start`, {
      method: "POST",
    });
    const data = await response.json();

    if (response.ok) {
      showNotification(data.message || "Starting project...", "success");
    } else {
      showNotification(data.error || "Failed to start project", "error");
    }
  } catch (error) {
    console.error("Error starting project:", error);
    showNotification("Failed to start project", "error");
  }
}

// Delete project
async function deleteProject(projectId) {
  // Remove menu if open
  const menu = document.querySelector(".project-menu-dropdown");
  if (menu) menu.remove();

  try {
    const response = await fetch(`${API_BASE}/projects/${projectId}`, {
      method: "DELETE",
    });

    if (!response.ok) {
      const error = await response.json();
      showNotification(error.error || "Failed to delete project", "error");
      return;
    }

    showNotification("Project deleted successfully", "success");
    loadProjects();
  } catch (error) {
    console.error("Error deleting project:", error);
    showNotification("Failed to delete project", "error");
  }
}

// Show add project modal
function showAddProjectModal() {
  document.getElementById("addProjectModal").style.display = "block";
  document.getElementById("projectPath").value = "";
  document.getElementById("clonePath").value = "";
  document.getElementById("cloneUrl").value = "";
  switchSwipePage(0); // Reset to first page
}

// Close add project modal
function closeAddProjectModal() {
  document.getElementById("addProjectModal").style.display = "none";
}

// Swipe page management
let currentSwipePage = 0;
let swipeStartX = 0;
let swipeStartY = 0;
let isSwiping = false;

function switchSwipePage(pageIndex) {
  currentSwipePage = pageIndex;
  const pages = document.querySelectorAll(".swipe-page");
  const dots = document.querySelectorAll(".swipe-dot");

  pages.forEach((page, index) => {
    page.classList.toggle("active", index === pageIndex);
  });

  dots.forEach((dot, index) => {
    dot.classList.toggle("active", index === pageIndex);
  });
}

// Initialize swipe functionality
document.addEventListener("DOMContentLoaded", () => {
  const swipeContainer = document.getElementById("addProjectSwipeContainer");
  if (!swipeContainer) return;

  // Touch events for mobile
  swipeContainer.addEventListener("touchstart", (e) => {
    swipeStartX = e.touches[0].clientX;
    swipeStartY = e.touches[0].clientY;
    isSwiping = true;
  });

  swipeContainer.addEventListener("touchmove", (e) => {
    if (!isSwiping) return;
    e.preventDefault();
  });

  swipeContainer.addEventListener("touchend", (e) => {
    if (!isSwiping) return;
    isSwiping = false;

    const swipeEndX = e.changedTouches[0].clientX;
    const swipeEndY = e.changedTouches[0].clientY;
    const diffX = swipeStartX - swipeEndX;
    const diffY = swipeStartY - swipeEndY;

    // Only swipe if horizontal movement is greater than vertical (to avoid conflicts with scrolling)
    if (Math.abs(diffX) > Math.abs(diffY) && Math.abs(diffX) > 50) {
      if (diffX > 0 && currentSwipePage < 1) {
        // Swipe left - go to next page
        switchSwipePage(currentSwipePage + 1);
      } else if (diffX < 0 && currentSwipePage > 0) {
        // Swipe right - go to previous page
        switchSwipePage(currentSwipePage - 1);
      }
    }
  });

  // Mouse events for desktop
  swipeContainer.addEventListener("mousedown", (e) => {
    swipeStartX = e.clientX;
    swipeStartY = e.clientY;
    isSwiping = true;
    swipeContainer.style.cursor = "grabbing";
  });

  swipeContainer.addEventListener("mousemove", (e) => {
    if (!isSwiping) return;
    e.preventDefault();
  });

  swipeContainer.addEventListener("mouseup", (e) => {
    if (!isSwiping) return;
    isSwiping = false;
    swipeContainer.style.cursor = "grab";

    const swipeEndX = e.clientX;
    const swipeEndY = e.clientY;
    const diffX = swipeStartX - swipeEndX;
    const diffY = swipeStartY - swipeEndY;

    if (Math.abs(diffX) > Math.abs(diffY) && Math.abs(diffX) > 50) {
      if (diffX > 0 && currentSwipePage < 1) {
        switchSwipePage(currentSwipePage + 1);
      } else if (diffX < 0 && currentSwipePage > 0) {
        switchSwipePage(currentSwipePage - 1);
      }
    }
  });

  swipeContainer.addEventListener("mouseleave", () => {
    isSwiping = false;
    swipeContainer.style.cursor = "grab";
  });

  // Click on dots to switch pages
  document.querySelectorAll(".swipe-dot").forEach((dot, index) => {
    dot.addEventListener("click", () => switchSwipePage(index));
  });
});

// Add new project
async function addProject(event) {
  event.preventDefault();
  const path = document.getElementById("projectPath").value.trim();

  if (!path) {
    showNotification("Please enter a project path", "error");
    return;
  }

  try {
    const response = await fetch(`${API_BASE}/projects`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ path }),
    });

    if (!response.ok) {
      const error = await response.json();
      showNotification(error.error || "Failed to add project", "error");
      return;
    }

    closeAddProjectModal();
    showNotification("Project added successfully", "success");
    loadProjects();
  } catch (error) {
    console.error("Error adding project:", error);
    showNotification("Failed to add project", "error");
  }
}

// Clone project from URL
async function cloneProject(event) {
  event.preventDefault();
  const clonePath = document.getElementById("clonePath").value.trim();
  const cloneUrl = document.getElementById("cloneUrl").value.trim();

  if (!clonePath) {
    showNotification("Please enter a path to clone to", "error");
    return;
  }

  if (!cloneUrl) {
    showNotification("Please enter a repository URL", "error");
    return;
  }

  try {
    showNotification("Cloning repository...", "info");

    const response = await fetch(`${API_BASE}/projects/clone`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        clone_path: clonePath,
        repository_url: cloneUrl,
      }),
    });

    const data = await response.json();

    if (!response.ok) {
      showNotification(data.error || "Failed to clone project", "error");
      return;
    }

    closeAddProjectModal();
    showNotification("Project cloned and added successfully", "success");
    loadProjects();
  } catch (error) {
    console.error("Error cloning project:", error);
    showNotification("Failed to clone project", "error");
  }
}

// --- Links (per project, stored in projects.json) ---
function getProjectLinks(project) {
  const links = project && project.links;
  return Array.isArray(links) ? links : [];
}

function openLinksModal(projectIndex) {
  currentLinksProjectIndex = projectIndex;
  const project = projects[projectIndex];
  if (!project) return;
  document.getElementById("linkName").value = "";
  document.getElementById("linkUrl").value = "";
  document.getElementById("linksModal").style.display = "block";
  renderLinksList();
}

function closeLinksModal() {
  document.getElementById("linksModal").style.display = "none";
  currentLinksProjectIndex = null;
}

async function saveLinksToServer(links) {
  const response = await fetch(
    `${API_BASE}/projects/${currentLinksProjectIndex}/links`,
    {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ links }),
    },
  );
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(data.error || "Failed to save links");
  }
  return response.json();
}

async function addLink() {
  if (currentLinksProjectIndex === null) return;
  const name = document.getElementById("linkName").value.trim();
  const url = document.getElementById("linkUrl").value.trim();
  if (!name || !url) {
    showNotification("Please enter both link name and URL", "error");
    return;
  }
  const project = projects[currentLinksProjectIndex];
  const links = getProjectLinks(project).slice();
  links.push({ name, url });
  try {
    await saveLinksToServer(links);
    project.links = links;
    document.getElementById("linkName").value = "";
    document.getElementById("linkUrl").value = "";
    renderLinksList();
    showNotification("Link added", "success");
  } catch (err) {
    console.error(err);
    showNotification(err.message || "Failed to save links", "error");
  }
}

async function removeLink(linkIndex) {
  if (currentLinksProjectIndex === null) return;
  const project = projects[currentLinksProjectIndex];
  const links = getProjectLinks(project).slice();
  links.splice(linkIndex, 1);
  try {
    await saveLinksToServer(links);
    project.links = links;
    renderLinksList();
  } catch (err) {
    console.error(err);
    showNotification(err.message || "Failed to save links", "error");
  }
}

function renderLinksList() {
  const listEl = document.getElementById("linksList");
  if (currentLinksProjectIndex === null) return;
  const project = projects[currentLinksProjectIndex];
  const links = getProjectLinks(project);
  if (links.length === 0) {
    listEl.innerHTML =
      '<li class="links-empty">No links yet. Add one above.</li>';
    return;
  }
  listEl.innerHTML = links
    .map(
      (link, i) => `
        <li class="links-item">
            <a href="${escapeHtml(normalizeLinkUrl(link.url))}" target="_blank" rel="noopener noreferrer" class="links-item-name">${escapeHtml(link.name)}</a>
            <button type="button" class="links-item-remove" onclick="event.preventDefault(); removeLink(${i})" title="Remove">×</button>
        </li>
    `,
    )
    .join("");
}

// --- Shared terminal helpers ---
function clearTerminal(elementId) {
  const logEl = document.getElementById(elementId);
  logEl.innerHTML = "";
  logEl.classList.add("empty");
}

function appendTerminalLine(elementId, message, type = "log") {
  const logEl = document.getElementById(elementId);
  logEl.classList.remove("empty");

  const line = document.createElement("div");
  if (type === "error") line.className = "log-error";
  else if (type === "success") line.className = "log-success";
  else if (type === "command") line.className = "log-command";
  line.textContent = message;
  logEl.appendChild(line);
  logEl.scrollTop = logEl.scrollHeight;
}

async function consumeEventStream(
  response,
  elementId,
  successMessage = "Command finished successfully.",
) {
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw new Error(data.error || "Command failed");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let finalResult = null;

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;

    buffer += decoder.decode(value, { stream: true });
    const chunks = buffer.split("\n\n");
    buffer = chunks.pop() || "";

    for (const chunk of chunks) {
      const line = chunk.trim();
      if (!line.startsWith("data: ")) continue;

      const data = JSON.parse(line.slice(6));
      if (data.type === "log") {
        const type = data.message.startsWith("$ ") ? "command" : "log";
        appendTerminalLine(elementId, data.message, type);
      } else if (data.type === "error") {
        appendTerminalLine(elementId, `ERROR: ${data.message}`, "error");
        throw new Error(data.message);
      } else if (data.type === "done") {
        finalResult = data.result;
        appendTerminalLine(elementId, successMessage, "success");
      }
    }
  }

  return finalResult;
}

async function runGitStream(action, options = {}) {
  if (currentProjectId === null) return;

  clearTerminal("gitOutput");
  appendTerminalLine("gitOutput", `Running git ${action}...`);

  const response = await fetch(
    `${API_BASE}/projects/${currentProjectId}/git-stream`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action, ...options }),
    },
  );

  return consumeEventStream(response, "gitOutput");
}

// Open project actions modal
function openProjectActions(projectId) {
  currentProjectId = projectId;
  const project = projects[projectId];
  document.getElementById("projectNameTitle").textContent = project.name;
  document.getElementById("actionsModal").style.display = "block";
  clearTerminal("gitOutput");
}

// Close actions modal
function closeActionsModal() {
  document.getElementById("actionsModal").style.display = "none";
  currentProjectId = null;
}

// Show git status
async function showGitStatus() {
  if (currentProjectId === null) return;

  try {
    await runGitStream("status");
  } catch (error) {
    console.error("Error getting git status:", error);
    showNotification(error.message || "Failed to get git status", "error");
  }
}

// Show checkout modal
function showCheckoutModal() {
  document.getElementById("checkoutModal").style.display = "block";
  document.getElementById("branchName").value = "";
}

// Close checkout modal
function closeCheckoutModal() {
  document.getElementById("checkoutModal").style.display = "none";
}

// Checkout branch
async function checkoutBranch(event) {
  event.preventDefault();
  const branchName = document.getElementById("branchName").value.trim();

  if (!branchName) {
    showNotification("Please enter a branch name", "error");
    return;
  }

  if (currentProjectId === null) return;

  closeCheckoutModal();

  try {
    const result = await runGitStream("checkout", { branch: branchName });
    if (result?.branch) {
      showNotification(`Switched to branch: ${result.branch}`, "success");
    }
  } catch (error) {
    console.error("Error switching branch:", error);
    showNotification(error.message || "Failed to switch branch", "error");
  }
}

// Git pull
async function gitPull() {
  if (currentProjectId === null) return;

  try {
    await runGitStream("pull");
    showNotification("Pull completed", "success");
  } catch (error) {
    console.error("Error pulling changes:", error);
    showNotification(error.message || "Failed to pull changes", "error");
  }
}

// Close modals when clicking outside
window.onclick = function (event) {
  const modals = document.getElementsByClassName("modal");
  for (let modal of modals) {
    if (event.target === modal) {
      modal.style.display = "none";
    }
  }
};

// Show custom notification
function showNotification(message, type = "info") {
  const notification = document.getElementById("notification");
  notification.textContent = message;
  notification.className = `notification ${type} show`;

  setTimeout(() => {
    notification.classList.remove("show");
  }, 3000);
}

// --- Docker Restore ---
function showDockerRestoreModal() {
  document.getElementById("dockerRestoreModal").style.display = "block";
  clearTerminal("dockerRestoreLog");
}

function closeDockerRestoreModal() {
  document.getElementById("dockerRestoreModal").style.display = "none";
}

async function browseDockerBackup(event) {
  const mode = event?.shiftKey ? "folder" : "file";
  const browseBtn = document.querySelector("#dockerRestoreModal .path-browse-btn");
  if (browseBtn) browseBtn.disabled = true;

  try {
    const response = await fetch(`${API_BASE}/docker-restore/browse`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mode }),
    });
    const data = await response.json();
    if (!response.ok) {
      showNotification(data.error || "Failed to open file browser", "error");
      return;
    }
    if (data.cancelled || !data.path) {
      return;
    }

    document.getElementById("dockerBackupPath").value = data.path;
    await detectDockerBackup();
  } catch (error) {
    console.error("Error browsing backup path:", error);
    showNotification("Failed to open file browser", "error");
  } finally {
    if (browseBtn) browseBtn.disabled = false;
  }
}

async function detectDockerBackup() {
  const backupPath = document.getElementById("dockerBackupPath").value.trim();
  if (!backupPath) return;

  try {
    const response = await fetch(`${API_BASE}/docker-restore/detect`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ backup_path: backupPath }),
    });
    const data = await response.json();
    if (!response.ok) {
      showNotification(data.error || "Failed to detect backup", "error");
      return;
    }

    document.getElementById("dockerDbName").value = data.db_name || "";
  } catch (error) {
    console.error("Error detecting backup:", error);
    showNotification("Failed to detect backup", "error");
  }
}

async function runDockerRestore(event) {
  event.preventDefault();

  const backupPath = document.getElementById("dockerBackupPath").value.trim();
  let dbName = document.getElementById("dockerDbName").value.trim();
  const restoreBtn = document.getElementById("dockerRestoreBtn");

  if (!backupPath) {
    showNotification("Please enter a backup folder or .zip path", "error");
    return;
  }

  if (!dbName) {
    try {
      const detectResponse = await fetch(`${API_BASE}/docker-restore/detect`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ backup_path: backupPath }),
      });
      const detectData = await detectResponse.json();
      if (!detectResponse.ok) {
        showNotification(detectData.error || "Failed to detect backup", "error");
        return;
      }
      dbName = detectData.db_name || "";
      document.getElementById("dockerDbName").value = dbName;
    } catch (error) {
      showNotification("Failed to detect backup", "error");
      return;
    }
  }

  if (!dbName) {
    showNotification("Database name is required", "error");
    return;
  }

  restoreBtn.disabled = true;
  restoreBtn.textContent = "Restoring...";
  clearTerminal("dockerRestoreLog");
  appendTerminalLine("dockerRestoreLog", "Starting restore...");

  try {
    const response = await fetch(`${API_BASE}/docker-restore/restore-stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        backup_path: backupPath,
        db_name: dbName,
      }),
    });

    const result = await consumeEventStream(
      response,
      "dockerRestoreLog",
      "Restore finished successfully.",
    );
    if (result?.db_name) {
      showNotification(
        `Restored ${result.db_name} in container ${result.container_name || result.db_name + "-postgres"} on localhost:5435`,
        "success",
      );
    }
  } catch (error) {
    console.error("Error restoring database:", error);
    appendTerminalLine("dockerRestoreLog", error.message || "Restore failed", "error");
    showNotification(error.message || "Restore failed", "error");
  } finally {
    restoreBtn.disabled = false;
    restoreBtn.textContent = "Restore";
  }
}

// Show Odoo Config Path Modal
function showOdooConfigModal() {
  const modalTitle = document.querySelector("#odooConfigModal h2");
  const modalLabel = document.querySelector('label[for="odooConfigPath"]');
  const modalInput = document.getElementById("odooConfigPath");
  const modalFormButton = document.querySelector(
    '#odooConfigForm button[type="submit"]',
  );

  if (currentOdooConfigVersion === "11") {
    if (modalTitle) modalTitle.textContent = "Odoo 11 Config Path";
    if (modalLabel)
      modalLabel.textContent = "Enter full path to your Odoo 11 odoo.conf:";
    if (modalInput)
      modalInput.placeholder =
        "C:\\Users\\username\\Documents\\Odoo 11\\Odoo 11.0e\\server\\odoo.conf";
    if (modalFormButton) modalFormButton.textContent = "Save & Open Odoo 11";
  } else {
    if (modalTitle) modalTitle.textContent = "Odoo 17 Config Path";
    if (modalLabel)
      modalLabel.textContent = "Enter full path to your Odoo 17 odoo.conf:";
    if (modalInput)
      modalInput.placeholder =
        "C:\\Users\\username\\Documents\\Odoo17\\server\\odoo.conf";
    if (modalFormButton) modalFormButton.textContent = "Save & Open Odoo 17";
  }

  document.getElementById("odooConfigModal").style.display = "block";
  document.getElementById("odooConfigPath").value = "";
}

// Close Odoo Config Path Modal
function closeOdooConfigModal() {
  document.getElementById("odooConfigModal").style.display = "none";
}

// Save Odoo Config Path and open file
async function saveOdooConfigPath(event) {
  event.preventDefault();
  const path = document.getElementById("odooConfigPath").value.trim();

  if (!path) {
    showNotification("Please enter a path to odoo.conf", "error");
    return;
  }

  try {
    const settingsEndpoint =
      currentOdooConfigVersion === "11"
        ? `${API_BASE}/settings/odoo11-config-path`
        : `${API_BASE}/settings/odoo-config-path`;

    const openEndpoint =
      currentOdooConfigVersion === "11"
        ? `${API_BASE}/open-odoo-config-11`
        : `${API_BASE}/open-odoo-config`;

    // Save the path
    const saveRes = await fetch(settingsEndpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ odoo17_config_path: path }),
    });

    const saveData = await saveRes.json();
    if (!saveRes.ok) {
      showNotification(
        saveData.error || "Failed to save Odoo config path",
        "error",
      );
      return;
    }

    // Close modal
    closeOdooConfigModal();

    // Open the file
    const response = await fetch(openEndpoint, { method: "POST" });
    const data = await response.json();

    if (response.ok) {
      showNotification(
        `Opening Odoo ${currentOdooConfigVersion} config in Cursor...`,
        "success",
      );
    } else {
      showNotification(
        data.error || `Failed to open Odoo ${currentOdooConfigVersion} config`,
        "error",
      );
    }
  } catch (error) {
    console.error("Error saving Odoo config path:", error);
    showNotification("Failed to save Odoo config path", "error");
  }
}

// Open Odoo config file in Cursor
async function openOdooConfig() {
  try {
    currentOdooConfigVersion = "17";

    // Check if path is already saved
    const settingsRes = await fetch(`${API_BASE}/settings/odoo-config-path`);
    const settingsData = await settingsRes.json();

    const odooPath = settingsData.odoo17_config_path;

    // First time: show modal to ask user for path
    if (!odooPath) {
      showOdooConfigModal();
      return;
    }

    // Open using saved path
    const response = await fetch(`${API_BASE}/open-odoo-config`, {
      method: "POST",
    });
    const data = await response.json();

    if (response.ok) {
      showNotification("Opening Odoo config in Cursor...", "success");
    } else {
      showNotification(data.error || "Failed to open Odoo config", "error");
    }
  } catch (error) {
    console.error("Error opening Odoo config:", error);
    showNotification("Failed to open Odoo config", "error");
  }
}

// Open Odoo 11 config file in Cursor
async function openOdooConfig11() {
  try {
    currentOdooConfigVersion = "11";

    // Check if path is already saved
    const settingsRes = await fetch(`${API_BASE}/settings/odoo11-config-path`);
    const settingsData = await settingsRes.json();
    const odoo11Path = settingsData.odoo17_config_path;

    // First time: show modal to ask user for path
    if (!odoo11Path) {
      showOdooConfigModal();
      return;
    }

    // Open using saved path
    const response = await fetch(`${API_BASE}/open-odoo-config-11`, {
      method: "POST",
    });
    const data = await response.json();

    if (response.ok) {
      showNotification("Opening Odoo 11 config in Cursor...", "success");
    } else {
      showNotification(data.error || "Failed to open Odoo 11 config", "error");
    }
  } catch (error) {
    console.error("Error opening Odoo 11 config:", error);
    showNotification("Failed to open Odoo 11 config", "error");
  }
}

// Escape HTML to prevent XSS
function escapeHtml(text) {
  const div = document.createElement("div");
  div.textContent = text;
  return div.innerHTML;
}

// Ensure link URL has a scheme so it opens as absolute URL (not relative to current host)
function normalizeLinkUrl(url) {
  if (!url || typeof url !== "string") return url || "";
  const u = url.trim();
  if (u.startsWith("http://") || u.startsWith("https://")) return u;
  return "http://" + u;
}
