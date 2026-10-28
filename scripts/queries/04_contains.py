"""功能 4：给定坐标，判断它在哪栋楼内。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from spatial import geo, service
from scripts.queries._common import database, repeat, save, show


def main() -> int:
    db = database()
    building = db["buildings"].find_one({}, {"center": 1, "name": 1})
    if building is None:
        print("[FAIL] 没有楼宇")
        return 1
    lon, lat = building["center"]["coordinates"]

    def inside():
        return service.buildings_containing(db, lon, lat)

    result, timings = repeat(inside)
    outside = service.buildings_containing(db, geo.MIN_LON - 0.01, geo.MIN_LAT - 0.01)
    ids = [item["_id"] for item in result["items"]]
    payload = {
        "function": "包含判断",
        "timing": timings,
        "point": {"lon": lon, "lat": lat},
        "expected_building": building["_id"],
        "hit_ids": ids,
        "outside_count": outside["count"],
    }
    path = save("04_contains.json", payload)
    show("包含判断", timings, f"点落在 {ids}  校园外 {outside['count']} 栋")
    print(path)
    return 0 if building["_id"] in ids and outside["count"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
