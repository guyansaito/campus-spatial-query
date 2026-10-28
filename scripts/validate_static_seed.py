import json
import sys
from collections import Counter
from pathlib import Path

from shapely.geometry import Point, Polygon

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

EXPECTED_FACILITY_COUNTS = {
    "water_dispenser": 3000,
    "restroom": 3000,
    "study_seat": 6000,
    "charging_station": 2000,
    "printing_point": 2000,
    "parcel_locker": 4000,
}
EXPECTED_BUILDING_COUNT = 200
EXPECTED_FACILITY_COUNT = 20000


def load_jsonl(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8") as file:
        return [json.loads(line) for line in file if line.strip()]


def validate_polygon(geometry: dict, building_id: str) -> int:
    if geometry.get("type") != "Polygon":
        raise ValueError(f"{building_id}: geometry type must be Polygon")
    rings = geometry.get("coordinates") or []
    if not rings:
        raise ValueError(f"{building_id}: empty Polygon")
    ring = rings[0]
    if len(ring) < 5:
        raise ValueError(f"{building_id}: polygon ring is too short")
    if ring[0] != ring[-1]:
        raise ValueError(f"{building_id}: polygon ring is not closed")
    vertex_count = len(ring) - 1
    if not 4 <= vertex_count <= 20:
        raise ValueError(f"{building_id}: vertex count {vertex_count} not in 4..20")
    return vertex_count


def validate_point(location: dict, document_id: str) -> None:
    if location.get("type") != "Point":
        raise ValueError(f"{document_id}: location must be Point")
    coordinates = location.get("coordinates")
    if not isinstance(coordinates, list) or len(coordinates) != 2:
        raise ValueError(f"{document_id}: invalid point coordinates")
    longitude, latitude = coordinates
    if not -180 <= longitude <= 180 or not -90 <= latitude <= 90:
        raise ValueError(f"{document_id}: coordinates out of range")


def main() -> int:
    source = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "data" / "seed"
    metadata = json.loads((source / "metadata.json").read_text(encoding="utf-8"))
    buildings = load_jsonl(source / "buildings.jsonl")
    facilities = load_jsonl(source / "facilities.jsonl")

    if len(buildings) != EXPECTED_BUILDING_COUNT:
        raise ValueError(f"building count {len(buildings)}")
    if len(facilities) != EXPECTED_FACILITY_COUNT:
        raise ValueError(f"facility count {len(facilities)}")
    if metadata.get("building_count") != len(buildings):
        raise ValueError("metadata building_count mismatch")
    if metadata.get("facility_count") != len(facilities):
        raise ValueError("metadata facility_count mismatch")

    polygons = {}
    vertex_counts = Counter()
    for building in buildings:
        count = validate_polygon(building["boundary"], building["_id"])
        validate_point(building["center"], building["_id"])
        vertex_counts[count] += 1
        polygons[building["_id"]] = Polygon(building["boundary"]["coordinates"][0])
        center = building["center"]["coordinates"]
        if not polygons[building["_id"]].covers(Point(center)):
            raise ValueError(f"{building['_id']}: center is outside the footprint")

    if min(vertex_counts) < 4 or max(vertex_counts) > 20 or len(vertex_counts) < 8:
        raise ValueError(f"vertex distribution is not diverse: {dict(vertex_counts)}")

    facility_types = Counter()
    facility_statuses = Counter()
    accuracy_types = Counter()
    outside = 0
    for facility in facilities:
        validate_point(facility["location"], facility["_id"])
        required = {
            "_id",
            "type",
            "status",
            "location",
            "coordinate_accuracy",
            "accuracy_meters",
        }
        missing = required - facility.keys()
        if missing:
            raise ValueError(f"{facility['_id']}: missing {sorted(missing)}")
        facility_types[facility["type"]] += 1
        facility_statuses[facility["status"]] += 1
        accuracy_types[facility["coordinate_accuracy"]] += 1
        building_id = facility.get("building_id")
        accuracy = facility["coordinate_accuracy"]
        if building_id and accuracy in {"exact", "building_center"}:
            point = Point(facility["location"]["coordinates"])
            if not polygons[building_id].covers(point):
                outside += 1
                if outside <= 5:
                    print(f"[WARN] {facility['_id']} outside {building_id}")

    if outside:
        raise ValueError(f"{outside} exact/center facilities fall outside their building")
    if dict(facility_types) != EXPECTED_FACILITY_COUNTS:
        raise ValueError(f"facility types {dict(facility_types)}")
    for name in ("exact", "estimated", "building_center"):
        if accuracy_types[name] <= 0:
            raise ValueError(f"missing accuracy {name}")
    if "disabled" not in facility_statuses or "occupied" not in facility_statuses:
        raise ValueError(f"statuses {dict(facility_statuses)}")
    if not any(item.get("building_id") for item in facilities):
        raise ValueError("no facility is tied to a building")
    if not any(item.get("building_id") is None for item in facilities):
        raise ValueError("no outdoor facility")

    print("[OK] static seed validation passed")
    print(f"[OK] buildings: {len(buildings)}")
    print(f"[OK] facilities: {len(facilities)}")
    print(f"[OK] vertices: {dict(sorted(vertex_counts.items()))}")
    print(f"[OK] facility types: {dict(facility_types)}")
    print(f"[OK] statuses: {dict(facility_statuses)}")
    print(f"[OK] coordinate accuracy: {dict(accuracy_types)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
