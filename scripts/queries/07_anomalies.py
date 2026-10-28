"""功能 7：最近 2 小时位置跳变。

快路径读 bike_anomalies。随后用原始上报重算一遍，两边必须一致。
"""

import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from spatial import service
from scripts.queries._common import database, repeat, save, show


def stamp(value) -> str:
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def main() -> int:
    db = database()
    end = service.as_of(db)
    start = end - timedelta(hours=2)

    def query():
        return service.anomalies(db, start, end, limit=5000)

    indexed, timings = repeat(query)
    started_note = "indexed"
    recomputed, recompute_timing = repeat(lambda: service.recompute_jumps(db, start, end), times=1)
    indexed_keys = {(item["bike_id"], stamp(item["timestamp"])) for item in indexed["items"]}
    fresh_keys = {(item["bike_id"], stamp(item["timestamp"])) for item in recomputed["items"]}
    zombies = service.zombies(db, limit=5000)
    payload = {
        "function": "异常识别",
        "timing": timings,
        "recompute_timing": recompute_timing,
        "indexed_count": indexed["count"],
        "recompute_count": recomputed["count"],
        "recompute_scanned": recomputed["scanned"],
        "only_indexed": sorted(indexed_keys - fresh_keys)[:10],
        "only_recompute": sorted(fresh_keys - indexed_keys)[:10],
        "match": indexed_keys == fresh_keys,
        "zombie_count": zombies["count"],
        "sample": indexed["items"][:5],
        "path": started_note,
    }
    path = save("07_anomalies.json", payload)
    show(
        "跳变识别",
        timings,
        f"索引 {indexed['count']}  重算 {recomputed['count']}  "
        f"重算耗时 {recompute_timing['median_ms']} ms  扫描 {recomputed['scanned']}  "
        f"僵尸车 {zombies['count']}",
    )
    print(path)
    return 0 if indexed_keys == fresh_keys else 1


if __name__ == "__main__":
    sys.exit(main())
