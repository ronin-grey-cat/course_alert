# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Running the app

```bash
# Development
python3 app.py

# Production (single worker is mandatory — see architecture note below)
gunicorn -w 1 -b 0.0.0.0:5000 --timeout 120 app:app
```

The app runs on port 5000. On macOS, port 5000 is occupied by AirPlay Receiver by default — disable it in System Settings → General → AirDrop & Handoff.

## First-run setup (VAPID keys)

Browser push notifications require VAPID keys. Generate them once:

1. Start the app **without** `VAPID_PUBLIC_KEY` set
2. Visit `http://localhost:5000/api/generate-vapid-keys`
3. Copy the returned keys into `.env`:
   ```
   VAPID_PUBLIC_KEY=<public_key value>
   VAPID_PRIVATE_KEY=<private_key_pem value — keep newlines as literal \n on one line>
   VAPID_SUBJECT=mailto:you@example.com
   FLASK_SECRET_KEY=<random string>
   ```

The `VAPID_PRIVATE_KEY` must be a single line in `.env` with `\n` as literal backslash-n (python-dotenv cannot parse multi-line values).

## Triggering the 24h check manually

```bash
curl -X POST http://localhost:5000/api/check-now
```

## Environment variables

| Variable | Purpose |
|---|---|
| `VAPID_PUBLIC_KEY` | Web Push public key (URL-safe base64) |
| `VAPID_PRIVATE_KEY` | EC private key PEM, newlines escaped as `\n` |
| `VAPID_SUBJECT` | `mailto:` URI for VAPID claims |
| `FLASK_SECRET_KEY` | Flask session secret |
| `DATABASE_PATH` | SQLite file path (default: `./course_alert.db`) |
| `PORT` | Server port (default: 5000) |
| `FLASK_DEBUG` | Set to `1` for debug mode |

## Architecture

**Single-process design**: Flask HTTP server + APScheduler background thread + SQLite all run in one process. This is intentional — Gunicorn **must** use `-w 1` (one worker). Multiple workers would each start their own APScheduler, causing duplicate 24h checks and duplicate push notifications.

### Data flow

```
Browser search → POST /api/search
  → scraper.search_courses()       # GET courses.myskillsfuture.gov.sg/search?q=...
  → scraper.get_course_runs()      # GET courses.myskillsfuture.gov.sg/courses/<slug>
  → returns runs[] with dates

User clicks Watch → POST /api/watch
  → db.upsert_watched_course()
  → db.upsert_subscription()       # stores browser PushSubscription
  → db.link_subscription_to_course()

Every 24h (APScheduler) → scheduler.run_checks()
  → scraper.get_course_runs() for each watched course
  → if no_runs → has_runs: notifications.send_push() for each subscriber
  → db.update_course_status()
  → if push returns 410/404: db.delete_subscription() (expired browser sub)
```

### Scraper: how portal data is extracted

`courses.myskillsfuture.gov.sg` is a Next.js SSR app. Course data is embedded in each page as a JavaScript Flight payload:

```html
<script>self.__next_f.push([1,"{ \"courseRuns\": [...] }"])</script>
```

`scraper._extract_course_data()` finds the script tag containing both `courseRuns` and `courseTitle`, decodes the JS string literal with `json.loads('"' + raw + '"')`, then parses the resulting JSON. No headless browser is needed.

Course URL format: `/courses/TGS-XXXXXXXX--course-title-slug`

When only a TGS ref is known (no slug), `_resolve_course_url()` searches for it first via `/search?q=TGS-XXXXXXXX` and extracts the full URL from results.

### Database (SQLite WAL mode)

Three tables in `database.py`:
- `watched_courses` — one row per TGS ref, tracks `last_status` (`no_runs` | `has_runs` | `error`)
- `push_subscriptions` — one row per browser (endpoint + p256dh + auth keys)
- `subscription_courses` — join table; CASCADE deletes clean up when a subscription is removed

Write serialisation uses a module-level `threading.Lock`. All writes go through the `_db(write=True)` context manager.

### Push notifications

`notifications.send_push()` writes the private key PEM to a temp file (pywebpush requires a file path, not an inline string), calls `pywebpush.webpush()`, then deletes the temp file. A 404/410 response from the push service means the subscription expired — the caller (`scheduler.run_checks`) deletes it from the DB.

### Frontend

Single-page app in `static/` — no build step, no framework. `app.js` stores the `PushSubscription` object in memory (not localStorage) and attaches it to watch requests. The service worker is served from `/sw.js` (not `/static/sw.js`) so its scope covers the full origin, enabling push receipt when the tab is closed.

## Docker

```bash
docker build -t course_alert .
docker run -d --name course_alert -p 5000:5000 \
  -v course_alert_data:/data --env-file .env course_alert
```

Mount `/data` as a volume for SQLite persistence across container restarts. HTTPS is required in production for Web Push and service workers — platforms like Railway, Render, and Fly.io provide it automatically.
