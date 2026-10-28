import time
from datetime import datetime, timedelta, timezone
from typing import Any, Literal, Optional

from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from spatial import geo, service
from spatial.db import get_database
from spatial.serialize import public_document

app = FastAPI(
    title="校园服务设施空间查询",
    version="1.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class Point(BaseModel):
    type: str = Field(default="Point", pattern="^Point$")
    coordinates: list[float] = Field(min_length=2, max_length=2)


class PolygonQuery(BaseModel):
    polygon: dict[str, Any]
    facility_type: str | None = None
    status: str | None = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=50, ge=1, le=200)


class StatusPatch(BaseModel):
    status: Literal["active", "disabled", "occupied"]


class FacilityCreate(BaseModel):
    id: str = Field(min_length=1)
    name: str
    type: str
    location: Point
    status: Literal["active", "disabled", "occupied"] = "active"
    coordinate_accuracy: str = "exact"
    accuracy_meters: float = Field(default=5, ge=0)
    building_id: str | None = None


class BuildingCreate(BaseModel):
    id: str = Field(min_length=1)
    name: str
    building_type: str = "service"
    boundary: dict[str, Any]
    center: Point


class BikeReportCreate(BaseModel):
    timestamp: Optional[datetime] = None
    location: Point
    speed_mps: Optional[float] = Field(default=None, ge=0)
    source: str = "api"


def database():
    return get_database()


def fail(exc: ValueError) -> HTTPException:
    return HTTPException(status_code=400, detail=str(exc))


@app.get("/")
def root() -> dict[str, Any]:
    return {
        "service": "校园服务设施空间查询",
        "docs": "/docs",
        "functions": [
            "POST /facilities 写入设施",
            "POST /buildings 写入楼宇",
            "POST /bikes/{bike_id}/reports 写入车辆上报",
            "GET /facilities/nearby 附近查找",
            "POST /facilities/within 区域检索",
            "GET /buildings/contains 包含判断",
            "GET /coverage 覆盖分析",
            "GET /bikes/heatmap 车辆热力",
            "GET /bikes/anomalies 跳变识别",
            "PATCH /facilities/{facility_id}/status 状态维护",
        ],
    }


@app.get("/health")
def health() -> dict[str, str]:
    db = database()
    db.client.admin.command("ping")
    return {"status": "ok", "database": db.name}


@app.get("/meta")
def read_meta() -> dict[str, Any]:
    return service.meta(database())


@app.get("/buildings")
def get_buildings(
    limit: int = Query(default=100, ge=1, le=1000),
    skip: int = Query(default=0, ge=0),
    building_type: Optional[str] = Query(default=None),
    view: Optional[str] = Query(default=None),
):
    query: dict[str, Any] = {}
    if building_type:
        query["building_type"] = building_type
    projection = None
    if view == "map":
        projection = {
            "name": 1,
            "building_type": 1,
            "boundary": 1,
            "center": 1,
            "vertex_count": 1,
        }
    documents = (
        database()["buildings"]
        .find(query, projection)
        .sort("_id", 1)
        .skip(skip)
        .limit(limit)
    )
    return {
        "skip": skip,
        "limit": limit,
        "items": [public_document(item) for item in documents],
    }


@app.get("/buildings/contains")
def buildings_contains(
    lon: float = Query(..., description="经度"),
    lat: float = Query(..., description="纬度"),
) -> dict[str, Any]:
    _check_coordinates(lon, lat)
    started = time.perf_counter()
    payload = service.buildings_containing(database(), lon, lat)
    payload["elapsed_ms"] = _elapsed(started)
    return payload


@app.get("/buildings/{building_id}")
def get_building(building_id: str):
    document = database()["buildings"].find_one(
        {"_id": building_id},
        {"coverage_300m": 0},
    )
    if document is None:
        raise HTTPException(status_code=404, detail="楼宇不存在")
    return public_document(document)


@app.post("/buildings", status_code=201)
def create_building(body: BuildingCreate):
    try:
        boundary = geo.ensure_polygon(body.boundary)
    except ValueError as exc:
        raise fail(exc) from exc
    _check_coordinates(body.center.coordinates[0], body.center.coordinates[1])
    document = {
        "_id": body.id,
        "name": body.name,
        "building_type": body.building_type,
        "boundary": boundary,
        "center": body.center.model_dump(),
        "vertex_count": len(boundary["coordinates"][0]) - 1,
        "source": "api",
        "data_version": "manual",
    }
    try:
        database()["buildings"].insert_one(document)
    except Exception as exc:
        raise HTTPException(status_code=409, detail=f"楼宇写入失败: {exc}") from exc
    return public_document(document)


@app.get("/buildings/{building_id}/coverage")
def building_coverage(building_id: str):
    started = time.perf_counter()
    try:
        payload = service.coverage_for_building(database(), building_id)
    except ValueError as exc:
        raise fail(exc) from exc
    if payload is None:
        raise HTTPException(status_code=404, detail="楼宇不存在")
    payload["elapsed_ms"] = _elapsed(started)
    return payload


@app.get("/buildings/{building_id}/facilities")
def get_building_facilities(
    building_id: str,
    facility_type: Optional[str] = Query(default=None),
    limit: int = Query(default=1000, ge=1, le=5000),
):
    building = database()["buildings"].find_one(
        {"_id": building_id},
        {"coverage_300m": 1},
    )
    if building is None:
        raise HTTPException(status_code=404, detail="楼宇不存在")
    geometry = building.get("coverage_300m")
    if geometry is None:
        raise HTTPException(status_code=409, detail="楼宇缓冲区尚未生成")
    query: dict[str, Any] = {
        "location": {"$geoWithin": {"$geometry": geometry}},
    }
    if facility_type:
        query["type"] = facility_type
    documents = list(database()["facilities"].find(query).limit(limit))
    return {
        "building_id": building_id,
        "count": len(documents),
        "limited": len(documents) >= limit,
        "items": [public_document(item) for item in documents],
    }


@app.get("/coverage")
def coverage_all():
    started = time.perf_counter()
    try:
        payload = service.coverage_all(database())
    except ValueError as exc:
        raise fail(exc) from exc
    payload["elapsed_ms"] = _elapsed(started)
    return payload


@app.get("/facilities/nearby")
def nearby_facilities(
    longitude: float = Query(..., ge=-180, le=180),
    latitude: float = Query(..., ge=-90, le=90),
    radius_m: float = Query(default=500, gt=0, le=50000),
    facility_type: Optional[str] = Query(default=None),
    status: Optional[str] = Query(default=None),
    limit: int = Query(default=10, ge=1, le=1000),
):
    started = time.perf_counter()
    payload = service.nearby_facilities(
        database(),
        longitude,
        latitude,
        radius_m=radius_m,
        facility_type=facility_type,
        status=status,
        limit=limit,
    )
    payload["elapsed_ms"] = _elapsed(started)
    return payload


@app.post("/facilities/within")
def facilities_within(body: PolygonQuery):
    started = time.perf_counter()
    try:
        payload = service.facilities_within(
            database(),
            body.polygon,
            facility_type=body.facility_type,
            status=body.status,
            page=body.page,
            page_size=body.page_size,
        )
    except ValueError as exc:
        raise fail(exc) from exc
    payload["elapsed_ms"] = _elapsed(started)
    return payload


@app.get("/facilities/{facility_id}")
def get_facility(facility_id: str):
    document = database()["facilities"].find_one({"_id": facility_id})
    if document is None:
        raise HTTPException(status_code=404, detail="设施不存在")
    return public_document(document)


@app.post("/facilities", status_code=201)
def create_facility(body: FacilityCreate):
    if body.type not in geo.TYPE_LABELS:
        raise HTTPException(status_code=400, detail="未知的设施类型")
    longitude, latitude = body.location.coordinates
    _check_coordinates(longitude, latitude)
    document = {
        "_id": body.id,
        "name": body.name,
        "type": body.type,
        "status": body.status,
        "location": body.location.model_dump(),
        "coordinate_accuracy": body.coordinate_accuracy,
        "accuracy_meters": body.accuracy_meters,
        "building_id": body.building_id,
        "source": "api",
        "data_version": "manual",
        "updated_at": service.utc_now(),
    }
    try:
        database()["facilities"].insert_one(document)
    except Exception as exc:
        raise HTTPException(status_code=409, detail=f"设施写入失败: {exc}") from exc
    return public_document(document)


@app.patch("/facilities/{facility_id}/status")
def patch_facility_status(facility_id: str, body: StatusPatch):
    started = time.perf_counter()
    try:
        document = service.update_facility_status(
            database(),
            facility_id,
            body.status,
        )
    except ValueError as exc:
        raise fail(exc) from exc
    if document is None:
        raise HTTPException(status_code=404, detail="设施不存在")
    fresh = service.read_facility_fresh(facility_id)
    return {
        "elapsed_ms": _elapsed(started),
        "item": document,
        "fresh_read": fresh,
    }


@app.get("/bikes/nearby")
def get_nearby_bikes(
    longitude: float = Query(..., ge=-180, le=180),
    latitude: float = Query(..., ge=-90, le=90),
    radius_m: float = Query(default=500, gt=0, le=50000),
    limit: int = Query(default=20, ge=1, le=500),
):
    started = time.perf_counter()
    payload = service.nearby_bikes(
        database(),
        longitude,
        latitude,
        radius_m=radius_m,
        limit=limit,
    )
    payload["elapsed_ms"] = _elapsed(started)
    return payload


@app.get("/bikes/heatmap")
def bike_heatmap(
    start: Optional[datetime] = Query(default=None),
    end: Optional[datetime] = Query(default=None),
    hours: float = Query(default=1, gt=0, le=72),
    limit: int = Query(default=5000, ge=1, le=5000),
):
    window_end, window_start = _resolve_window(start, end, hours)
    started = time.perf_counter()
    try:
        payload = service.heatmap(database(), window_start, window_end, limit=limit)
    except ValueError as exc:
        raise fail(exc) from exc
    payload["elapsed_ms"] = _elapsed(started)
    return payload


@app.get("/bikes/anomalies")
def bike_anomalies(
    start: Optional[datetime] = Query(default=None),
    end: Optional[datetime] = Query(default=None),
    hours: float = Query(default=2, gt=0, le=72),
    limit: int = Query(default=1000, ge=1, le=5000),
):
    window_end, window_start = _resolve_window(start, end, hours)
    started = time.perf_counter()
    try:
        payload = service.anomalies(database(), window_start, window_end, limit=limit)
    except ValueError as exc:
        raise fail(exc) from exc
    payload["elapsed_ms"] = _elapsed(started)
    return payload


@app.get("/bikes/zombies")
def bike_zombies(limit: int = Query(default=500, ge=1, le=2000)):
    started = time.perf_counter()
    payload = service.zombies(database(), limit=limit)
    payload["elapsed_ms"] = _elapsed(started)
    return payload


@app.get("/bikes/{bike_id}/tracks")
def get_bike_tracks(
    bike_id: str,
    start: Optional[datetime] = Query(default=None),
    end: Optional[datetime] = Query(default=None),
    hours: float = Query(default=1, gt=0, le=72),
    limit: int = Query(default=2000, ge=1, le=10000),
):
    window_end, window_start = _resolve_window(start, end, hours)
    try:
        return service.bike_track(
            database(),
            bike_id,
            window_start,
            window_end,
            limit=limit,
        )
    except ValueError as exc:
        raise fail(exc) from exc


@app.post("/bikes/{bike_id}/reports", status_code=201)
def create_bike_report(bike_id: str, body: BikeReportCreate):
    longitude, latitude = body.location.coordinates
    _check_coordinates(longitude, latitude)
    try:
        return service.ingest_bike_report(
            database(),
            bike_id,
            longitude,
            latitude,
            stamp=body.timestamp,
            speed_mps=body.speed_mps,
            source=body.source,
        )
    except ValueError as exc:
        raise fail(exc) from exc


def _resolve_window(
    start: datetime | None,
    end: datetime | None,
    hours: float,
) -> tuple[datetime, datetime]:
    db = database()
    window_end = _aware(end) if end is not None else service.as_of(db)
    window_start = _aware(start) if start is not None else window_end - timedelta(hours=hours)
    return window_end, window_start


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _check_coordinates(longitude: float, latitude: float) -> None:
    if not -180 <= longitude <= 180:
        raise HTTPException(status_code=400, detail="经度必须位于 [-180, 180]")
    if not -90 <= latitude <= 90:
        raise HTTPException(status_code=400, detail="纬度必须位于 [-90, 90]")


def _elapsed(started: float) -> float:
    return round((time.perf_counter() - started) * 1000, 2)
