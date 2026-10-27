
import os
import math
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel, Field
from pymongo import MongoClient, ASCENDING, DESCENDING

load_dotenv()

app = FastAPI(
    title="Campus Spatial Query API",
    version="0.1.0",
)

# ==================== MongoDB 配置 ====================

MONGO_URI = os.getenv(
    "MONGO_URI",
    "mongodb://campus_admin:CampusDev_2026_ChangeMe@127.0.0.1:27017/"
    "?authSource=admin",
)

MONGO_DB = os.getenv(
    "MONGO_DATABASE",
    os.getenv("MONGO_DB", "campus_service"),
)

_client: MongoClient | None = None


def get_database():
    global _client

    if _client is None:
        _client = MongoClient(
            MONGO_URI,
            serverSelectionTimeoutMS=5000,
            appname="campus-spatial-api",
        )

    return _client[MONGO_DB]


# ==================== 数据集合 ====================

def get_collections():
    database = get_database()

    return (
        database,
        database["buildings"],
        database["facilities"],
        database["vehicle_tracks"],
    )


# ==================== 数据模型 ====================

class PolygonQuery(BaseModel):
    polygon: dict[str, Any]
    facility_type: str | None = None
    limit: int = Field(default=1000, ge=1, le=5000)


class Point(BaseModel):
    type: str = Field(default="Point", pattern="^Point$")
    coordinates: list[float] = Field(min_length=2, max_length=2)


class VehicleTrackCreate(BaseModel):
    timestamp: Optional[datetime] = None
    location: Point
    speed_kmh: Optional[float] = Field(default=None, ge=0)
    heading_degrees: Optional[float] = Field(default=None, ge=0, le=360)
    status: Optional[str] = None
    source: Optional[str] = "api"


# ==================== 公共辅助函数 ====================

def point_geometry(lon: float, lat: float) -> dict[str, Any]:
    return {
        "type": "Point",
        "coordinates": [lon, lat],
    }


def validate_coordinates(lon: float, lat: float) -> None:
    if not -180 <= lon <= 180:
        raise HTTPException(
            status_code=400,
            detail="经度必须位于 [-180, 180]",
        )

    if not -90 <= lat <= 90:
        raise HTTPException(
            status_code=400,
            detail="纬度必须位于 [-90, 90]",
        )


def serialize_document(document: dict | None) -> dict | None:
    if document is None:
        return None

    result = dict(document)

    if "_id" in result:
        result["_id"] = str(result["_id"])

    for key, value in result.items():
        if isinstance(value, datetime):
            result[key] = value.isoformat()

    return result


def normalize_timestamp(value: Optional[datetime]) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)

    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)

    return value.astimezone(timezone.utc)


def calculate_distance_meters(
    longitude_1: float,
    latitude_1: float,
    longitude_2: float,
    latitude_2: float,
) -> float:
    earth_radius_m = 6371008.8

    lon_1 = math.radians(longitude_1)
    lat_1 = math.radians(latitude_1)
    lon_2 = math.radians(longitude_2)
    lat_2 = math.radians(latitude_2)

    delta_lon = lon_2 - lon_1
    delta_lat = lat_2 - lat_1

    value = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat_1)
        * math.cos(lat_2)
        * math.sin(delta_lon / 2) ** 2
    )

    # 防止浮点数误差导致 asin 参数超出 [0, 1]
    value = max(0.0, min(1.0, value))

    return 2 * earth_radius_m * math.asin(math.sqrt(value))


# ==================== 健康检查 ====================

@app.get("/health")
def health() -> dict[str, str]:
    database = get_database()
    database.client.admin.command("ping")

    return {
        "status": "ok",
        "database": MONGO_DB,
    }


# ==================== 设施空间查询 ====================

@app.get("/facilities/nearby")
def nearby_facilities(
    lon: float = Query(..., description="经度"),
    lat: float = Query(..., description="纬度"),
    radius_m: float = Query(default=300, gt=0, le=10000),
    facility_type: str | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=1000),
) -> dict[str, Any]:
    validate_coordinates(lon, lat)

    query: dict[str, Any] = {
        "location": {
            "$near": {
                "$geometry": point_geometry(lon, lat),
                "$maxDistance": radius_m,
            }
        }
    }

    if facility_type:
        query["type"] = facility_type

    database = get_database()

    documents = list(
        database["facilities"]
        .find(query)
        .limit(limit)
    )

    return {
        "center": {"lon": lon, "lat": lat},
        "radius_m": radius_m,
        "count": len(documents),
        "items": [
            serialize_document(item) for item in documents
        ],
    }


@app.post("/facilities/within")
def facilities_within(body: PolygonQuery) -> dict[str, Any]:
    polygon = body.polygon

    if polygon.get("type") != "Polygon":
        raise HTTPException(
            status_code=400,
            detail="polygon.type 必须为 Polygon",
        )

    coordinates = polygon.get("coordinates")

    if not coordinates or not isinstance(coordinates, list):
        raise HTTPException(
            status_code=400,
            detail="polygon.coordinates 格式无效",
        )

    query: dict[str, Any] = {
        "location": {
            "$geoWithin": {
                "$geometry": polygon,
            }
        }
    }

    if body.facility_type:
        query["type"] = body.facility_type

    database = get_database()

    documents = list(
        database["facilities"]
        .find(query)
        .limit(body.limit)
    )

    return {
        "polygon": polygon,
        "count": len(documents),
        "limited": len(documents) >= body.limit,
        "items": [
            serialize_document(item) for item in documents
        ],
    }


# ==================== 楼宇空间查询 ====================

@app.get("/buildings/contains")
def buildings_contains(
    lon: float = Query(..., description="经度"),
    lat: float = Query(..., description="纬度"),
) -> dict[str, Any]:
    validate_coordinates(lon, lat)

    database = get_database()

    documents = list(
        database["buildings"].find(
            {
                "boundary": {
                    "$geoIntersects": {
                        "$geometry": point_geometry(lon, lat),
                    }
                }
            }
        )
    )

    return {
        "point": {"lon": lon, "lat": lat},
        "count": len(documents),
        "items": [
            serialize_document(item) for item in documents
        ],
    }


@app.get("/buildings/{building_id}/coverage")
def building_coverage(
    building_id: str,
    radius_m: float = Query(default=300, gt=0, le=300),
) -> dict[str, Any]:
    database = get_database()

    building = database["buildings"].find_one(
        {"_id": building_id},
        {
            "_id": 1,
            "name": 1,
            "center": 1,
            "coverage_300m": 1,
            "coverage_buffer_distance_m": 1,
        },
    )

    if building is None:
        raise HTTPException(
            status_code=404,
            detail="楼宇不存在",
        )

    if radius_m != 300:
        raise HTTPException(
            status_code=400,
            detail="当前仅支持 300 米楼宇边界缓冲区",
        )

    coverage_geometry = building.get("coverage_300m")

    if coverage_geometry is None:
        raise HTTPException(
            status_code=500,
            detail="楼宇缓冲区尚未生成",
        )

    base_query = {
        "location": {
            "$geoWithin": {
                "$geometry": coverage_geometry,
            }
        }
    }

    total = database["facilities"].count_documents(base_query)

    type_counts = list(
        database["facilities"].aggregate(
            [
                {"$match": base_query},
                {
                    "$group": {
                        "_id": "$type",
                        "count": {"$sum": 1},
                    }
                },
                {"$sort": {"_id": 1}},
            ]
        )
    )

    return {
        "building_id": building_id,
        "building_name": building.get("name"),
        "center": building.get("center"),
        "radius_m": 300,
        "coverage_mode": "building_boundary_buffer",
        "facility_count": total,
        "facility_count_by_type": {
            item["_id"]: item["count"]
            for item in type_counts
        },
    }


# ==================== 车辆轨迹管理 ====================

@app.post("/vehicles/{vehicle_id}/tracks", status_code=201)
def create_vehicle_track(
    vehicle_id: str,
    payload: VehicleTrackCreate,
):
    if not vehicle_id.strip():
        raise HTTPException(
            status_code=400,
            detail="vehicle_id is required",
        )

    longitude, latitude = payload.location.coordinates
    validate_coordinates(longitude, latitude)

    timestamp = normalize_timestamp(payload.timestamp)

    document = {
        "vehicle_id": vehicle_id,
        "timestamp": timestamp,
        "location": payload.location.model_dump(),
        "source": payload.source,
    }

    if payload.speed_kmh is not None:
        document["speed_kmh"] = payload.speed_kmh

    if payload.heading_degrees is not None:
        document["heading_degrees"] = payload.heading_degrees

    if payload.status is not None:
        document["status"] = payload.status

    database = get_database()
    result = database["vehicle_tracks"].insert_one(document)

    document["_id"] = result.inserted_id

    return serialize_document(document)


@app.get("/vehicles/{vehicle_id}/tracks")
def get_vehicle_tracks(
    vehicle_id: str,
    start_time: Optional[datetime] = Query(default=None),
    end_time: Optional[datetime] = Query(default=None),
    limit: int = Query(default=100, ge=1, le=5000),
):
    now = datetime.now(timezone.utc)

    start = (
        normalize_timestamp(start_time)
        if start_time is not None
        else now - timedelta(hours=1)
    )

    end = (
        normalize_timestamp(end_time)
        if end_time is not None
        else now
    )

    if start > end:
        raise HTTPException(
            status_code=400,
            detail="start_time must be earlier than end_time",
        )

    database = get_database()

    documents = (
        database["vehicle_tracks"]
        .find(
            {
                "vehicle_id": vehicle_id,
                "timestamp": {
                    "$gte": start,
                    "$lte": end,
                },
            }
        )
        .sort("timestamp", DESCENDING)
        .limit(limit)
    )

    return {
        "vehicle_id": vehicle_id,
        "start_time": start.isoformat(),
        "end_time": end.isoformat(),
        "items": [
            serialize_document(item) for item in documents
        ],
    }


# ==================== 附近车辆查询 ====================

@app.get("/vehicles/nearby")
def get_nearby_vehicles(
    longitude: float = Query(..., ge=-180, le=180),
    latitude: float = Query(..., ge=-90, le=90),
    radius_m: float = Query(default=500, gt=0, le=50000),
    minutes: int = Query(default=5, gt=0, le=1440),
):
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=minutes)

    # 地球平均半径，单位：米
    earth_radius_m = 6371008.8
    radius_radians = radius_m / earth_radius_m

    pipeline = [
        {
            "$match": {
                "timestamp": {
                    "$gte": cutoff,
                },
                "location": {
                    "$geoWithin": {
                        "$centerSphere": [
                            [longitude, latitude],
                            radius_radians,
                        ]
                    }
                },
            }
        },
        {
            "$sort": {
                "vehicle_id": ASCENDING,
                "timestamp": DESCENDING,
            }
        },
        {
            "$group": {
                "_id": "$vehicle_id",
                "latest": {"$first": "$$ROOT"},
            }
        },
        {
            "$replaceRoot": {
                "newRoot": "$latest",
            }
        },
    ]

    database = get_database()
    vehicle_tracks = database["vehicle_tracks"]

    items = []

    for document in vehicle_tracks.aggregate(pipeline):
        coordinates = document["location"]["coordinates"]

        vehicle_longitude = float(coordinates[0])
        vehicle_latitude = float(coordinates[1])

        distance_m = calculate_distance_meters(
            longitude,
            latitude,
            vehicle_longitude,
            vehicle_latitude,
        )

        document["distance_m"] = round(distance_m, 2)
        items.append(serialize_document(document))

    items.sort(key=lambda item: item["distance_m"])

    return {
        "center": {
            "type": "Point",
            "coordinates": [longitude, latitude],
        },
        "radius_m": radius_m,
        "within_minutes": minutes,
        "items": items,
    }
