"""坐标、距离、网格和跳变判定。

距离有两种口径，不要混用：
- 附近查找用 MongoDB `$geoNear` 的球面距离（半径 6378100 米）。
- 跳变识别和网格换算用本模块的 Haversine（半径 6371008.8 米）。
两者都是球面距离，校园尺度下相差可以忽略。
"""

import math
from datetime import datetime, timedelta, timezone

EARTH_RADIUS_M = 6371008.8
MONGO_EARTH_RADIUS_M = 6378100.0

# 北京附近的模拟校园。20 列 × 10 行，每格约 100 米 × 110 米。
MIN_LON = 116.3000
MIN_LAT = 39.9000
CELL_LON = 0.0012
CELL_LAT = 0.0010
BUILDING_COLUMNS = 20
BUILDING_ROWS = 10
MAX_LON = MIN_LON + BUILDING_COLUMNS * CELL_LON
MAX_LAT = MIN_LAT + BUILDING_ROWS * CELL_LAT
CENTER_LON = (MIN_LON + MAX_LON) / 2
CENTER_LAT = (MIN_LAT + MAX_LAT) / 2

LAT0 = CENTER_LAT
M_PER_DEG_LAT = 111132.954
M_PER_DEG_LON = 111132.954 * math.cos(math.radians(LAT0))

# 50 米约半栋楼，且大于常见手机定位误差。
GRID_SIZE_M = 50
BUCKET_MINUTES = 15

# 正常骑行上限 5 m/s，30 秒最多约 150 米。
# 160 米会误伤正常骑行，所以阈值放在 180 米；注入的瞬移至少 300 米。
NORMAL_MAX_SPEED_MPS = 5.0
JUMP_DISTANCE_M = 180.0
JUMP_MIN_INJECT_M = 300.0
MAX_JUMP_GAP_S = 60.0
ZOMBIE_DISPLACEMENT_M = 10.0

FACILITY_TYPES = [
    "water_dispenser",
    "restroom",
    "study_seat",
    "charging_station",
    "printing_point",
    "parcel_locker",
]

TYPE_LABELS = {
    "water_dispenser": "饮水机",
    "restroom": "卫生间",
    "study_seat": "自习座位",
    "charging_station": "充电桩",
    "printing_point": "打印点",
    "parcel_locker": "快递柜",
}

STATUS_LABELS = {
    "active": "可用",
    "disabled": "停用",
    "occupied": "占用",
}

GRID_REASON = (
    "校园约 2.0 km × 1.1 km，楼宇网格约 100 m。"
    "热力用 50 m 格子，大约半栋楼，能分开楼前和楼后的聚集；"
    "这个尺寸也大于常见手机定位误差（5～15 m），不会被噪声切碎。"
    "全校园大约 40×23 个格子，结果可以直接画在地图上。"
    "时间按 15 分钟分桶，是 30 秒上报间隔的 30 倍，"
    "短时拥堵看得到，1700 万条明细也被压成十万级汇总。"
)

DISTANCE_NOTE = (
    "坐标使用 WGS84，GeoJSON 顺序是 [经度, 纬度]。"
    "附近查找走 2dsphere 上的 $geoNear（spherical: true），单位米，"
    f"MongoDB 使用的球面半径是 {MONGO_EARTH_RADIUS_M:.0f} 米。"
    "楼宇 300 米覆盖不按经纬度直接外扩，而是先投到 UTM 50N（EPSG:32650）"
    "做平面缓冲，再投回 WGS84，避免经向和纬向每度对应的米数不同。"
    "上报点精度分 exact、estimated、building_center。"
    "距离按上报点计算，同时给出 accuracy_meters，"
    "真实位置落在 [max(0, 距离-精度), 距离+精度]。"
    "只有楼栋中心的点不能当成米级定位。"
)


def geo_point(lon: float, lat: float, ndigits: int = 7) -> dict:
    return {
        "type": "Point",
        "coordinates": [round(float(lon), ndigits), round(float(lat), ndigits)],
    }


def haversine(lon1: float, lat1: float, lon2: float, lat2: float) -> float:
    lon_1 = math.radians(lon1)
    lat_1 = math.radians(lat1)
    lon_2 = math.radians(lon2)
    lat_2 = math.radians(lat2)
    delta_lon = lon_2 - lon_1
    delta_lat = lat_2 - lat_1
    value = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(lat_1) * math.cos(lat_2) * math.sin(delta_lon / 2) ** 2
    )
    value = max(0.0, min(1.0, value))
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(value))


def is_jump(distance_m: float, gap_seconds: float) -> bool:
    """相邻两次上报间隔不超过 60 秒，且球面距离达到跳变阈值。"""
    return 0 < gap_seconds <= MAX_JUMP_GAP_S and distance_m >= JUMP_DISTANCE_M


def grid_index(lon: float, lat: float) -> tuple[int, int]:
    grid_x = math.floor((lon - MIN_LON) * M_PER_DEG_LON / GRID_SIZE_M)
    grid_y = math.floor((lat - MIN_LAT) * M_PER_DEG_LAT / GRID_SIZE_M)
    return int(grid_x), int(grid_y)


def grid_center(grid_x: int, grid_y: int) -> tuple[float, float]:
    lon = MIN_LON + (grid_x + 0.5) * GRID_SIZE_M / M_PER_DEG_LON
    lat = MIN_LAT + (grid_y + 0.5) * GRID_SIZE_M / M_PER_DEG_LAT
    return round(lon, 7), round(lat, 7)


def grid_id(grid_x: int, grid_y: int) -> str:
    return f"{grid_x}:{grid_y}"


def heatmap_document_id(window_start: datetime, grid_x: int, grid_y: int) -> str:
    return f"{window_start.isoformat()}|{grid_x}|{grid_y}"


def floor_bucket(ts: datetime, minutes: int = BUCKET_MINUTES) -> datetime:
    if ts.tzinfo is None:
        ts = ts.replace(tzinfo=timezone.utc)
    else:
        ts = ts.astimezone(timezone.utc)
    minute = (ts.minute // minutes) * minutes
    return ts.replace(minute=minute, second=0, microsecond=0)


def bucket_end(window_start: datetime, minutes: int = BUCKET_MINUTES) -> datetime:
    return window_start + timedelta(minutes=minutes)


def point_in_ring(lon: float, lat: float, ring: list) -> bool:
    points = ring[:-1] if ring and ring[0] == ring[-1] else ring
    if len(points) < 3:
        return False
    inside = False
    previous = len(points) - 1
    for index in range(len(points)):
        xi, yi = points[index]
        xj, yj = points[previous]
        intersects = (yi > lat) != (yj > lat) and lon < (
            (xj - xi) * (lat - yi) / ((yj - yi) or 1e-30) + xi
        )
        if intersects:
            inside = not inside
        previous = index
    return inside


def ring_area_m2(ring: list) -> float:
    area = 0.0
    for index in range(len(ring) - 1):
        x1, y1 = ring[index]
        x2, y2 = ring[index + 1]
        area += x1 * y2 - x2 * y1
    area = abs(area) / 2
    return area * M_PER_DEG_LON * M_PER_DEG_LAT


def campus_polygon() -> dict:
    ring = [
        [MIN_LON, MIN_LAT],
        [MAX_LON, MIN_LAT],
        [MAX_LON, MAX_LAT],
        [MIN_LON, MAX_LAT],
        [MIN_LON, MIN_LAT],
    ]
    return {"type": "Polygon", "coordinates": [ring]}


def campus_quarter_polygon() -> dict:
    mid_lon = (MIN_LON + MAX_LON) / 2
    mid_lat = (MIN_LAT + MAX_LAT) / 2
    ring = [
        [MIN_LON, MIN_LAT],
        [mid_lon, MIN_LAT],
        [mid_lon, mid_lat],
        [MIN_LON, mid_lat],
        [MIN_LON, MIN_LAT],
    ]
    return {"type": "Polygon", "coordinates": [ring]}


def ensure_polygon(polygon: dict) -> dict:
    if not isinstance(polygon, dict) or polygon.get("type") != "Polygon":
        raise ValueError("polygon.type 必须为 Polygon")
    rings = polygon.get("coordinates")
    if not isinstance(rings, list) or not rings or not isinstance(rings[0], list):
        raise ValueError("polygon.coordinates 格式无效")
    if len(rings[0]) < 4:
        raise ValueError("多边形至少需要 4 个点（含闭合点）")
    if rings[0][0] != rings[0][-1]:
        raise ValueError("多边形没有闭合")
    return polygon


def clip_campus(lon: float, lat: float) -> tuple[float, float]:
    return (
        min(MAX_LON, max(MIN_LON, lon)),
        min(MAX_LAT, max(MIN_LAT, lat)),
    )
