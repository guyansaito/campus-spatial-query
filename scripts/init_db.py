import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from pymongo import ASCENDING, DESCENDING, GEOSPHERE, MongoClient
from pymongo.errors import CollectionInvalid, PyMongoError


PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")


COLLECTIONS = [
    "facilities",
    "buildings",
    "bikes",
    "bike_latest",
    "bike_reports",
    "bike_anomalies",
    "heatmap_aggregates",
    "dataset_metadata",
]


def get_client() -> MongoClient:
    username = os.getenv("MONGO_ROOT_USERNAME")
    password = os.getenv("MONGO_ROOT_PASSWORD")
    port = int(os.getenv("MONGO_PORT", "27017"))

    return MongoClient(
        host="127.0.0.1",
        port=port,
        username=username,
        password=password,
        authSource="admin",
        serverSelectionTimeoutMS=5000,
        appname="campus-db-initializer",
    )


def ensure_collections(database) -> None:
    existing = set(database.list_collection_names())

    for name in COLLECTIONS:
        if name not in existing:
            database.create_collection(name)
            print(f"[CREATE] collection: {name}")
        else:
            print(f"[EXISTS] collection: {name}")


def ensure_indexes(database) -> None:
    facilities = database["facilities"]
    buildings = database["buildings"]
    bikes = database["bikes"]
    bike_latest = database["bike_latest"]
    bike_reports = database["bike_reports"]
    bike_anomalies = database["bike_anomalies"]
    heatmap_aggregates = database["heatmap_aggregates"]
    dataset_metadata = database["dataset_metadata"]

    index_tasks = [
        (
            facilities,
            [
                ([("location", GEOSPHERE)], {"name": "idx_facilities_location"}),
                (
                    [
                        ("type", ASCENDING),
                        ("status", ASCENDING),
                        ("location", GEOSPHERE),
                    ],
                    {"name": "idx_facilities_type_status_location"},
                ),
                (
                    [("building_id", ASCENDING)],
                    {"name": "idx_facilities_building_id"},
                ),
            ],
        ),
        (
            buildings,
            [
                (
                    [("boundary", GEOSPHERE)],
                    {"name": "idx_buildings_boundary"},
                ),
                (
                    [("center", GEOSPHERE)],
                    {"name": "idx_buildings_center"},
                ),
            ],
        ),
        (
            bikes,
            [
                (
                    [("last_report_at", DESCENDING)],
                    {"name": "idx_bikes_last_report_at"},
                ),
            ],
        ),
        (
            bike_latest,
            [
                (
                    [("location", GEOSPHERE)],
                    {"name": "idx_bike_latest_location"},
                ),
                (
                    [("last_report_at", DESCENDING)],
                    {"name": "idx_bike_latest_last_report_at"},
                ),
                (
                    [("status", ASCENDING)],
                    {"name": "idx_bike_latest_status"},
                ),
            ],
        ),
        (
            bike_reports,
            [
                (
                    [
                        ("bike_id", ASCENDING),
                        ("timestamp", ASCENDING),
                    ],
                    {"name": "idx_bike_reports_bike_time"},
                ),
                (
                    [("timestamp", DESCENDING)],
                    {"name": "idx_bike_reports_timestamp"},
                ),
            ],
        ),
        (
            bike_anomalies,
            [
                (
                    [("timestamp", DESCENDING)],
                    {"name": "idx_bike_anomalies_timestamp"},
                ),
                (
                    [
                        ("bike_id", ASCENDING),
                        ("timestamp", DESCENDING),
                    ],
                    {"name": "idx_bike_anomalies_bike_time"},
                ),
                (
                    [("anomaly_type", ASCENDING)],
                    {"name": "idx_bike_anomalies_type"},
                ),
            ],
        ),
        (
            heatmap_aggregates,
            [
                (
                    [
                        ("window_start", ASCENDING),
                        ("window_end", ASCENDING),
                        ("grid_id", ASCENDING),
                    ],
                    {"name": "idx_heatmap_window_grid", "unique": True},
                ),
            ],
        ),
        (
            dataset_metadata,
            [
                (
                    [("dataset_version", ASCENDING)],
                    {"name": "idx_dataset_version", "unique": True},
                ),
            ],
        ),
    ]

    for collection, indexes in index_tasks:
        for keys, options in indexes:
            collection.create_index(keys, **options)
            print(
                f"[INDEX] {collection.name}.{options['name']}"
            )


def print_summary(database) -> None:
    print()
    print("Collections and indexes:")
    for name in COLLECTIONS:
        collection = database[name]
        index_names = sorted(collection.index_information().keys())
        print(f"- {name}: {', '.join(index_names)}")


def main() -> int:
    database_name = os.getenv("MONGO_DATABASE", "campus_service")

    if not os.getenv("MONGO_ROOT_USERNAME") or not os.getenv(
        "MONGO_ROOT_PASSWORD"
    ):
        print("[FAIL] Missing MongoDB credentials in .env")
        return 1

    client = get_client()

    try:
        client.admin.command("ping")
        database = client[database_name]

        ensure_collections(database)
        ensure_indexes(database)
        print_summary(database)

        print()
        print(f"[OK] Database initialization completed: {database_name}")
        return 0

    except PyMongoError as exc:
        print(f"[FAIL] MongoDB initialization failed: {exc}")
        return 1

    finally:
        client.close()


if __name__ == "__main__":
    sys.exit(main())