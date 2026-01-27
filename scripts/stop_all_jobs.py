
import sys
import os

# Ensure project root is in path
sys.path.append(os.getcwd())

try:
    from src.workers.celery_app import celery_app
except ImportError:
    # Fallback if running from scripts dir
    sys.path.append(os.path.dirname(os.getcwd()))
    from src.workers.celery_app import celery_app

def stop_all_jobs():
    print("Connecting to Celery...")
    try:
        inspect = celery_app.control.inspect()
        if not inspect:
            print("Error: Could not connect to Celery inspector.")
            return

        print("Inspecting active tasks...")
        active = inspect.active() or {}
        if not active:
            print("No active tasks found (or no workers connected).")
        
        for worker, tasks in active.items():
            print(f"Found {len(tasks)} active tasks on {worker}")
            for task in tasks:
                task_id = task['id']
                print(f"  Revoking active task {task_id}")
                celery_app.control.revoke(task_id, terminate=True, signal='SIGTERM')

        print("Inspecting reserved tasks...")
        reserved = inspect.reserved() or {}
        for worker, tasks in reserved.items():
            print(f"Found {len(tasks)} reserved tasks on {worker}")
            for task in tasks:
                task_id = task['id']
                print(f"  Revoking reserved task {task_id}")
                celery_app.control.revoke(task_id, terminate=True)

        print("Purging task queues...")
        purged_count = celery_app.control.purge()
        print(f"Purged {purged_count} tasks from queue.")
        
    except Exception as e:
        print(f"Error stopping jobs: {e}")

if __name__ == "__main__":
    stop_all_jobs()
