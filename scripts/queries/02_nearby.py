"""功能 2：500 米内最近的 10 个某类设施，按距离升序。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from spatial import geo, service
from scripts.queries._common import database, repeat, save, show


def main() -> int:
    db = database()

    def query():
        return service.nearby_facilities(
            db,
            geo.CENTER_LON,
            geo.CENTER_LAT,
            radius_m=500,
            facility_type="water_dispenser",
            limit=10,
        )

    result, timings = repeat(query)
    distances = [item["distance_m"] for item in result["items"]]
    ordered = distances == sorted(distances)
    payload = {
        "function": "附近查找",
        "timing": timings,
        "count": result["count"],
        "distances_m": distances,
        "sorted": ordered,
        "items": [
            {
                "_id": item["_id"],
                "distance_m": item["distance_m"],
                "distance_min_m": item["distance_min_m"],
                "distance_max_m": item["distance_max_m"],
                "coordinate_accuracy": item.get("coordinate_accuracy"),
                "accuracy_meters": item.get("accuracy_meters"),
                "status": item.get("status"),
            }
            for item in result["items"]
        ],
    }
    explain = db.command(
        "explain",
        {
            "aggregate": "facilities",
            "pipeline": [
                {
                    "$geoNear": {
                        "near": geo.geo_point(geo.CENTER_LON, geo.CENTER_LAT),
                        "key": "location",
                        "distanceField": "distance_m",
                        "maxDistance": 500,
                        "spherical": True,
                        "query": {"type": "water_dispenser"},
                    }
                },
                {"$limit": 10},
            ],
            "cursor": {},
        },
        verbosity="executionStats",
    )
    payload["explain_ok"] = isinstance(explain, dict) and (
        "queryPlanner" in explain or "executionStats" in explain or "stages" in explain
    )
    path = save("02_nearby.json", payload)
    show("附近查找", timings, f"返回 {result['count']} 条  距离 {distances}  有序 {ordered}")
    print(path)
    return 0 if ordered and result["count"] <= 10 else 1


if __name__ == "__main__":
    sys.exit(main())
