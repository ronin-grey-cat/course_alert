import atexit
import logging
import os

from dotenv import load_dotenv

load_dotenv()

from flask import Flask, jsonify, request, send_from_directory

import database as db
from notifications import generate_vapid_keys
from scheduler import run_checks

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

app = Flask(__name__, static_folder="static")
app.config["SECRET_KEY"] = os.environ.get("FLASK_SECRET_KEY", os.urandom(24).hex())

db.init_db()


# ── Scheduler ─────────────────────────────────────────────────────────────────

def _start_scheduler():
    from apscheduler.schedulers.background import BackgroundScheduler

    scheduler = BackgroundScheduler(daemon=True)
    scheduler.add_job(
        func=run_checks,
        trigger="interval",
        hours=24,
        id="course_check",
        max_instances=1,
        misfire_grace_time=3600,
    )
    scheduler.start()
    atexit.register(lambda: scheduler.shutdown(wait=False))
    logger.info("Scheduler started — checks run every 24 hours")
    return scheduler


_scheduler = _start_scheduler()


# ── Static / frontend routes ──────────────────────────────────────────────────

@app.route("/")
def index():
    return send_from_directory("static", "index.html")


@app.route("/sw.js")
def service_worker():
    return send_from_directory("static", "sw.js")


@app.route("/manifest.json")
def manifest():
    return send_from_directory("static", "manifest.json")


# ── API: VAPID public key ─────────────────────────────────────────────────────

@app.route("/api/vapid-public-key")
def vapid_public_key():
    key = os.environ.get("VAPID_PUBLIC_KEY", "")
    if not key:
        return jsonify({"error": "VAPID keys not configured"}), 503
    return jsonify({"public_key": key})


# ── API: Push subscription ────────────────────────────────────────────────────

@app.route("/api/subscribe", methods=["POST"])
def subscribe():
    data = request.get_json(silent=True) or {}
    endpoint = data.get("endpoint", "")
    keys = data.get("keys", {})
    p256dh = keys.get("p256dh", "")
    auth = keys.get("auth", "")
    if not (endpoint and p256dh and auth):
        return jsonify({"error": "Invalid subscription"}), 400
    db.upsert_subscription(endpoint, p256dh, auth)
    return jsonify({"status": "subscribed"})


# ── API: Search courses ───────────────────────────────────────────────────────

@app.route("/api/search", methods=["POST"])
def search():
    from scraper import search_courses, get_course_runs

    data = request.get_json(silent=True) or {}
    query = (data.get("query") or "").strip()
    if not query:
        return jsonify({"error": "query is required"}), 400

    try:
        courses = search_courses(query)
    except Exception as exc:
        logger.error("Search error: %s", exc)
        return jsonify({"error": "Failed to reach SkillsFuture portal"}), 502

    if not courses:
        return jsonify({"status": "not_found", "courses": []})

    enriched = []
    for c in courses:
        try:
            detail = get_course_runs(c["tgs_ref"], c["course_url"])
            enriched.append(detail)
        except Exception as exc:
            logger.warning("Could not fetch runs for %s: %s", c["tgs_ref"], exc)
            enriched.append({**c, "runs": []})

    has_any_runs = any(len(c.get("runs", [])) > 0 for c in enriched)
    status = "found" if has_any_runs else "no_runs"
    return jsonify({"status": status, "courses": enriched})


# ── API: Watchlist ────────────────────────────────────────────────────────────

@app.route("/api/watchlist")
def watchlist():
    endpoint = request.args.get("endpoint", "")
    if endpoint:
        courses = db.get_watched_courses_for_sub(endpoint)
    else:
        courses = db.get_all_watched_courses()
    return jsonify({"courses": courses})


@app.route("/api/watch", methods=["POST"])
def watch():
    data = request.get_json(silent=True) or {}
    tgs_ref = (data.get("tgs_ref") or "").strip().upper()
    title = (data.get("title") or "").strip()
    provider = (data.get("provider") or "").strip()
    course_url = (data.get("course_url") or "").strip()
    subscription = data.get("subscription") or {}
    endpoint = subscription.get("endpoint", "")
    keys = subscription.get("keys", {})
    p256dh = keys.get("p256dh", "")
    auth = keys.get("auth", "")

    if not tgs_ref or not title:
        return jsonify({"error": "tgs_ref and title are required"}), 400

    db.upsert_watched_course(tgs_ref, title, provider, course_url)

    if endpoint and p256dh and auth:
        db.upsert_subscription(endpoint, p256dh, auth)
        db.link_subscription_to_course(endpoint, tgs_ref)

    return jsonify({"status": "watching", "tgs_ref": tgs_ref})


@app.route("/api/watch/<path:tgs_ref>", methods=["DELETE"])
def unwatch(tgs_ref):
    tgs_ref = tgs_ref.upper()
    data = request.get_json(silent=True) or {}
    endpoint = data.get("endpoint", "")
    if endpoint:
        db.remove_watched_course_for_sub(tgs_ref, endpoint)
    else:
        db.force_remove_watched_course(tgs_ref)
    return jsonify({"status": "removed"})


# ── Dev helper: trigger a check manually ─────────────────────────────────────

@app.route("/api/check-now", methods=["POST"])
def check_now():
    try:
        run_checks()
        return jsonify({"status": "done"})
    except Exception as exc:
        logger.error("Manual check error: %s", exc)
        return jsonify({"error": str(exc)}), 500


# ── VAPID key generation helper ───────────────────────────────────────────────

@app.route("/api/generate-vapid-keys")
def gen_vapid():
    """Only callable when VAPID keys are not yet configured. Used during setup."""
    if os.environ.get("VAPID_PUBLIC_KEY"):
        return jsonify({"error": "VAPID keys already set"}), 400
    keys = generate_vapid_keys()
    return jsonify(keys)


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    debug = os.environ.get("FLASK_DEBUG", "0") == "1"
    app.run(host="0.0.0.0", port=port, debug=debug, use_reloader=False)
