import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from pymongo import MongoClient


ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

SEED_DIR = ROOT / "data" / "seed"
BATCH_SIZE = 1000


def read_jsonl(path: Path):
    with path.open("r", encoding="utf-8") as file:
        for line in file:
            line = line.strip()
            if line:
                yield json.loads(line)


def import_collection(database, collection_name: str, path: Path) -> int:
    collection = database[collection_name]
    collection.delete_many({"data_version": "seed-v1"})

    batch = []
    count = 0

    for document in read_jsonl(path):
        batch.append(document)

        if len(batch) >= BATCH_SIZE:
            collection.insert_many(batch, ordered=False)
            count += len(batch)
            batch.clear()

    if batch:
        collection.insert_many(batch, ordered=False)
        count += len(batch)

    return count


def main() -> int:
    username = os.getenv("MONGO_ROOT_USERNAME")
    password = os.getenv("MONGO_ROOT_PASSWORD")
    port = int(os.getenv("MONGO_PORT", "27017"))
    database_name = os.getenv("MONGO_DATABASE", "campus_service")

    client = MongoClient(
        "127.0.0.1",
        port,
        username=username,
        password=password,
        authSource="admin",
        serverSelectionTimeoutMS=5000,
        appname="campus-static-seed-import",
    )

    try:
        client.admin.command("ping")
        database = client[database_name]

        building_count = import_collection(
            database,
            "buildings",
            SEED_DIR / "buildings.jsonl",
        )

        facility_count = import_collection(
            database,
            "facilities",
            SEED_DIR / "facilities.jsonl",
        )

        metadata = json.loads(
            (SEED_DIR / "metadata.json").read_text(encoding="utf-8")
        )

        database["dataset_metadata"].replace_one(
            {"_id": metadata["_id"]},
            metadata,
            upsert=True,
        )

        print(f"[OK] imported buildings: {building_count}")
        print(f"[OK] imported facilities: {facility_count}")
        print(f"[OK] dataset version: {metadata['dataset_version']}")

        return 0

    except Exception as exc:
        print(f"[FAIL] import failed: {exc}")
        return 1

    finally:
        client.close()


if __name__ == "__main__":
    sys.exit(main())