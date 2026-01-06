import sys

from pymilvus import connections, utility


def check_version():
    try:
        connections.connect(host="milvus", port="19530")
        ver = utility.get_server_version()
        print(f"Milvus Server Version: {ver}")

        # Simple check for hybrid capabilities on server side isn't direct via utility API easily
        # but version check is sufficient.
        connections.disconnect("default")
    except Exception as e:
        print(f"Failed to connect to Milvus: {e}")
        sys.exit(1)

if __name__ == "__main__":
    check_version()
