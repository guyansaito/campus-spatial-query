"""50 个并发客户端做附近查找，统计吞吐和 P95/P99。"""

import argparse
import http.client
import json
import math
import random
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from spatial import geo


def percentile(sorted_values: list[float], percent: float) -> float | None:
    if not sorted_values:
        return None
    index = math.ceil(percent / 100 * len(sorted_values)) - 1
    index = min(len(sorted_values) - 1, max(0, index))
    return sorted_values[index]


def summarize(latencies: list[float], errors: int, elapsed: float) -> dict:
    ordered = sorted(latencies)
    return {
        "requests": len(latencies),
        "errors": errors,
        "elapsed_seconds": round(elapsed, 3),
        "throughput_rps": round(len(latencies) / elapsed, 2) if elapsed else 0,
        "avg_ms": round(sum(latencies) / len(latencies), 3) if latencies else None,
        "p50_ms": percentile(ordered, 50),
        "p95_ms": percentile(ordered, 95),
        "p99_ms": percentile(ordered, 99),
        "max_ms": ordered[-1] if ordered else None,
    }


def per_second(samples: list[tuple[int, float]]) -> list[dict]:
    buckets: dict[int, list[float]] = {}
    for second, latency in samples:
        buckets.setdefault(second, []).append(latency)
    rows = []
    for second in sorted(buckets):
        ordered = sorted(buckets[second])
        rows.append(
            {
                "second": second,
                "count": len(ordered),
                "p95_ms": percentile(ordered, 95),
            }
        )
    return rows


def http_worker(index: int, host: str, port: int, warmup_end: float, deadline: float):
    rng = random.Random(20260301 + index)
    connection = http.client.HTTPConnection(host, port, timeout=30)
    latencies = []
    samples = []
    errors = 0
    types = geo.FACILITY_TYPES
    try:
        while time.perf_counter() < deadline:
            lon = rng.uniform(geo.MIN_LON, geo.MAX_LON)
            lat = rng.uniform(geo.MIN_LAT, geo.MAX_LAT)
            facility_type = types[rng.randrange(len(types))]
            path = (
                "/facilities/nearby"
                f"?longitude={lon:.7f}&latitude={lat:.7f}"
                f"&radius_m=500&facility_type={facility_type}&limit=10"
            )
            started = time.perf_counter()
            status = 0
            try:
                connection.request("GET", path)
                response = connection.getresponse()
                response.read()
                status = response.status
            except Exception:
                errors += 1
                connection.close()
                connection = http.client.HTTPConnection(host, port, timeout=30)
                continue
            elapsed_ms = (time.perf_counter() - started) * 1000
            now = time.perf_counter()
            if now < warmup_end:
                continue
            if status != 200:
                errors += 1
                continue
            latencies.append(elapsed_ms)
            samples.append((int(time.time()), elapsed_ms))
    finally:
        connection.close()
    return latencies, samples, errors


def direct_worker(index: int, database, warmup_end: float, deadline: float):
    from spatial import service

    rng = random.Random(20260301 + index)
    latencies = []
    samples = []
    errors = 0
    types = geo.FACILITY_TYPES
    while time.perf_counter() < deadline:
        lon = rng.uniform(geo.MIN_LON, geo.MAX_LON)
        lat = rng.uniform(geo.MIN_LAT, geo.MAX_LAT)
        facility_type = types[rng.randrange(len(types))]
        started = time.perf_counter()
        try:
            service.nearby_facilities(
                database,
                lon,
                lat,
                radius_m=500,
                facility_type=facility_type,
                limit=10,
            )
        except Exception:
            errors += 1
            continue
        elapsed_ms = (time.perf_counter() - started) * 1000
        now = time.perf_counter()
        if now < warmup_end:
            continue
        latencies.append(elapsed_ms)
        samples.append((int(time.time()), elapsed_ms))
    return latencies, samples, errors


def run_pool(workers, concurrency: int):
    from concurrent.futures import ThreadPoolExecutor

    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        return list(pool.map(lambda index: workers(index), range(concurrency)))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--concurrency", type=int, default=50)
    parser.add_argument("--seconds", type=float, default=600)
    parser.add_argument("--warmup", type=float, default=20)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--direct-seconds", type=float, default=0)
    args = parser.parse_args()

    probe = http.client.HTTPConnection(args.host, args.port, timeout=5)
    try:
        probe.request("GET", "/health")
        response = probe.getresponse()
        body = response.read()
        if response.status != 200:
            print(f"[FAIL] API /health -> {response.status} {body[:200]!r}")
            return 2
    except Exception as exc:
        print(f"[FAIL] API 没起来: {exc}")
        print("先运行: .\\.venv\\Scripts\\python.exe -m uvicorn api.main:app --host 127.0.0.1 --port 8000")
        return 2
    finally:
        probe.close()

    print(
        f"[bench] HTTP {args.concurrency} 并发，预热 {args.warmup} s，测量 {args.seconds} s",
        flush=True,
    )
    warmup_end = time.perf_counter() + args.warmup
    deadline = warmup_end + args.seconds
    started = time.perf_counter()
    parts = run_pool(
        lambda index: http_worker(index, args.host, args.port, warmup_end, deadline),
        args.concurrency,
    )
    measured = time.perf_counter() - started - args.warmup
    latencies = [item for part in parts for item in part[0]]
    samples = [item for part in parts for item in part[1]]
    errors = sum(part[2] for part in parts)
    http_summary = summarize(latencies, errors, max(measured, 0.001))
    http_summary["concurrency"] = args.concurrency
    http_summary["warmup_seconds"] = args.warmup
    http_summary["mode"] = "http"

    direct_summary = None
    if args.direct_seconds > 0:
        from spatial.db import get_database

        database = get_database()
        print(f"[bench] 直接查 MongoDB {args.direct_seconds} s", flush=True)
        warmup_end = time.perf_counter() + min(5, args.warmup)
        deadline = warmup_end + args.direct_seconds
        started = time.perf_counter()
        parts = run_pool(
            lambda index: direct_worker(index, database, warmup_end, deadline),
            args.concurrency,
        )
        measured = time.perf_counter() - started - min(5, args.warmup)
        direct_lat = [item for part in parts for item in part[0]]
        direct_err = sum(part[2] for part in parts)
        direct_summary = summarize(direct_lat, direct_err, max(measured, 0.001))
        direct_summary["concurrency"] = args.concurrency
        direct_summary["mode"] = "pymongo"

    payload = {"http": http_summary, "direct": direct_summary, "per_second": per_second(samples)}
    out_dir = ROOT / "results"
    out_dir.mkdir(parents=True, exist_ok=True)
    summary_path = out_dir / "bench_summary.json"
    summary_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    series_path = out_dir / "bench_per_second.csv"
    with series_path.open("w", encoding="utf-8") as file:
        file.write("second,count,p95_ms\n")
        for row in payload["per_second"]:
            file.write(f"{row['second']},{row['count']},{row['p95_ms']}\n")
    text = (
        f"concurrency={args.concurrency}\n"
        f"requests={http_summary['requests']}\n"
        f"errors={http_summary['errors']}\n"
        f"throughput_rps={http_summary['throughput_rps']}\n"
        f"p50_ms={http_summary['p50_ms']}\n"
        f"p95_ms={http_summary['p95_ms']}\n"
        f"p99_ms={http_summary['p99_ms']}\n"
        f"max_ms={http_summary['max_ms']}\n"
    )
    (out_dir / "bench_output.txt").write_text(text, encoding="utf-8")
    print(text)
    if direct_summary:
        print(
            f"[direct] throughput {direct_summary['throughput_rps']} rps  "
            f"p95 {direct_summary['p95_ms']} ms  p99 {direct_summary['p99_ms']} ms"
        )
    print(summary_path)
    return 0 if http_summary["errors"] == 0 and http_summary["requests"] > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
