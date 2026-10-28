"""功能 8：设施状态变更后，新连接立刻能查到。"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from spatial import service
from scripts.queries._common import database, repeat, save, show


def main() -> int:
    db = database()
    original = db["facilities"].find_one(
        {"type": "water_dispenser", "status": "active", "coordinate_accuracy": "exact"}
    )
    if original is None:
        print("[FAIL] 没有可用的饮水机")
        return 1
    facility_id = original["_id"]
    previous = original["status"]
    longitude, latitude = original["location"]["coordinates"]

    def change_and_read():
        service.update_facility_status(db, facility_id, "disabled")
        fresh = service.read_facility_fresh(facility_id)
        nearby = service.nearby_facilities(
            db,
            longitude,
            latitude,
            radius_m=500,
            facility_type="water_dispenser",
            status="active",
            limit=50,
        )
        visible = facility_id in {item["_id"] for item in nearby["items"]}
        return {"fresh_status": fresh["status"] if fresh else None, "still_in_active_nearby": visible}

    try:
        result, timings = repeat(change_and_read, times=5)
        restored = service.update_facility_status(db, facility_id, previous)
        after = service.nearby_facilities(
            db,
            longitude,
            latitude,
            radius_m=500,
            facility_type="water_dispenser",
            status="active",
            limit=50,
        )
        back = facility_id in {item["_id"] for item in after["items"]}
    finally:
        service.update_facility_status(db, facility_id, previous)

    payload = {
        "function": "状态维护",
        "facility_id": facility_id,
        "timing": timings,
        "while_disabled": result,
        "restored_status": restored["status"] if restored else None,
        "back_in_active_nearby": back,
    }
    path = save("08_status.json", payload)
    ok = (
        result["fresh_status"] == "disabled"
        and not result["still_in_active_nearby"]
        and back
    )
    show("状态维护", timings, f"{facility_id} 停用后附近查询不可见={not result['still_in_active_nearby']} 恢复={back}")
    print(path)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
