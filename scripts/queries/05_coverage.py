"""功能 5：每栋楼 300 米范围内有几类设施、各几个。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from spatial import service
from scripts.queries._common import database, repeat, save, show


def main() -> int:
    db = database()
    result, timings = repeat(lambda: service.coverage_all(db), times=3)
    categories = [item["category_count"] for item in result["items"]]
    payload = {
        "function": "覆盖分析",
        "timing": timings,
        "building_count": result["building_count"],
        "category_min": min(categories) if categories else None,
        "category_max": max(categories) if categories else None,
        "sample": result["items"][:3],
        "items": result["items"],
    }
    path = save("05_coverage.json", payload)
    show(
        "覆盖分析",
        timings,
        f"楼宇 {result['building_count']}  类别数 {min(categories) if categories else '-'}~{max(categories) if categories else '-'}",
    )
    print(path)
    return 0 if result["building_count"] == 200 else 1


if __name__ == "__main__":
    sys.exit(main())
