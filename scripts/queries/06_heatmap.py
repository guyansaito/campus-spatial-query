"""功能 6：时间窗口内按 50 米网格聚合单车分布。"""

import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from spatial import geo, service
from scripts.queries._common import database, repeat, save, show


def main() -> int:
    db = database()
    end = service.as_of(db)
    start = end - timedelta(hours=1)

    def query():
        return service.heatmap(db, start, end, limit=5000)

    result, timings = repeat(query)
    top = result["items"][:5]
    payload = {
        "function": "车辆热力",
        "timing": timings,
        "start": result["start"],
        "end": result["end"],
        "grid_size_m": result["grid_size_m"],
        "bucket_minutes": result["bucket_minutes"],
        "grid_reason": result["grid_reason"],
        "cell_count": result["cell_count"],
        "report_count": result["report_count"],
        "top": top,
    }
    path = save("06_heatmap.json", payload)
    show(
        "车辆热力",
        timings,
        f"格子 {result['cell_count']}  上报 {result['report_count']}  网格 {geo.GRID_SIZE_M} m",
    )
    print(path)
    return 0 if result["cell_count"] > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
