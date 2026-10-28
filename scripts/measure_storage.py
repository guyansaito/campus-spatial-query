"""统计库体积、索引体积和 MongoDB 内存。"""

import json
import os
import platform
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spatial.db import get_client, mongo_settings
from spatial.schema import COLLECTIONS
from spatial.serialize import to_jsonable


def memory_bytes() -> dict:
    if os.name != "nt":
        return {}
    import ctypes

    class MEMORYSTATUSEX(ctypes.Structure):
        _fields_ = [
            ("dwLength", ctypes.c_ulong),
            ("dwMemoryLoad", ctypes.c_ulong),
            ("ullTotalPhys", ctypes.c_ulonglong),
            ("ullAvailPhys", ctypes.c_ulonglong),
            ("ullTotalPageFile", ctypes.c_ulonglong),
            ("ullAvailPageFile", ctypes.c_ulonglong),
            ("ullTotalVirtual", ctypes.c_ulonglong),
            ("ullAvailVirtual", ctypes.c_ulonglong),
            ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
        ]

    status = MEMORYSTATUSEX()
    status.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))
    return {
        "total_bytes": int(status.ullTotalPhys),
        "available_bytes": int(status.ullAvailPhys),
    }


def main() -> int:
    client = get_client()
    settings = mongo_settings()
    database = client[settings["database"]]
    client.admin.command("ping")
    server = client.admin.command("serverStatus")
    db_stats = database.command("dbStats")
    collections = {}
    for name in COLLECTIONS:
        if name not in database.list_collection_names():
            continue
        stats = database.command("collStats", name)
        collections[name] = {
            "count": stats.get("count"),
            "size": stats.get("size"),
            "storageSize": stats.get("storageSize"),
            "totalIndexSize": stats.get("totalIndexSize"),
            "avgObjSize": stats.get("avgObjSize"),
        }
    cache = {}
    wired = server.get("wiredTiger", {}).get("cache", {})
    if wired:
        cache = {
            "bytes_in_cache": wired.get("bytes currently in the cache"),
            "max_bytes": wired.get("maximum bytes configured"),
        }
    disk = shutil.disk_usage(ROOT)
    payload = {
        "host": {
            "system": platform.platform(),
            "processor": platform.processor(),
            "cpu_count": os.cpu_count(),
            "python": platform.python_version(),
            "memory": memory_bytes(),
        },
        "disk": {
            "path": str(ROOT),
            "total": disk.total,
            "used": disk.used,
            "free": disk.free,
        },
        "mongodb": {
            "version": client.server_info().get("version"),
            "resident_mb": server.get("mem", {}).get("resident"),
            "virtual_mb": server.get("mem", {}).get("virtual"),
            "cache": cache,
        },
        "database": {
            "name": database.name,
            "collections": db_stats.get("collections"),
            "objects": db_stats.get("objects"),
            "dataSize": db_stats.get("dataSize"),
            "storageSize": db_stats.get("storageSize"),
            "indexSize": db_stats.get("indexSize"),
            "totalSize": db_stats.get("totalSize"),
        },
        "collections": collections,
    }
    path = ROOT / "results" / "storage.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(to_jsonable(payload), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    data_mb = (payload["database"].get("dataSize") or 0) / 1024 / 1024
    index_mb = (payload["database"].get("indexSize") or 0) / 1024 / 1024
    storage_mb = (payload["database"].get("storageSize") or 0) / 1024 / 1024
    print(f"[存储] data {data_mb:.1f} MB  storage {storage_mb:.1f} MB  index {index_mb:.1f} MB")
    print(f"[内存] mongod resident {payload['mongodb']['resident_mb']} MB")
    print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
