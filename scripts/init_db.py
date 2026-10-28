import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pymongo.errors import PyMongoError

from spatial.db import get_client, mongo_settings
from spatial.schema import ensure_collections, ensure_indexes, print_summary


def main() -> int:
    settings = mongo_settings()
    if not settings["username"] or not settings["password"]:
        print("[FAIL] Missing MongoDB credentials in .env")
        return 1

    client = get_client()
    try:
        client.admin.command("ping")
        database = client[settings["database"]]
        ensure_collections(database)
        ensure_indexes(database)
        print_summary(database)
        print()
        print(f"[OK] Database initialization completed: {settings['database']}")
        return 0
    except (PyMongoError, RuntimeError) as exc:
        print(f"[FAIL] MongoDB initialization failed: {exc}")
        return 1
    finally:
        client.close()


if __name__ == "__main__":
    sys.exit(main())
