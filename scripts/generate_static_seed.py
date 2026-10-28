import argparse
import json
import math
import random
import sys
from datetime import datetime, timezone
from pathlib import Path

from shapely.geometry import Point, Polygon

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spatial import geo

SEED = 20260301
BUILDING_COUNT = 200
FACILITY_COUNTS = {
    "water_dispenser": 3000,
    "restroom": 3000,
    "study_seat": 6000,
    "charging_station": 2000,
    "printing_point": 2000,
    "parcel_locker": 4000,
}
BUILDING_TYPES = [
    "teaching",
    "dormitory",
    "library",
    "canteen",
    "administration",
    "laboratory",
    "sports",
    "service",
]
BUILDING_LABELS = {
    "teaching": "教学楼",
    "dormitory": "宿舍",
    "library": "图书馆",
    "canteen": "食堂",
    "administration": "行政楼",
    "laboratory": "实验楼",
    "sports": "体育馆",
    "service": "服务楼",
}


def make_ring(cx: float, cy: float, rng: random.Random):
    for _ in range(40):
        vertex_count = rng.randint(4, 20)
        base = rng.uniform(0, 2 * math.pi)
        angles = sorted(
            base + 2 * math.pi * index / vertex_count + rng.uniform(-0.12, 0.12)
            for index in range(vertex_count)
        )
        raw = []
        for angle in angles:
            raw.append(
                (
                    cx + math.cos(angle) * geo.CELL_LON * rng.uniform(0.28, 0.40),
                    cy + math.sin(angle) * geo.CELL_LAT * rng.uniform(0.28, 0.40),
                )
            )
        ring = [[round(x, 7), round(y, 7)] for x, y in raw]
        cleaned = [ring[0]]
        for point in ring[1:]:
            if point != cleaned[-1]:
                cleaned.append(point)
        if cleaned[0] != cleaned[-1]:
            cleaned.append(cleaned[0])
        if len(cleaned) - 1 < 4 or len(cleaned) - 1 > 20:
            continue
        polygon = Polygon(cleaned)
        if polygon.is_valid and polygon.area > 0:
            return cleaned, polygon
    raise RuntimeError("无法生成合法楼宇多边形")


def point_inside(polygon: Polygon) -> list[float]:
    candidate = polygon.centroid
    if not polygon.covers(candidate):
        candidate = polygon.representative_point()
    point = [round(candidate.x, 7), round(candidate.y, 7)]
    if polygon.covers(Point(point)):
        return point
    return [candidate.x, candidate.y]


def make_buildings(rng: random.Random) -> list[dict]:
    buildings = []
    for index in range(BUILDING_COUNT):
        row = index // geo.BUILDING_COLUMNS
        col = index % geo.BUILDING_COLUMNS
        cx = geo.MIN_LON + (col + 0.5) * geo.CELL_LON
        cy = geo.MIN_LAT + (row + 0.5) * geo.CELL_LAT
        ring, polygon = make_ring(cx, cy, rng)
        building_type = BUILDING_TYPES[index % len(BUILDING_TYPES)]
        center = point_inside(polygon)
        minx, miny, maxx, maxy = polygon.bounds
        diagonal = geo.haversine(minx, miny, maxx, maxy)
        buildings.append(
            {
                "_id": f"building_{index + 1:04d}",
                "name": f"{BUILDING_LABELS[building_type]}{index + 1:03d}",
                "building_type": building_type,
                "boundary": {"type": "Polygon", "coordinates": [ring]},
                "center": geo.geo_point(center[0], center[1]),
                "vertex_count": len(ring) - 1,
                "area_square_meters": round(geo.ring_area_m2(ring), 2),
                "center_accuracy_meters": int(max(20, round(diagonal / 2))),
                "data_version": "seed-v1",
                "_polygon": polygon,
            }
        )
    return buildings


def random_point_in_polygon(polygon: Polygon, rng: random.Random) -> tuple[float, float]:
    minx, miny, maxx, maxy = polygon.bounds
    for _ in range(80):
        lon = round(rng.uniform(minx, maxx), 7)
        lat = round(rng.uniform(miny, maxy), 7)
        if polygon.covers(Point(lon, lat)):
            return lon, lat
    point = polygon.representative_point()
    rounded = (round(point.x, 7), round(point.y, 7))
    if polygon.covers(Point(rounded)):
        return rounded
    return point.x, point.y


def make_facilities(buildings: list[dict], rng: random.Random) -> list[dict]:
    facilities = []
    facility_index = 1
    max_lon = geo.MAX_LON
    max_lat = geo.MAX_LAT

    for facility_type, count in FACILITY_COUNTS.items():
        for _ in range(count):
            if rng.random() < 0.60:
                building = buildings[rng.randrange(len(buildings))]
                building_id = building["_id"]
                roll = rng.random()
                if roll < 0.75:
                    lon, lat = random_point_in_polygon(building["_polygon"], rng)
                    coordinate_accuracy = "exact"
                    accuracy_meters = rng.choice([1, 3, 5, 8])
                elif roll < 0.95:
                    lon, lat = random_point_in_polygon(building["_polygon"], rng)
                    lon += rng.uniform(-0.00015, 0.00015)
                    lat += rng.uniform(-0.00015, 0.00015)
                    coordinate_accuracy = "estimated"
                    accuracy_meters = rng.choice([10, 20, 30])
                else:
                    lon, lat = building["center"]["coordinates"]
                    coordinate_accuracy = "building_center"
                    accuracy_meters = building["center_accuracy_meters"]
            else:
                lon = rng.uniform(geo.MIN_LON, max_lon)
                lat = rng.uniform(geo.MIN_LAT, max_lat)
                building_id = None
                coordinate_accuracy = "exact"
                accuracy_meters = rng.choice([2, 5, 10])

            if facility_type == "study_seat":
                status = rng.choices(
                    ["active", "occupied", "disabled"],
                    weights=[88, 10, 2],
                )[0]
            else:
                status = rng.choices(["active", "disabled"], weights=[97, 3])[0]

            facilities.append(
                {
                    "_id": f"facility_{facility_index:06d}",
                    "name": f"{facility_type}_{facility_index:06d}",
                    "type": facility_type,
                    "status": status,
                    "location": geo.geo_point(lon, lat),
                    "coordinate_accuracy": coordinate_accuracy,
                    "accuracy_meters": accuracy_meters,
                    "building_id": building_id,
                    "source": "generated_seed",
                    "data_version": "seed-v1",
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }
            )
            facility_index += 1
    return facilities


def write_jsonl(path: Path, documents: list[dict]) -> None:
    with path.open("w", encoding="utf-8") as file:
        for document in documents:
            file.write(json.dumps(document, ensure_ascii=False) + "\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "data" / "seed")
    args = parser.parse_args()
    output_dir = args.output
    output_dir.mkdir(parents=True, exist_ok=True)

    rng = random.Random(SEED)
    buildings = make_buildings(rng)
    facilities = make_facilities(buildings, rng)
    vertex_counts = [building["vertex_count"] for building in buildings]

    for building in buildings:
        building.pop("_polygon", None)

    write_jsonl(output_dir / "buildings.jsonl", buildings)
    write_jsonl(output_dir / "facilities.jsonl", facilities)

    metadata = {
        "_id": "seed-v1",
        "dataset_version": "seed-v1",
        "random_seed": SEED,
        "building_count": len(buildings),
        "facility_count": len(facilities),
        "facility_counts": FACILITY_COUNTS,
        "vertex_min": min(vertex_counts),
        "vertex_max": max(vertex_counts),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    (output_dir / "metadata.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"[OK] buildings: {len(buildings)}")
    print(f"[OK] facilities: {len(facilities)}")
    print(f"[OK] vertices: {min(vertex_counts)} ~ {max(vertex_counts)}")
    print(f"[OK] output: {output_dir}")


if __name__ == "__main__":
    main()
