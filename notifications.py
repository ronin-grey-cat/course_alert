import base64
import json
import os
import tempfile

from cryptography.hazmat.primitives.serialization import (
    Encoding, PublicFormat, PrivateFormat, NoEncryption
)
from py_vapid import Vapid
from pywebpush import webpush, WebPushException


def generate_vapid_keys() -> dict:
    """Generate a new VAPID key pair. Returns {public_key, private_key_pem}."""
    v = Vapid()
    v.generate_keys()
    pub_bytes = v.public_key.public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)
    pub_b64 = base64.urlsafe_b64encode(pub_bytes).rstrip(b"=").decode()
    priv_pem = v.private_key.private_bytes(
        Encoding.PEM, PrivateFormat.TraditionalOpenSSL, NoEncryption()
    ).decode()
    return {"public_key": pub_b64, "private_key_pem": priv_pem}


def _private_key_pem() -> str:
    pem = os.environ.get("VAPID_PRIVATE_KEY", "")
    if not pem:
        raise RuntimeError("VAPID_PRIVATE_KEY environment variable is not set")
    return pem.replace("\\n", "\n")


def _vapid_claims() -> dict:
    return {"sub": os.environ.get("VAPID_SUBJECT", "mailto:admin@example.com")}


def send_push(subscription: dict, course: dict, runs: list) -> bool:
    """
    Send a browser push notification for a course becoming available.
    Returns True if the subscription is expired (caller should delete it).
    subscription keys: endpoint, p256dh, auth
    """
    next_run = ""
    if runs:
        r = runs[0]
        schedule = r.get("scheduleInfo", "")
        if schedule:
            next_run = schedule.strip()
        else:
            from datetime import datetime
            try:
                dt = datetime.fromisoformat(r["courseStartDate"])
                next_run = dt.strftime("%-d %b %Y")
            except Exception:
                pass

    payload = json.dumps({
        "title": f"Course run available: {course['title'][:50]}",
        "body": next_run or f"{len(runs)} upcoming run(s) — click to view",
        "tgs_ref": course["tgs_ref"],
        "url": course.get("course_url") or
               f"https://courses.myskillsfuture.gov.sg/search?q={course['tgs_ref']}",
    })

    pem = _private_key_pem()
    with tempfile.NamedTemporaryFile(mode="w", suffix=".pem", delete=False) as f:
        f.write(pem)
        pem_path = f.name

    try:
        webpush(
            subscription_info={
                "endpoint": subscription["endpoint"],
                "keys": {
                    "p256dh": subscription["p256dh"],
                    "auth": subscription["auth"],
                },
            },
            data=payload,
            vapid_private_key=pem_path,
            vapid_claims=_vapid_claims(),
        )
        return False
    except WebPushException as exc:
        if exc.response is not None and exc.response.status_code in (404, 410):
            return True
        raise
    finally:
        os.unlink(pem_path)
