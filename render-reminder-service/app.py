# ═══════════════════════════════════════════════
# OpenClaw Render Reminder Service
# Deploy this to Render.com (free tier) for
# 24/7 reminders even when PC is off
# ═══════════════════════════════════════════════

import json
import os
from datetime import datetime
from pathlib import Path

import requests
from apscheduler.schedulers.background import BackgroundScheduler
from flask import Flask, jsonify, request

app = Flask(__name__)

REMINDERS_FILE = Path(__file__).parent / "render_reminders.json"
# Your ngrok/PC webhook URL — set via env var
PC_WEBHOOK_URL = os.getenv("PC_WEBHOOK_URL", "")
WEBHOOK_SECRET = os.getenv("RENDER_WEBHOOK_SECRET", "openclaw_secret")


def load_reminders():
    if REMINDERS_FILE.exists():
        try:
            return json.loads(REMINDERS_FILE.read_text())
        except Exception:
            return []
    return []


def save_reminders(rems):
    REMINDERS_FILE.write_text(json.dumps(rems, indent=2))


def fire_reminder(reminder):
    """Send reminder notification to the PC via webhook."""
    print(f"[⏰ FIRING] {reminder['text']} @ {reminder['time']}")

    if PC_WEBHOOK_URL:
        try:
            resp = requests.post(
                f"{PC_WEBHOOK_URL}/api/webhook/reminder",
                json={
                    "text": reminder["text"],
                    "time": reminder["time"],
                    "secret": WEBHOOK_SECRET,
                },
                timeout=10,
            )
            print(f"  → PC notified: {resp.status_code}")
        except Exception as e:
            print(f"  → PC unreachable: {e}")

    # Mark one-time reminders as done
    if reminder.get("repeat", "none") == "none":
        rems = load_reminders()
        for r in rems:
            if r["id"] == reminder["id"]:
                r["active"] = False
        save_reminders(rems)


scheduler = BackgroundScheduler()


def schedule_all():
    scheduler.remove_all_jobs()
    rems = load_reminders()
    for r in rems:
        if not r.get("active", True):
            continue
        try:
            hour, minute = map(int, r["time"].split(":"))
        except (ValueError, KeyError):
            continue

        repeat = r.get("repeat", "none")
        if repeat == "daily":
            scheduler.add_job(fire_reminder, "cron", args=[r], hour=hour, minute=minute, id=r["id"], replace_existing=True)
        elif repeat == "weekly":
            scheduler.add_job(fire_reminder, "cron", args=[r], day_of_week="*", hour=hour, minute=minute, id=r["id"], replace_existing=True)
        else:
            date_str = r.get("date", "")
            if date_str:
                try:
                    d = datetime.strptime(date_str, "%Y-%m-%d")
                    scheduler.add_job(
                        fire_reminder, "cron", args=[r],
                        year=d.year, month=d.month, day=d.day,
                        hour=hour, minute=minute,
                        id=r["id"], replace_existing=True,
                    )
                except ValueError:
                    scheduler.add_job(fire_reminder, "cron", args=[r], hour=hour, minute=minute, id=r["id"], replace_existing=True)
            else:
                scheduler.add_job(fire_reminder, "cron", args=[r], hour=hour, minute=minute, id=r["id"], replace_existing=True)


# ── API Routes ──────────────────────────────────

@app.route("/")
def index():
    return jsonify({"service": "OpenClaw Reminder Service", "status": "running"})


@app.route("/api/reminders", methods=["GET"])
def get_reminders():
    return jsonify(load_reminders())


@app.route("/api/reminders", methods=["POST"])
def add_reminder():
    data = request.json
    import uuid
    reminder = {
        "id": str(uuid.uuid4())[:8],
        "text": data.get("text", ""),
        "time": data.get("time", ""),
        "date": data.get("date", ""),
        "repeat": data.get("repeat", "none"),
        "active": True,
        "created": datetime.now().isoformat(),
    }
    rems = load_reminders()
    rems.append(reminder)
    save_reminders(rems)
    schedule_all()
    return jsonify(reminder), 201


@app.route("/api/reminders/<rid>", methods=["DELETE"])
def delete_reminder(rid):
    rems = [r for r in load_reminders() if r["id"] != rid]
    save_reminders(rems)
    schedule_all()
    return jsonify({"deleted": rid})


@app.route("/api/reminders/<rid>", methods=["PUT"])
def update_reminder(rid):
    data = request.json
    rems = load_reminders()
    for r in rems:
        if r["id"] == rid:
            r.update({
                "text": data.get("text", r["text"]),
                "time": data.get("time", r["time"]),
                "date": data.get("date", r.get("date", "")),
                "repeat": data.get("repeat", r.get("repeat", "none")),
            })
    save_reminders(rems)
    schedule_all()
    return jsonify({"updated": rid})


@app.route("/api/set-pc-url", methods=["POST"])
def set_pc_url():
    """Update the PC webhook URL (your ngrok URL)."""
    global PC_WEBHOOK_URL
    data = request.json
    PC_WEBHOOK_URL = data.get("url", "")
    return jsonify({"pc_url": PC_WEBHOOK_URL})


# ── Start ─────────────────────────────────────────

scheduler.start()
schedule_all()

if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    print(f"🔔 OpenClaw Reminder Service running on port {port}")
    app.run(host="0.0.0.0", port=port)
