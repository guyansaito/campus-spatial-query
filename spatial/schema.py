"""集合和索引。

1700 万条位置不上 2dsphere。最新位置在 bike_latest（约 2000 条），
历史上报在时间序列 bike_reports，热力和跳变分别落到汇总表。
"""

from pymongo import ASCENDING, DESCENDING, GEOSPHERE
from pymongo.errors import PyMongoError

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

MOVEMENT_COLLECTIONS = [
    "bikes",
    "bike_latest",
    "bike_reports",
    "bike_anomalies",
    "heatmap_aggregates",
    "vehicle_tracks",
]

BIKE_REPORTS_TIMESERIES = {
    "timeField": "timestamp",
    "metaField": "meta",
    "granularity": "seconds",
}


def drop_index_if_exists(collection, name: str) -> None:
    if name in collection.index_information():
        collection.drop_index(name)
        print(f"[DROP INDEX] {collection.name}.{name}")


def ensure_bike_reports(database) -> None:
    current = {
        item["name"]: item
        for item in database.list_collections(filter={"name": "bike_reports"})
    }
    if "bike_reports" in current:
        options = current["bike_reports"].get("options") or {}
        if "timeseries" not in options:
            count = database["bike_reports"].estimated_document_count()
            if count != 0:
                raise RuntimeError(
                    "bike_reports 不是时间序列且已有数据，种子脚本不会直接覆盖。"
                )
            database["bike_reports"].drop()
            print("[DROP] non-timeseries bike_reports")

    if "bike_reports" not in set(database.list_collection_names()):
        database.create_collection(
            "bike_reports",
            timeseries=BIKE_REPORTS_TIMESERIES,
        )
        print("[CREATE] timeseries bike_reports")
    else:
        print("[EXISTS] timeseries bike_reports")


def ensure_collections(database) -> None:
    existing = set(database.list_collection_names())
    for name in COLLECTIONS:
        if name == "bike_reports":
            continue
        if name not in existing:
            database.create_collection(name)
            print(f"[CREATE] collection: {name}")
        else:
            print(f"[EXISTS] collection: {name}")
    ensure_bike_reports(database)


def ensure_indexes(database) -> None:
    facilities = database["facilities"]
    buildings = database["buildings"]
    bikes = database["bikes"]
    bike_latest = database["bike_latest"]
    bike_reports = database["bike_reports"]
    bike_anomalies = database["bike_anomalies"]
    heatmap_aggregates = database["heatmap_aggregates"]
    dataset_metadata = database["dataset_metadata"]

    # 两个 2dsphere 会让 $geoNear 无法选择索引，过滤条件改走普通复合索引。
    drop_index_if_exists(facilities, "idx_facilities_type_status_location")

    index_tasks = [
        (
            facilities,
            [
                ([("location", GEOSPHERE)], {"name": "idx_facilities_location"}),
                (
                    [("type", ASCENDING), ("status", ASCENDING)],
                    {"name": "idx_facilities_type_status"},
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
                ([("boundary", GEOSPHERE)], {"name": "idx_buildings_boundary"}),
                ([("center", GEOSPHERE)], {"name": "idx_buildings_center"}),
                (
                    [("coverage_300m", GEOSPHERE)],
                    {"name": "idx_buildings_coverage_300m"},
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
                ([("status", ASCENDING)], {"name": "idx_bike_latest_status"}),
                (
                    [("displacement_m", ASCENDING)],
                    {"name": "idx_bike_latest_displacement"},
                ),
            ],
        ),
        (
            bike_reports,
            [
                (
                    [("meta.bike_id", ASCENDING), ("timestamp", ASCENDING)],
                    {"name": "idx_bike_reports_bike_time"},
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
                    [("bike_id", ASCENDING), ("timestamp", DESCENDING)],
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
            try:
                collection.create_index(keys, **options)
            except PyMongoError as exc:
                raise RuntimeError(
                    f"创建索引失败 {collection.name}.{options['name']}: {exc}"
                ) from exc
            print(f"[INDEX] {collection.name}.{options['name']}")


def print_summary(database) -> None:
    print()
    print("Collections and indexes:")
    for name in COLLECTIONS:
        collection = database[name]
        index_names = sorted(collection.index_information().keys())
        print(f"- {name}: {', '.join(index_names)}")


def reset_movement_data(database) -> None:
    """清掉车辆明细和汇总。不碰楼宇和设施。"""
    existing = set(database.list_collection_names())
    for name in MOVEMENT_COLLECTIONS:
        if name in existing:
            database[name].drop()
            print(f"[DROP] {name}")
    ensure_collections(database)
    ensure_indexes(database)
