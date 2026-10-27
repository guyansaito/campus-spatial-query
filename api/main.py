import os
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from pymongo import GEOSPHERE, MongoClient
from pydantic import BaseModel, Field


load_dotenv()

app = FastAPI(
    title="Campus Spatial Query API",
    version="0.1.0",
)

_client: MongoClient | None = None


class PolygonQuery(BaseModel):
    polygon: dict[str, Any]
    facility_type: str | None = None
    limit: int = Field(default=1000, ge=1, le=5000)


def get_database():
    global _client

    if _client is None:
        _client = MongoClient(
            host="127.0.0.1",
            port=int(os.getenv("MONGO_PORT", "27017")),
            username=os.getenv("MONGO_ROOT_USERNAME"),
            password=os.getenv("MONGO_ROOT_PASSWORD"),
            authSource="admin",
            serverSelectionTimeoutMS=5000,
            appname="campus-spatial-api",
        )

    return _client[os.getenv("MONGO_DATABASE", "campus_service")]


def point_geometry(lon: float, lat: float) -> dict[str, Any]:
    return {
        "type": "Point",
        "coordinates": [lon, lat],
    }


def validate_coordinates(lon: float, lat: float) -> None:
    if not -180 <= lon <= 180:
        raise HTTPException(status_code=400, detail="经度必须位于 [-180, 180]")
    if not -90 <= lat <= 90:
        raise HTTPException(status_code=400, detail="纬度必须位于 [-90, 90]")


def serialize_document(document: dict[str, Any]) -> dict[str, Any]:
    document["_id"] = str(document["_id"])
    return document


@app.get("/health")
def health() -> dict[str, str]:
    database = get_database()
    database.client.admin.command("ping")
    return {"status": "ok", "database": "mongodb"}


@app.get("/facilities/nearby")
def nearby_facilities(
    lon: float = Query(..., description="经度"),
    lat: float = Query(..., description="纬度"),
    radius_m: float = Query(300, gt=0, le=10000),
    facility_type: str | None = Query(None),
    limit: int = Query(100, ge=1, le=1000),
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
        "items": [serialize_document(item) for item in documents],
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
        "items": [serialize_document(item) for item in documents],
    }


@app.get("/buildings/contains")
def buildings_contains(
    lon: float = Query(...),
    lat: float = Query(...),
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
        "items": [serialize_document(item) for item in documents],
    }


@app.get("/buildings/{building_id}/coverage")
def building_coverage(
    building_id: str,
    radius_m: float = Query(300, gt=0, le=300),
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
        raise HTTPException(status_code=404, detail="楼宇不存在")

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
                {"$group": {"_id": "$type", "count": {"$sum": 1}}},
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
            item["_id"]: item["count"] for item in type_counts
        },
    }   