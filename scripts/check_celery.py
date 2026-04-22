import os
import sys

# Add src to path
sys.path.append(os.getcwd())

from src.workers.celery_app import celery_app


def check_active_tasks():
    i = celery_app.control.inspect()
    active = i.active() or {}
    reserved = i.reserved() or {}
    scheduled = i.scheduled() or {}

    counts = {
        "active": 0,
        "reserved": 0,
        "scheduled": 0
    }

    target_task = "src.workers.tasks.process_communities"

    for worker, tasks in active.items():
        for task in tasks:
            if task.get("name") == target_task:
                counts["active"] += 1

    for worker, tasks in reserved.items():
        for task in tasks:
            if task.get("name") == target_task:
                counts["reserved"] += 1

    for worker, tasks in scheduled.items():
        for task in tasks:
            if task.get("name") == target_task:
                counts["scheduled"] += 1

    print("Community Jobs (process_communities):")
    print(f"- Active: {counts['active']}")
    print(f"- Reserved: {counts['reserved']}")
    print(f"- Scheduled: {counts['scheduled']}")

    # Also check other tasks if interested
    all_active = 0
    for worker, tasks in active.items():
        all_active += len(tasks)
    print(f"Total Active Tasks (all types): {all_active}")

if __name__ == "__main__":
    check_active_tasks()
