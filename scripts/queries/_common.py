import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spatial.db import get_database
from spatial.serialize import to_jsonable


def database():
    db = get_database()
    db.client.admin.command("ping")
    return db


def save(name: str, payload: dict) -> Path:
    path = ROOT / "results" / "queries" / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(to_jsonable(payload), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return path


def repeat(func, times: int = 5):
    samples = []
    result = None
    for _ in range(times):
        started = time.perf_counter()
        result = func()
        samples.append(round((time.perf_counter() - started) * 1000, 2))
    ordered = sorted(samples)
    middle = ordered[len(ordered) // 2]
    return result, {
        "runs_ms": samples,
        "min_ms": ordered[0],
        "median_ms": middle,
        "max_ms": ordered[-1],
    }


def show(title: str, timings: dict, extra: str = "") -> None:
    print(f"[{title}] median {timings['median_ms']} ms  runs {timings['runs_ms']}")
    if extra:
        print(extra)
