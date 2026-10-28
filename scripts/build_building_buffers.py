import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv
from pymongo import MongoClient
from pyproj import Transformer
from shapely.geometry import shape, mapping
from shapely.ops import transform


ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

# 北京区域使用 UTM 50N，单位为米，适合进行 300 米缓冲计算。
TO_METERS = Transformer.from_crs(
    "EPSG:4326",
    "EPSG:32650",
    always_xy=True,
).transform

TO_WGS84 = Transformer.from_crs(
    "EPSG:32650",
    "EPSG:4326",
    always_xy=True,
).transform


def build_buffer(boundary: dict, distance_m: float) -> dict:
    geometry = shape(boundary)

    projected = transform(TO_METERS, geometry)
    buffered = projected.buffer(distance_m, resolution=16)
    result = transform(TO_WGS84, buffered)

    return mapping(result)


def main() -> int:
    mongo_port = int(os.getenv("MONGO_PORT", "27017"))
    database_name = os.getenv("MONGO_DATABASE", "campus_service")

    client = MongoClient(
        "127.0.0.1",
        mongo_port,
        username=os.getenv("MONGO_ROOT_USERNAME"),
        password=os.getenv("MONGO_ROOT_PASSWORD"),
        authSource="admin",
        serverSelectionTimeoutMS=5000,
        appname="campus-building-buffer-builder",
    )

    try:
        client.admin.command("ping")
        database = client[database_name]
        buildings = database["buildings"]
        started = time.perf_counter()
        count = 0

        for building in buildings.find(
            {"boundary": {"$exists": True}},
            {"_id": 1, "boundary": 1},
        ):
            coverage_300m = build_buffer(
                building["boundary"],
                distance_m=300,
            )

            buildings.update_one(
                {"_id": building["_id"]},
                {
                    "$set": {
                        "coverage_300m": coverage_300m,
                        "coverage_buffer_distance_m": 300,
                        "coverage_buffer_version": "buffer-v1",
                    }
                },
            )

            count += 1

        elapsed = round(time.perf_counter() - started, 2)
        database["dataset_metadata"].update_one(
            {"_id": "seed-v1"},
            {"$set": {"buffer_seconds": elapsed}},
        )
        print(f"[OK] building buffers updated: {count}")
        print(f"[OK] buffer seconds: {elapsed}")
        return 0

    except Exception as exc:
        print(f"[FAIL] buffer generation failed: {exc}")
        return 1

    finally:
        client.close()


if __name__ == "__main__":
    sys.exit(main())