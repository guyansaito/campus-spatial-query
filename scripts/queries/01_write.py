"""功能 1：写入。

大批量导入由 scripts/seed.py 完成，耗时记在 dataset_metadata。
这里再测一次单条设施写入，并立刻读回。
"""

import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from spatial import geo
from spatial.serialize import public_document
from scripts.queries._common import database, repeat, save, show

PROBE_ID = "facility_probe_acceptance"


def main() -> int:
    db = database()
    meta = db["dataset_metadata"].find_one({"_id": "seed-v1"}) or {}

    def counts():
        return {
            "buildings": db["buildings"].count_documents({}),
            "facilities": db["facilities"].count_documents({}),
            "bikes": db["bikes"].count_documents({}),
            "bike_latest": db["bike_latest"].count_documents({}),
        }

    counted, timings = repeat(counts, times=3)

    def one_write():
        now = datetime.now(timezone.utc)
        db["facilities"].replace_one(
            {"_id": PROBE_ID},
            {
                "_id": PROBE_ID,
                "name": "验收探针饮水机",
                "type": "water_dispenser",
                "status": "active",
                "location": geo.geo_point(geo.CENTER_LON, geo.CENTER_LAT),
                "coordinate_accuracy": "exact",
                "accuracy_meters": 1,
                "building_id": None,
                "source": "acceptance",
                "data_version": "probe",
                "updated_at": now,
            },
            upsert=True,
        )
        return public_document(db["facilities"].find_one({"_id": PROBE_ID}))

    written, write_timings = repeat(one_write, times=5)
    db["facilities"].delete_one({"_id": PROBE_ID})
    gone = db["facilities"].find_one({"_id": PROBE_ID}) is None

    payload = {
        "function": "写入",
        "bulk": {
            "building_count": meta.get("building_count"),
            "facility_count": meta.get("facility_count"),
            "bike_count": meta.get("bike_count"),
            "report_count": meta.get("report_count"),
            "static_import_seconds": meta.get("static_import_seconds"),
            "buffer_seconds": meta.get("buffer_seconds"),
            "bike_insert_seconds": meta.get("bike_insert_seconds"),
        },
        "count_query": {"result": counted, "timing": timings},
        "single_facility_write": {"timing": write_timings, "read_back": written, "deleted": gone},
    }
    path = save("01_write.json", payload)
    show(
        "写入",
        write_timings,
        f"设施 {counted['facilities']}  楼宇 {counted['buildings']}  "
        f"车辆 {counted['bike_latest']}  上报 {meta.get('report_count')}  "
        f"导入 {meta.get('static_import_seconds')} s  "
        f"轨迹 {meta.get('bike_insert_seconds')} s",
    )
    print(path)
    return 0 if gone else 1


if __name__ == "__main__":
    sys.exit(main())
