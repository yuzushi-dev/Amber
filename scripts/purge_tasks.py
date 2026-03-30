
from src.workers.celery_app import celery_app

print("Purging celery queue...")
purged = celery_app.control.purge()
print(f"Purged {purged} tasks.")

# Also inspect active to see if we can revoke
i = celery_app.control.inspect()
active = i.active()
if active:
    for worker, tasks in active.items():
        print(f"Active tasks on {worker}: {len(tasks)}")
        for task in tasks:
            print(f"  Revoking {task['id']}")
            celery_app.control.revoke(task['id'], terminate=True, signal='SIGKILL')
