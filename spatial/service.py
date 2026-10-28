"""八项功能对应的 MongoDB 操作。

最近的车只查 bike_latest。历史轨迹在时间序列 bike_reports。
热力读 15 分钟网格汇总，跳变读写入时判定好的 bike_anomalies。
"""

from datetime import datetime, timedelta, timezone
from typing import Any

from pymongo import ASCENDING, MongoClient, ReturnDocument

from spatial import geo
from spatial.serialize import public_document

DATASET_ID = "seed-v1"


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def dataset_document(database) -> dict:
    return database["dataset_metadata"].find_one({"_id": DATASET_ID}) or {}


def as_of(database) -> datetime:
    """查询里的“现在”默认取种子数据的最后一条上报，而不是墙钟。"""
    document = dataset_document(database)
    stamp = document.get("simulation_end")
    if isinstance(stamp, datetime):
        if stamp.tzinfo is None:
            return stamp.replace(tzinfo=timezone.utc)
        return stamp.astimezone(timezone.utc)
    latest = database["bike_latest"].find_one(sort=[("last_report_at", -1)])
    if latest and isinstance(latest.get("last_report_at"), datetime):
        stamp = latest["last_report_at"]
        if stamp.tzinfo is None:
            return stamp.replace(tzinfo=timezone.utc)
        return stamp.astimezone(timezone.utc)
    return utc_now()


def _with_distance_band(document: dict) -> dict:
    item = public_document(document)
    distance = round(float(item.get("distance_m") or 0), 2)
    accuracy = float(item.get("accuracy_meters") or 0)
    item["distance_m"] = distance
    item["distance_min_m"] = round(max(0.0, distance - accuracy), 2)
    item["distance_max_m"] = round(distance + accuracy, 2)
    return item


def nearby_facilities(
    database,
    longitude: float,
    latitude: float,
    radius_m: float = 500,
    facility_type: str | None = None,
    status: str | None = None,
    limit: int = 10,
) -> dict[str, Any]:
    query: dict[str, Any] = {}
    if facility_type:
        query["type"] = facility_type
    if status:
        query["status"] = status

    pipeline = [
        {
            "$geoNear": {
                "near": geo.geo_point(longitude, latitude, ndigits=7),
                "key": "location",
                "distanceField": "distance_m",
                "maxDistance": float(radius_m),
                "spherical": True,
                "query": query,
            }
        },
        {"$limit": int(limit)},
    ]
    items = [
        _with_distance_band(document)
        for document in database["facilities"].aggregate(pipeline)
    ]
    return {
        "center": geo.geo_point(longitude, latitude),
        "radius_m": radius_m,
        "facility_type": facility_type,
        "status": status,
        "count": len(items),
        "items": items,
        "distance_note": geo.DISTANCE_NOTE,
    }


def facilities_within(
    database,
    polygon: dict,
    facility_type: str | None = None,
    status: str | None = None,
    page: int = 1,
    page_size: int = 50,
) -> dict[str, Any]:
    geometry = geo.ensure_polygon(polygon)
    query: dict[str, Any] = {
        "location": {"$geoWithin": {"$geometry": geometry}},
    }
    if facility_type:
        query["type"] = facility_type
    if status:
        query["status"] = status

    total = database["facilities"].count_documents(query)
    skip = (page - 1) * page_size
    documents = (
        database["facilities"]
        .find(query)
        .sort("_id", ASCENDING)
        .skip(skip)
        .limit(page_size)
    )
    items = [public_document(document) for document in documents]
    total_pages = (total + page_size - 1) // page_size if page_size else 0
    return {
        "polygon": geometry,
        "page": page,
        "page_size": page_size,
        "total": total,
        "total_pages": total_pages,
        "count": len(items),
        "items": items,
    }


def buildings_containing(database, longitude: float, latitude: float) -> dict[str, Any]:
    documents = list(
        database["buildings"].find(
            {
                "boundary": {
                    "$geoIntersects": {
                        "$geometry": geo.geo_point(longitude, latitude),
                    }
                }
            },
            {"coverage_300m": 0},
        )
    )
    return {
        "point": {"lon": longitude, "lat": latitude},
        "count": len(documents),
        "items": [public_document(document) for document in documents],
    }


def _coverage_counts(database, geometry: dict) -> dict[str, int]:
    rows = database["facilities"].aggregate(
        [
            {"$match": {"location": {"$geoWithin": {"$geometry": geometry}}}},
            {"$group": {"_id": "$type", "count": {"$sum": 1}}},
        ]
    )
    return {row["_id"]: row["count"] for row in rows}


def coverage_for_building(database, building_id: str) -> dict[str, Any] | None:
    building = database["buildings"].find_one(
        {"_id": building_id},
        {
            "_id": 1,
            "name": 1,
            "building_type": 1,
            "center": 1,
            "coverage_300m": 1,
            "coverage_buffer_distance_m": 1,
        },
    )
    if building is None:
        return None
    geometry = building.get("coverage_300m")
    if geometry is None:
        raise ValueError("楼宇缓冲区尚未生成，请先运行 scripts/build_building_buffers.py")
    counts = _coverage_counts(database, geometry)
    return {
        "building_id": building_id,
        "building_name": building.get("name"),
        "building_type": building.get("building_type"),
        "center": building.get("center"),
        "radius_m": 300,
        "coverage_mode": "building_boundary_buffer",
        "coverage_300m": geometry,
        "category_count": len(counts),
        "facility_count": sum(counts.values()),
        "facility_count_by_type": counts,
    }


def coverage_all(database) -> dict[str, Any]:
    missing = database["buildings"].count_documents(
        {"coverage_300m": {"$exists": False}}
    )
    if missing:
        raise ValueError("还有楼宇没有 300 米缓冲区，请先运行 scripts/build_building_buffers.py")

    from concurrent.futures import ThreadPoolExecutor

    buildings = list(
        database["buildings"].find(
            {},
            {"name": 1, "building_type": 1, "coverage_300m": 1},
        )
    )

    def one(building: dict) -> dict:
        counts = _coverage_counts(database, building["coverage_300m"])
        return {
            "building_id": building["_id"],
            "name": building.get("name"),
            "building_type": building.get("building_type"),
            "category_count": len(counts),
            "total": sum(counts.values()),
            "counts": counts,
        }

    with ThreadPoolExecutor(max_workers=8) as pool:
        items = list(pool.map(one, buildings))
    items.sort(key=lambda item: item["building_id"])
    return {
        "radius_m": 300,
        "building_count": len(items),
        "items": items,
    }


def heatmap(
    database,
    start: datetime,
    end: datetime,
    limit: int = 5000,
) -> dict[str, Any]:
    if start >= end:
        raise ValueError("开始时间必须早于结束时间")
    pipeline = [
        {
            "$match": {
                "window_end": {"$gt": start},
                "window_start": {"$lt": end},
            }
        },
        {
            "$group": {
                "_id": "$grid_id",
                "grid_x": {"$first": "$grid_x"},
                "grid_y": {"$first": "$grid_y"},
                "center": {"$first": "$center"},
                "report_count": {"$sum": "$report_count"},
                "bike_count_peak": {"$max": "$bike_count"},
            }
        },
        {"$sort": {"report_count": -1}},
        {"$limit": int(limit)},
    ]
    items = []
    for row in database["heatmap_aggregates"].aggregate(pipeline):
        items.append(
            {
                "grid_id": row["_id"],
                "grid_x": row.get("grid_x"),
                "grid_y": row.get("grid_y"),
                "center": row.get("center"),
                "report_count": row.get("report_count", 0),
                "bike_count_peak": row.get("bike_count_peak", 0),
            }
        )
    report_total = sum(item["report_count"] for item in items)
    return {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "grid_size_m": geo.GRID_SIZE_M,
        "bucket_minutes": geo.BUCKET_MINUTES,
        "grid_reason": geo.GRID_REASON,
        "cell_count": len(items),
        "report_count": report_total,
        "truncated": len(items) >= limit,
        "items": items,
    }


def anomalies(
    database,
    start: datetime,
    end: datetime,
    limit: int = 1000,
) -> dict[str, Any]:
    if start >= end:
        raise ValueError("开始时间必须早于结束时间")
    documents = (
        database["bike_anomalies"]
        .find(
            {
                "anomaly_type": "jump",
                "timestamp": {"$gte": start, "$lte": end},
            }
        )
        .sort("timestamp", ASCENDING)
        .limit(int(limit))
    )
    items = [public_document(document) for document in documents]
    return {
        "start": start.isoformat(),
        "end": end.isoformat(),
        "threshold_m": geo.JUMP_DISTANCE_M,
        "count": len(items),
        "items": items,
    }


def recompute_jumps(database, start: datetime, end: datetime) -> dict[str, Any]:
    """用原始上报重算窗口内的跳变，用来核对写入时的判定。"""
    scan_start = start - timedelta(seconds=geo.MAX_JUMP_GAP_S)
    cursor = database["bike_reports"].find(
        {"timestamp": {"$gte": scan_start, "$lte": end}},
        {
            "_id": 0,
            "timestamp": 1,
            "meta.bike_id": 1,
            "location.coordinates": 1,
        },
    )
    grouped: dict[str, list] = {}
    scanned = 0
    for document in cursor:
        scanned += 1
        bike_id = document.get("meta", {}).get("bike_id")
        coordinates = document.get("location", {}).get("coordinates")
        stamp = document.get("timestamp")
        if not bike_id or not coordinates or stamp is None:
            continue
        grouped.setdefault(bike_id, []).append((stamp, coordinates))

    found = []
    for bike_id, points in grouped.items():
        points.sort(key=lambda item: item[0])
        for index in range(1, len(points)):
            previous_ts, previous_xy = points[index - 1]
            current_ts, current_xy = points[index]
            if current_ts < start or current_ts > end:
                continue
            gap = (current_ts - previous_ts).total_seconds()
            distance = geo.haversine(
                previous_xy[0],
                previous_xy[1],
                current_xy[0],
                current_xy[1],
            )
            if geo.is_jump(distance, gap):
                found.append(
                    {
                        "bike_id": bike_id,
                        "timestamp": current_ts,
                        "distance_m": round(distance, 2),
                        "gap_seconds": gap,
                    }
                )
    found.sort(key=lambda item: (item["timestamp"], item["bike_id"]))
    return {"scanned": scanned, "count": len(found), "items": found}


def zombies(database, limit: int = 500) -> dict[str, Any]:
    documents = (
        database["bike_latest"]
        .find({"displacement_m": {"$lt": geo.ZOMBIE_DISPLACEMENT_M}})
        .sort("displacement_m", ASCENDING)
        .limit(int(limit))
    )
    items = [public_document(document) for document in documents]
    return {
        "threshold_m": geo.ZOMBIE_DISPLACEMENT_M,
        "count": len(items),
        "items": items,
    }


def update_facility_status(database, facility_id: str, status: str) -> dict | None:
    if status not in geo.STATUS_LABELS:
        raise ValueError("状态只能是 active、disabled 或 occupied")
    document = database["facilities"].find_one_and_update(
        {"_id": facility_id},
        {"$set": {"status": status, "updated_at": utc_now()}},
        return_document=ReturnDocument.AFTER,
    )
    return public_document(document)


def read_facility_fresh(facility_id: str) -> dict | None:
    """新开一个客户端读，避免和刚才的写入共用连接缓存。"""
    from spatial.db import mongo_settings

    settings = mongo_settings()
    client = MongoClient(
        host=settings["host"],
        port=settings["port"],
        username=settings["username"],
        password=settings["password"],
        authSource="admin",
        serverSelectionTimeoutMS=8000,
        appname="campus-spatial-fresh-read",
        tz_aware=True,
    )
    try:
        document = client[settings["database"]]["facilities"].find_one(
            {"_id": facility_id}
        )
        return public_document(document)
    finally:
        client.close()


def nearby_bikes(
    database,
    longitude: float,
    latitude: float,
    radius_m: float = 500,
    limit: int = 20,
) -> dict[str, Any]:
    pipeline = [
        {
            "$geoNear": {
                "near": geo.geo_point(longitude, latitude),
                "key": "location",
                "distanceField": "distance_m",
                "maxDistance": float(radius_m),
                "spherical": True,
            }
        },
        {"$limit": int(limit)},
    ]
    items = []
    for document in database["bike_latest"].aggregate(pipeline):
        item = public_document(document)
        item["distance_m"] = round(float(item.get("distance_m") or 0), 2)
        items.append(item)
    return {
        "center": geo.geo_point(longitude, latitude),
        "radius_m": radius_m,
        "count": len(items),
        "source": "bike_latest",
        "items": items,
    }


def bike_track(
    database,
    bike_id: str,
    start: datetime,
    end: datetime,
    limit: int = 2000,
) -> dict[str, Any]:
    documents = (
        database["bike_reports"]
        .find(
            {
                "meta.bike_id": bike_id,
                "timestamp": {"$gte": start, "$lte": end},
            },
            {"_id": 0, "timestamp": 1, "location": 1, "speed_mps": 1, "meta": 1},
        )
        .sort("timestamp", ASCENDING)
        .limit(int(limit))
    )
    items = []
    for document in documents:
        items.append(
            {
                "bike_id": document.get("meta", {}).get("bike_id", bike_id),
                "timestamp": document["timestamp"].isoformat(),
                "location": document.get("location"),
                "speed_mps": document.get("speed_mps"),
            }
        )
    return {
        "bike_id": bike_id,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "count": len(items),
        "items": items,
    }


def _touch_heatmap(database, bike_id: str, longitude: float, latitude: float, stamp: datetime) -> None:
    window_start = geo.floor_bucket(stamp)
    grid_x, grid_y = geo.grid_index(longitude, latitude)
    center_lon, center_lat = geo.grid_center(grid_x, grid_y)
    document_id = geo.heatmap_document_id(window_start, grid_x, grid_y)
    database["heatmap_aggregates"].update_one(
        {"_id": document_id},
        {
            "$inc": {"report_count": 1},
            "$setOnInsert": {
                "window_start": window_start,
                "window_end": geo.bucket_end(window_start),
                "grid_size_m": geo.GRID_SIZE_M,
                "grid_x": grid_x,
                "grid_y": grid_y,
                "grid_id": geo.grid_id(grid_x, grid_y),
                "bike_count": 1,
            },
            "$set": {
                "center": geo.geo_point(center_lon, center_lat),
            },
        },
        upsert=True,
    )


def ingest_bike_report(
    database,
    bike_id: str,
    longitude: float,
    latitude: float,
    stamp: datetime | None = None,
    speed_mps: float | None = None,
    source: str = "api",
) -> dict[str, Any]:
    """单条上报：写时间序列、更新最新位置，跳变当时判定。"""
    if not bike_id.strip():
        raise ValueError("bike_id 不能为空")
    stamp = stamp or utc_now()
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    else:
        stamp = stamp.astimezone(timezone.utc)

    previous = database["bike_latest"].find_one({"_id": bike_id})
    anomaly = None
    if previous and previous.get("location") and previous.get("last_report_at"):
        previous_xy = previous["location"]["coordinates"]
        previous_ts = previous["last_report_at"]
        if previous_ts.tzinfo is None:
            previous_ts = previous_ts.replace(tzinfo=timezone.utc)
        gap = (stamp - previous_ts).total_seconds()
        distance = geo.haversine(previous_xy[0], previous_xy[1], longitude, latitude)
        if geo.is_jump(distance, gap):
            anomaly = {
                "_id": f"{bike_id}|{stamp.isoformat()}",
                "bike_id": bike_id,
                "timestamp": stamp,
                "anomaly_type": "jump",
                "distance_m": round(distance, 2),
                "gap_seconds": gap,
                "implied_speed_kmh": round(distance / gap * 3.6, 2),
                "from_location": previous["location"],
                "to_location": geo.geo_point(longitude, latitude),
                "source": source,
            }
            database["bike_anomalies"].replace_one(
                {"_id": anomaly["_id"]},
                anomaly,
                upsert=True,
            )

    report = {
        "timestamp": stamp,
        "meta": {"bike_id": bike_id},
        "location": geo.geo_point(longitude, latitude),
        "speed_mps": speed_mps,
        "source": source,
    }
    database["bike_reports"].insert_one(report)

    origin = previous.get("origin") if previous else geo.geo_point(longitude, latitude)
    origin_xy = origin["coordinates"]
    displacement = geo.haversine(origin_xy[0], origin_xy[1], longitude, latitude)
    if previous:
        displacement = max(float(previous.get("displacement_m") or 0), displacement)
    status = "zombie" if displacement < geo.ZOMBIE_DISPLACEMENT_M else "active"
    latest = {
        "_id": bike_id,
        "bike_id": bike_id,
        "location": geo.geo_point(longitude, latitude),
        "last_report_at": stamp,
        "timestamp": stamp,
        "speed_mps": speed_mps,
        "origin": origin,
        "displacement_m": round(displacement, 2),
        "status": status,
        "source": source,
    }
    database["bike_latest"].replace_one({"_id": bike_id}, latest, upsert=True)
    database["bikes"].update_one(
        {"_id": bike_id},
        {
            "$set": {
                "last_report_at": stamp,
                "displacement_m": latest["displacement_m"],
                "status": status,
            },
            "$inc": {"report_count": 1},
        },
        upsert=True,
    )
    _touch_heatmap(database, bike_id, longitude, latitude, stamp)
    return {
        "report": public_document(report),
        "latest": public_document(latest),
        "anomaly": public_document(anomaly),
    }


def meta(database) -> dict[str, Any]:
    document = dataset_document(database)
    return {
        "service": "校园服务设施空间查询",
        "campus": geo.campus_polygon(),
        "sample_polygon": geo.campus_quarter_polygon(),
        "center": {"lon": geo.CENTER_LON, "lat": geo.CENTER_LAT},
        "bounds": {
            "min_lon": geo.MIN_LON,
            "min_lat": geo.MIN_LAT,
            "max_lon": geo.MAX_LON,
            "max_lat": geo.MAX_LAT,
        },
        "facility_types": geo.TYPE_LABELS,
        "statuses": geo.STATUS_LABELS,
        "grid_size_m": geo.GRID_SIZE_M,
        "bucket_minutes": geo.BUCKET_MINUTES,
        "grid_reason": geo.GRID_REASON,
        "jump_distance_m": geo.JUMP_DISTANCE_M,
        "zombie_displacement_m": geo.ZOMBIE_DISPLACEMENT_M,
        "distance_note": geo.DISTANCE_NOTE,
        "dataset": public_document(document),
    }
