"""生成共享单车上报。

最新位置写入 bike_latest（约 2000 条，给“附近的车”用）。
每 30 秒一条的历史上报写入时间序列 bike_reports，不建地理位置索引。
热力在写入时按 50 米、15 分钟汇总。跳变也在写入时判定。
"""

import argparse
import math
import random
import sys
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pymongo import ASCENDING

from spatial import geo
from spatial.db import get_client, mongo_settings
from spatial.schema import drop_index_if_exists, reset_movement_data

SEED = 20260301
BATCH_SIZE = 8000


def far_point(lon: float, lat: float, rng: random.Random) -> tuple[float, float]:
    for _ in range(80):
        candidate_lon = rng.uniform(geo.MIN_LON, geo.MAX_LON)
        candidate_lat = rng.uniform(geo.MIN_LAT, geo.MAX_LAT)
        if geo.haversine(lon, lat, candidate_lon, candidate_lat) >= geo.JUMP_MIN_INJECT_M:
            return candidate_lon, candidate_lat
    delta_lon = 400 / geo.M_PER_DEG_LON
    next_lon = lon + delta_lon
    if next_lon > geo.MAX_LON:
        next_lon = lon - delta_lon
    return geo.clip_campus(next_lon, lat)


def flush_heatmap(collection, window_start, cell_reports: dict, cell_bikes: dict) -> int:
    if not cell_reports:
        return 0
    window_end = geo.bucket_end(window_start)
    documents = []
    for (grid_x, grid_y), report_count in cell_reports.items():
        center_lon, center_lat = geo.grid_center(grid_x, grid_y)
        documents.append(
            {
                "_id": geo.heatmap_document_id(window_start, grid_x, grid_y),
                "window_start": window_start,
                "window_end": window_end,
                "grid_size_m": geo.GRID_SIZE_M,
                "grid_x": grid_x,
                "grid_y": grid_y,
                "grid_id": geo.grid_id(grid_x, grid_y),
                "center": geo.geo_point(center_lon, center_lat),
                "report_count": report_count,
                "bike_count": len(cell_bikes[(grid_x, grid_y)]),
            }
        )
    collection.insert_many(documents, ordered=False)
    return len(documents)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=float, default=3.0)
    parser.add_argument("--bikes", type=int, default=2000)
    args = parser.parse_args()

    bike_count = args.bikes
    steps = int(round(args.days * 24 * 60 * 60 / 30))
    if bike_count < 10 or steps < 2:
        print("[FAIL] 至少 10 辆车、2 个上报周期")
        return 1

    expected = bike_count * steps
    print(
        f"[bike] 准备写入 {bike_count} 辆 × {steps} 次 = {expected} 条上报。"
        "这些数据只进 MongoDB，不要导出数据库。",
        flush=True,
    )

    client = get_client()
    database = client[mongo_settings()["database"]]
    client.admin.command("ping")
    reset_movement_data(database)
    # 1700 万条插入期间先不要二级索引，插完再补。时间字段本身有聚集索引。
    drop_index_if_exists(database["bike_reports"], "idx_bike_reports_bike_time")

    rng = random.Random(SEED)
    zombie_n = max(1, int(round(bike_count * 0.05)))
    jumper_n = max(1, int(round(bike_count * 0.06)))
    if zombie_n + jumper_n >= bike_count:
        zombie_n = max(1, bike_count // 10)
        jumper_n = max(1, bike_count // 10)
    zombie_ids = set(rng.sample(range(bike_count), zombie_n))
    jumper_ids = set(rng.sample([i for i in range(bike_count) if i not in zombie_ids], jumper_n))

    jump_steps = [set() for _ in range(bike_count)]
    latest_zone = max(1, steps - 240)
    for bike_index in jumper_ids:
        jump_steps[bike_index].add(rng.randrange(latest_zone, steps))
        if latest_zone > 1:
            for _ in range(2):
                jump_steps[bike_index].add(rng.randrange(1, latest_zone))

    centers = [
        tuple(document["center"]["coordinates"])
        for document in database["buildings"].find({}, {"center": 1})
        if document.get("center")
    ]
    lons = [0.0] * bike_count
    lats = [0.0] * bike_count
    headings = [rng.uniform(0, math.tau) for _ in range(bike_count)]
    for index in range(bike_count):
        if centers and rng.random() < 0.75:
            center_lon, center_lat = centers[rng.randrange(len(centers))]
            lon = center_lon + rng.uniform(-25, 25) / geo.M_PER_DEG_LON
            lat = center_lat + rng.uniform(-25, 25) / geo.M_PER_DEG_LAT
            lon, lat = geo.clip_campus(lon, lat)
        else:
            lon = rng.uniform(geo.MIN_LON, geo.MAX_LON)
            lat = rng.uniform(geo.MIN_LAT, geo.MAX_LAT)
        lons[index] = lon
        lats[index] = lat
    origin_lons = lons.copy()
    origin_lats = lats.copy()
    max_disp = [0.0] * bike_count
    jump_counts = [0] * bike_count
    speeds = [0.0] * bike_count

    now = datetime.now(timezone.utc).replace(microsecond=0)
    end = now - timedelta(seconds=now.second % 30)
    start = end - timedelta(seconds=30 * (steps - 1))

    reports = database["bike_reports"]
    inserted = 0
    inserted_lock = threading.Lock()
    inflight: list[Future] = []
    started_at = time.perf_counter()

    def insert_batch(documents: list[dict]) -> None:
        nonlocal inserted
        reports.insert_many(documents, ordered=False)
        with inserted_lock:
            inserted += len(documents)
            done = inserted
        if done % 200000 < len(documents) or done == expected:
            elapsed = time.perf_counter() - started_at
            rate = done / elapsed if elapsed else 0
            print(
                f"[bike] inserted {done}/{expected}  {rate:.0f} docs/s",
                flush=True,
            )

    def submit(documents: list[dict]) -> None:
        while inflight and inflight[0].done():
            inflight.pop(0).result()
        while len(inflight) >= 2:
            inflight.pop(0).result()
        inflight.append(pool.submit(insert_batch, documents))

    anomalies = []
    heatmap_docs = 0
    current_window = None
    cell_reports: dict[tuple[int, int], int] = {}
    cell_bikes: dict[tuple[int, int], set] = {}
    batch: list[dict] = []
    uniform = rng.uniform
    random_value = rng.random
    haversine = geo.haversine
    grid_index = geo.grid_index
    is_jump = geo.is_jump
    geo_point = geo.geo_point

    pool = ThreadPoolExecutor(max_workers=1)
    try:
        for step in range(steps):
            stamp = start + timedelta(seconds=30 * step)
            window = geo.floor_bucket(stamp)
            if current_window is None:
                current_window = window
            elif window != current_window:
                heatmap_docs += flush_heatmap(
                    database["heatmap_aggregates"],
                    current_window,
                    cell_reports,
                    cell_bikes,
                )
                cell_reports = {}
                cell_bikes = {}
                current_window = window

            for index in range(bike_count):
                previous_lon = lons[index]
                previous_lat = lats[index]
                if step == 0:
                    speed = 0.0
                elif index in zombie_ids:
                    lons[index] = origin_lons[index] + uniform(-1.5, 1.5) / geo.M_PER_DEG_LON
                    lats[index] = origin_lats[index] + uniform(-1.5, 1.5) / geo.M_PER_DEG_LAT
                    speed = 0.0
                elif step in jump_steps[index]:
                    lons[index], lats[index] = far_point(previous_lon, previous_lat, rng)
                    speed = 0.0
                else:
                    headings[index] += uniform(-0.35, 0.35)
                    if step < 20:
                        speed = uniform(1.5, geo.NORMAL_MAX_SPEED_MPS)
                    elif random_value() < 0.08:
                        speed = 0.0
                    else:
                        speed = uniform(0.6, geo.NORMAL_MAX_SPEED_MPS)
                    next_lon = previous_lon + speed * 30 * math.cos(headings[index]) / geo.M_PER_DEG_LON
                    next_lat = previous_lat + speed * 30 * math.sin(headings[index]) / geo.M_PER_DEG_LAT
                    if next_lon < geo.MIN_LON or next_lon > geo.MAX_LON:
                        headings[index] = math.pi - headings[index]
                    if next_lat < geo.MIN_LAT or next_lat > geo.MAX_LAT:
                        headings[index] = -headings[index]
                    lons[index], lats[index] = geo.clip_campus(next_lon, next_lat)

                if step > 0:
                    distance = haversine(previous_lon, previous_lat, lons[index], lats[index])
                    if is_jump(distance, 30):
                        bike_id = f"bike_{index + 1:04d}"
                        jump_counts[index] += 1
                        anomalies.append(
                            {
                                "_id": f"{bike_id}|{stamp.isoformat()}",
                                "bike_id": bike_id,
                                "timestamp": stamp,
                                "anomaly_type": "jump",
                                "distance_m": round(distance, 2),
                                "gap_seconds": 30,
                                "implied_speed_kmh": round(distance / 30 * 3.6, 2),
                                "from_location": geo_point(previous_lon, previous_lat),
                                "to_location": geo_point(lons[index], lats[index]),
                                "source": "seed",
                            }
                        )
                        speed = distance / 30

                moved = haversine(origin_lons[index], origin_lats[index], lons[index], lats[index])
                if moved > max_disp[index]:
                    max_disp[index] = moved
                speeds[index] = speed

                grid_x, grid_y = grid_index(lons[index], lats[index])
                key = (grid_x, grid_y)
                cell_reports[key] = cell_reports.get(key, 0) + 1
                bikes_here = cell_bikes.get(key)
                if bikes_here is None:
                    cell_bikes[key] = {index}
                else:
                    bikes_here.add(index)

                batch.append(
                    {
                        "timestamp": stamp,
                        "meta": {"bike_id": f"bike_{index + 1:04d}"},
                        "location": geo_point(lons[index], lats[index]),
                        "speed_mps": round(speed, 2),
                    }
                )
                if len(batch) >= BATCH_SIZE:
                    submit(batch)
                    batch = []

        if batch:
            submit(batch)
            batch = []
        for future in inflight:
            future.result()
        if current_window is not None:
            heatmap_docs += flush_heatmap(
                database["heatmap_aggregates"],
                current_window,
                cell_reports,
                cell_bikes,
            )
    finally:
        pool.shutdown(wait=True)

    detected = {index for index, value in enumerate(max_disp) if value < geo.ZOMBIE_DISPLACEMENT_M}
    if detected != zombie_ids:
        missed = sorted(zombie_ids - detected)[:5]
        extra = sorted(detected - zombie_ids)[:5]
        print(f"[FAIL] 僵尸车识别和注入不一致 missed={missed} extra={extra}")
        return 1

    latest_docs = []
    bike_docs = []
    for index in range(bike_count):
        bike_id = f"bike_{index + 1:04d}"
        status = "zombie" if index in zombie_ids else "active"
        latest_docs.append(
            {
                "_id": bike_id,
                "bike_id": bike_id,
                "location": geo.geo_point(lons[index], lats[index]),
                "last_report_at": end,
                "timestamp": end,
                "speed_mps": round(speeds[index], 2),
                "origin": geo.geo_point(origin_lons[index], origin_lats[index]),
                "displacement_m": round(max_disp[index], 2),
                "status": status,
            }
        )
        bike_docs.append(
            {
                "_id": bike_id,
                "status": status,
                "displacement_m": round(max_disp[index], 2),
                "injected_zombie": index in zombie_ids,
                "jump_count": jump_counts[index],
                "report_count": steps,
                "last_report_at": end,
                "origin": geo.geo_point(origin_lons[index], origin_lats[index]),
            }
        )

    database["bike_latest"].insert_many(latest_docs, ordered=False)
    database["bikes"].insert_many(bike_docs, ordered=False)
    if anomalies:
        database["bike_anomalies"].insert_many(anomalies, ordered=False)

    print("[bike] 正在为时间序列补 bike_id + timestamp 索引", flush=True)
    database["bike_reports"].create_index(
        [("meta.bike_id", ASCENDING), ("timestamp", ASCENDING)],
        name="idx_bike_reports_bike_time",
    )

    recent_start = end - timedelta(hours=2)
    recent_jumps = sum(1 for item in anomalies if item["timestamp"] >= recent_start)
    elapsed = time.perf_counter() - started_at
    database["dataset_metadata"].update_one(
        {"_id": "seed-v1"},
        {
            "$set": {
                "bike_count": bike_count,
                "report_count": expected,
                "simulation_start": start,
                "simulation_end": end,
                "report_interval_seconds": 30,
                "simulation_days": args.days,
                "jump_threshold_m": geo.JUMP_DISTANCE_M,
                "jump_count": len(anomalies),
                "recent_jump_count": recent_jumps,
                "zombie_count": zombie_n,
                "zombie_threshold_m": geo.ZOMBIE_DISPLACEMENT_M,
                "grid_size_m": geo.GRID_SIZE_M,
                "heatmap_bucket_minutes": geo.BUCKET_MINUTES,
                "heatmap_cell_documents": heatmap_docs,
                "bike_insert_seconds": round(elapsed, 2),
                "distance_note": geo.DISTANCE_NOTE,
                "grid_reason": geo.GRID_REASON,
            }
        },
        upsert=True,
    )
    print(f"[OK] reports: {expected}")
    print(f"[OK] jumps: {len(anomalies)}  recent_2h: {recent_jumps}")
    print(f"[OK] zombies: {zombie_n}")
    print(f"[OK] heatmap cells: {heatmap_docs}")
    print(f"[OK] bike insert seconds: {elapsed:.1f}")
    print(f"[OK] simulation: {start.isoformat()} -> {end.isoformat()}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
