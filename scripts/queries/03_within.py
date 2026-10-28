"""功能 3：多边形区域内的设施，分页。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from spatial import geo, service
from scripts.queries._common import database, repeat, save, show


def main() -> int:
    db = database()
    polygon = geo.campus_quarter_polygon()

    def query():
        return service.facilities_within(db, polygon, page=1, page_size=20)

    first, timings = repeat(query)
    second = service.facilities_within(db, polygon, page=2, page_size=20)
    ids_1 = [item["_id"] for item in first["items"]]
    ids_2 = [item["_id"] for item in second["items"]]
    overlap = set(ids_1) & set(ids_2)
    payload = {
        "function": "区域检索",
        "timing": timings,
        "total": first["total"],
        "page_size": 20,
        "page1_ids": ids_1,
        "page2_ids": ids_2,
        "overlap": sorted(overlap),
    }
    path = save("03_within.json", payload)
    show("区域检索", timings, f"总数 {first['total']}  第1页 {len(ids_1)}  第2页 {len(ids_2)}  重复 {len(overlap)}")
    print(path)
    return 0 if first["total"] >= len(ids_1) and not overlap else 1


if __name__ == "__main__":
    sys.exit(main())
