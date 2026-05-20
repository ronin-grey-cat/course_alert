"use strict";

// ── State ────────────────────────────────────────────────────────────────────
let pushSubscription = null; // stored PushSubscription object

// ── Boot ─────────────────────────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", async () => {
  loadWatchlist();
  await initPush();

  document.getElementById("search-form").addEventListener("submit", onSearch);
});

// ── Push notifications setup ──────────────────────────────────────────────────
async function initPush() {
  if (!("serviceWorker" in navigator) || !("PushManager" in window)) {
    showNotifBar(
      "warn",
      "Your browser doesn't support push notifications. You can still search for courses."
    );
    return;
  }

  try {
    const reg = await navigator.serviceWorker.register("/sw.js");
    await navigator.serviceWorker.ready;

    const res = await fetch("/api/vapid-public-key");
    if (!res.ok) {
      showNotifBar("warn", "Notification service not configured — watching still works.");
      return;
    }

    const { public_key } = await res.json();
    const appKey = urlBase64ToUint8Array(public_key);

    const permission = Notification.permission;
    if (permission === "denied") {
      showNotifBar("warn", "Notifications blocked. Enable them in browser settings to get alerts.");
      return;
    }

    let sub = await reg.pushManager.getSubscription();
    if (!sub) {
      if (permission !== "granted") {
        const result = await Notification.requestPermission();
        if (result !== "granted") {
          showNotifBar("warn", "Notifications not enabled — you won't receive alerts when runs open up.");
          return;
        }
      }
      sub = await reg.pushManager.subscribe({
        userVisibleOnly: true,
        applicationServerKey: appKey,
      });
      await fetch("/api/subscribe", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(sub.toJSON()),
      });
    }

    pushSubscription = sub;
    showNotifBar("info", "Notifications enabled — you'll be alerted when a watched course gets new runs.");
    setTimeout(() => hideNotifBar(), 4000);
  } catch (err) {
    console.warn("Push init error:", err);
  }
}

// ── Search ────────────────────────────────────────────────────────────────────
async function onSearch(e) {
  e.preventDefault();
  const query = document.getElementById("query").value.trim();
  if (!query) return;

  const btn = document.getElementById("search-btn");
  btn.disabled = true;
  btn.innerHTML = '<span class="spinner"></span>Searching…';

  document.getElementById("results-section").style.display = "none";
  document.getElementById("results-list").innerHTML = "";

  try {
    const res = await fetch("/api/search", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ query }),
    });
    const data = await res.json();

    if (!res.ok) {
      renderError(data.error || "Search failed");
      return;
    }

    renderResults(data);
  } catch (err) {
    renderError("Network error — check your connection.");
  } finally {
    btn.disabled = false;
    btn.textContent = "Search";
  }
}

function renderResults(data) {
  const section = document.getElementById("results-section");
  const list = document.getElementById("results-list");

  if (!data.courses || data.courses.length === 0) {
    list.innerHTML = '<div class="empty-state">No courses found. Try a different keyword or TGS reference.</div>';
    section.style.display = "block";
    return;
  }

  list.innerHTML = data.courses.map(renderCourseCard).join("");
  section.style.display = "block";

  list.querySelectorAll(".watch-btn").forEach((btn) => {
    btn.addEventListener("click", () => onWatch(btn));
  });
}

function renderCourseCard(course) {
  const hasRuns = course.runs && course.runs.length > 0;
  const runsHtml = hasRuns
    ? `<div class="run-list">
        ${course.runs
          .slice(0, 5)
          .map(
            (r) => `<div class="run-item">
              <span class="run-date">${formatDate(r.start_date)}</span>
              <span class="run-mode">${r.mode || ""}</span>
              <span class="run-vacancy">${r.vacancy || ""}</span>
            </div>`
          )
          .join("")}
        ${course.runs.length > 5 ? `<div class="run-item" style="background:none;border:none;color:var(--muted)">+${course.runs.length - 5} more run(s)</div>` : ""}
      </div>`
    : `<p style="font-size:0.8125rem;color:var(--muted);margin-top:0.5rem">No upcoming runs published yet.</p>`;

  const watchBtn = hasRuns
    ? ""
    : `<button class="btn btn-primary watch-btn"
          data-tgs="${course.tgs_ref}"
          data-title="${escHtml(course.title)}"
          data-provider="${escHtml(course.provider || "")}"
          data-url="${escHtml(course.course_url || "")}">
        Watch
      </button>`;

  const viewBtn = course.course_url
    ? `<a class="btn btn-outline" href="${escHtml(course.course_url)}" target="_blank" rel="noopener">View</a>`
    : "";

  return `
    <div class="card">
      <div class="card-header">
        <div>
          <div class="card-title">${escHtml(course.title)}</div>
          <div class="card-sub">${escHtml(course.tgs_ref)}${course.provider ? " · " + escHtml(course.provider) : ""}</div>
        </div>
        <div class="card-actions">${viewBtn}${watchBtn}</div>
      </div>
      ${runsHtml}
    </div>`;
}

// ── Watch a course ────────────────────────────────────────────────────────────
async function onWatch(btn) {
  const { tgs, title, provider, url } = btn.dataset;
  btn.disabled = true;
  btn.textContent = "Adding…";

  const body = {
    tgs_ref: tgs,
    title,
    provider,
    course_url: url,
  };
  if (pushSubscription) {
    body.subscription = pushSubscription.toJSON();
  }

  try {
    const res = await fetch("/api/watch", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (res.ok) {
      btn.textContent = "Watching ✓";
      btn.classList.remove("btn-primary");
      btn.classList.add("btn-outline");
      loadWatchlist();
    } else {
      btn.disabled = false;
      btn.textContent = "Watch";
    }
  } catch {
    btn.disabled = false;
    btn.textContent = "Watch";
  }
}

// ── Watchlist ─────────────────────────────────────────────────────────────────
async function loadWatchlist() {
  const endpoint = pushSubscription ? encodeURIComponent(pushSubscription.endpoint) : "";
  const url = endpoint ? `/api/watchlist?endpoint=${endpoint}` : "/api/watchlist";

  try {
    const res = await fetch(url);
    const data = await res.json();
    renderWatchlist(data.courses || []);
  } catch {
    document.getElementById("watchlist").innerHTML =
      '<div class="empty-state">Could not load watchlist.</div>';
  }
}

function renderWatchlist(courses) {
  const el = document.getElementById("watchlist");
  if (!courses.length) {
    el.innerHTML = '<div class="empty-state">Nothing here yet. Search for a course and click Watch to start monitoring it.</div>';
    return;
  }

  el.innerHTML = courses
    .map((c) => {
      const badge =
        c.last_status === "has_runs"
          ? '<span class="badge badge-green">Available</span>'
          : c.last_status === "error"
          ? '<span class="badge badge-red">Error</span>'
          : '<span class="badge badge-amber">Monitoring</span>';

      const checked = c.last_checked
        ? `Last checked ${formatRelative(c.last_checked)}`
        : "Not checked yet";

      const viewBtn = c.course_url
        ? `<a class="btn btn-outline" href="${escHtml(c.course_url)}" target="_blank" rel="noopener">View</a>`
        : "";

      return `
        <div class="card">
          <div class="card-header">
            <div>
              <div class="card-title">${escHtml(c.title)}</div>
              <div class="card-sub">${escHtml(c.tgs_ref)} · ${checked}</div>
            </div>
            <div class="card-actions">
              ${badge}
              ${viewBtn}
              <button class="btn btn-ghost remove-btn" data-tgs="${c.tgs_ref}" title="Remove">✕</button>
            </div>
          </div>
        </div>`;
    })
    .join("");

  el.querySelectorAll(".remove-btn").forEach((btn) => {
    btn.addEventListener("click", () => onRemove(btn.dataset.tgs));
  });
}

async function onRemove(tgsRef) {
  const body = {};
  if (pushSubscription) body.endpoint = pushSubscription.endpoint;

  await fetch(`/api/watch/${encodeURIComponent(tgsRef)}`, {
    method: "DELETE",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  loadWatchlist();
}

// ── Helpers ───────────────────────────────────────────────────────────────────
function showNotifBar(type, msg) {
  const bar = document.getElementById("notif-bar");
  bar.textContent = msg;
  bar.className = type;
  bar.style.display = "block";
}

function hideNotifBar() {
  document.getElementById("notif-bar").style.display = "none";
}

function renderError(msg) {
  const list = document.getElementById("results-list");
  list.innerHTML = `<div class="empty-state" style="color:var(--red)">${escHtml(msg)}</div>`;
  document.getElementById("results-section").style.display = "block";
}

function escHtml(str) {
  return String(str)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

function formatDate(iso) {
  if (!iso) return "";
  try {
    const d = new Date(iso);
    return d.toLocaleDateString("en-SG", { day: "numeric", month: "short", year: "numeric" });
  } catch {
    return iso;
  }
}

function formatRelative(iso) {
  try {
    const diff = Date.now() - new Date(iso + "Z").getTime();
    const h = Math.floor(diff / 3600000);
    if (h < 1) return "just now";
    if (h < 24) return `${h}h ago`;
    return `${Math.floor(h / 24)}d ago`;
  } catch {
    return iso;
  }
}

function urlBase64ToUint8Array(base64String) {
  const padding = "=".repeat((4 - (base64String.length % 4)) % 4);
  const base64 = (base64String + padding).replace(/-/g, "+").replace(/_/g, "/");
  const raw = atob(base64);
  return Uint8Array.from([...raw].map((c) => c.charCodeAt(0)));
}
