"""
Background 24-hour check for watched courses.
Called by APScheduler from app.py.
"""
import logging

logger = logging.getLogger(__name__)


def run_checks():
    """
    Check every watched course for new run dates.
    Notifies subscribers when status changes from no_runs → has_runs.
    """
    import database as db
    from scraper import get_course_runs
    from notifications import send_push

    courses = db.get_all_watched_courses()
    if not courses:
        logger.info("No watched courses to check")
        return

    logger.info("Checking %d watched course(s)", len(courses))

    for course in courses:
        tgs_ref = course["tgs_ref"]
        try:
            result = get_course_runs(tgs_ref, course.get("course_url", ""))
            runs = result.get("runs", [])
            new_status = "has_runs" if runs else "no_runs"
            prev_status = course.get("last_status", "no_runs")

            if prev_status == "no_runs" and new_status == "has_runs":
                logger.info("Course %s now has runs — notifying subscribers", tgs_ref)
                subscribers = db.get_subscribers_for_course(tgs_ref)
                for sub in subscribers:
                    try:
                        dead = send_push(sub, course, runs)
                        if dead:
                            logger.info("Removing dead subscription: %s", sub["endpoint"][:40])
                            db.delete_subscription(sub["endpoint"])
                    except Exception as exc:
                        logger.warning("Push failed for %s: %s", sub["endpoint"][:40], exc)

            db.update_course_status(tgs_ref, new_status)
            logger.info("Course %s: %s", tgs_ref, new_status)

        except Exception as exc:
            logger.error("Check failed for %s: %s", tgs_ref, exc)
            db.update_course_status(tgs_ref, "error")
