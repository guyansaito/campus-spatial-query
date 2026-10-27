import json
import random
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT / "data" / "seed"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

SEED = 20260301
random.seed(SEED)

BUILDING_COUNT = 200

FACILITY_COUNTS = {
    "water_dispenser": 3000,
    "restroom": 3000,
    "study_seat": 6000,
    "charging_station": 2000,
    "printing_point": 2000,
    "parcel_locker": 4000,
}

# 北京附近的模拟校园范围。
MIN_LON = 116.3000
MIN_LAT = 39.9000
CELL_LON = 0.0012
CELL_LAT = 0.0010

BUILDING_COLUMNS = 20
BUILDING_ROWS = 10


def point(lon: float, lat: float) -> dict:
    return {
        "type": "Point",
        "coordinates": [round(lon, 7), round(lat, 7)],
    }


def polygon(coordinates: list[list[float]]) -> dict:
    return {
        "type": "Polygon",
        "coordinates": [coordinates],
    }


def make_buildings() -> list[dict]:
    buildings = []

    building_types = [
        "teaching",
        "dormitory",
        "library",
        "canteen",
        "administration",
        "laboratory",
        "sports",
        "service",
    ]

    for index in range(BUILDING_COUNT):
        row = index // BUILDING_COLUMNS
        col = index % BUILDING_COLUMNS

        cell_min_lon = MIN_LON + col * CELL_LON
        cell_min_lat = MIN_LAT + row * CELL_LAT

        # 建筑物占据网格单元的大部分区域，但相邻建筑之间保留间隔。
        left = cell_min_lon + CELL_LON * 0.12
        right = cell_min_lon + CELL_LON * 0.88
        bottom = cell_min_lat + CELL_LAT * 0.12
        top = cell_min_lat + CELL_LAT * 0.88

        ring = [
            [round(left, 7), round(bottom, 7)],
            [round(right, 7), round(bottom, 7)],
            [round(right, 7), round(top, 7)],
            [round(left, 7), round(top, 7)],
            [round(left, 7), round(bottom, 7)],
        ]

        center_lon = (left + right) / 2
        center_lat = (bottom + top) / 2

        buildings.append(
            {
                "_id": f"building_{index + 1:04d}",
                "name": f"校园{building_types[index % len(building_types)]}{index + 1:03d}",
                "building_type": building_types[index % len(building_types)],
                "boundary": polygon(ring),
                "center": point(center_lon, center_lat),
                "area_square_meters": round(
                    (right - left) * 111000
                    * (top - bottom)
                    * 111000
                    * 0.8,
                    2,
                ),
                "data_version": "seed-v1",
            }
        )

    return buildings


def random_point_in_building(building: dict) -> tuple[float, float]:
    ring = building["boundary"]["coordinates"][0]
    left = ring[0][0]
    bottom = ring[0][1]
    right = ring[2][0]
    top = ring[2][1]

    lon = random.uniform(left + 0.00003, right - 0.00003)
    lat = random.uniform(bottom + 0.00003, top - 0.00003)
    return lon, lat


def random_campus_point() -> tuple[float, float]:
    max_lon = MIN_LON + BUILDING_COLUMNS * CELL_LON
    max_lat = MIN_LAT + BUILDING_ROWS * CELL_LAT

    return (
        random.uniform(MIN_LON, max_lon),
        random.uniform(MIN_LAT, max_lat),
    )


def make_facilities(buildings: list[dict]) -> list[dict]:
    facilities = []
    facility_index = 1

    for facility_type, count in FACILITY_COUNTS.items():
        for _ in range(count):
            placement = random.random()

            if placement < 0.60:
                building = random.choice(buildings)
                lon, lat = random_point_in_building(building)
                building_id = building["_id"]

                accuracy_choice = random.random()

                if accuracy_choice < 0.75:
                    coordinate_accuracy = "exact"
                    accuracy_meters = random.choice([1, 3, 5, 8])
                    location = point(lon, lat)
                elif accuracy_choice < 0.95:
                    coordinate_accuracy = "estimated"
                    accuracy_meters = random.choice([10, 20, 30])
                    location = point(
                        lon + random.uniform(-0.00015, 0.00015),
                        lat + random.uniform(-0.00015, 0.00015),
                    )
                else:
                    coordinate_accuracy = "building_center"
                    accuracy_meters = random.choice([30, 40, 50])
                    location = building["center"]
            else:
                lon, lat = random_campus_point()
                building_id = None
                coordinate_accuracy = "exact"
                accuracy_meters = random.choice([2, 5, 10])
                location = point(lon, lat)

            if facility_type == "study_seat":
                status = random.choices(
                    ["active", "occupied", "disabled"],
                    weights=[88, 10, 2],
                    k=1,
                )[0]
            else:
                status = random.choices(
                    ["active", "disabled"],
                    weights=[97, 3],
                    k=1,
                )[0]

            facilities.append(
                {
                    "_id": f"facility_{facility_index:06d}",
                    "name": f"{facility_type}_{facility_index:06d}",
                    "type": facility_type,
                    "status": status,
                    "location": location,
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
    buildings = make_buildings()
    facilities = make_facilities(buildings)

    write_jsonl(OUTPUT_DIR / "buildings.jsonl", buildings)
    write_jsonl(OUTPUT_DIR / "facilities.jsonl", facilities)

    metadata = {
        "_id": "seed-v1",
        "dataset_version": "seed-v1",
        "random_seed": SEED,
        "building_count": len(buildings),
        "facility_count": len(facilities),
        "facility_counts": FACILITY_COUNTS,
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }

    with (OUTPUT_DIR / "metadata.json").open("w", encoding="utf-8") as file:
        json.dump(metadata, file, ensure_ascii=False, indent=2)

    print(f"[OK] buildings: {len(buildings)}")
    print(f"[OK] facilities: {len(facilities)}")
    print(f"[OK] output: {OUTPUT_DIR}")


if __name__ == "__main__":
    main()