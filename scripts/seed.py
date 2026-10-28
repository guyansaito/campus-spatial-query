import argparse
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def run(args: list[str]) -> None:
    print(">>", " ".join(args), flush=True)
    completed = subprocess.run(args, cwd=ROOT)
    if completed.returncode != 0:
        raise SystemExit(completed.returncode)


def main() -> int:
    parser = argparse.ArgumentParser(description="初始化集合并灌入可重复的种子数据")
    parser.add_argument("--bike-days", type=float, default=3.0)
    parser.add_argument("--bikes", type=int, default=2000)
    args = parser.parse_args()
    python = sys.executable
    run([python, str(ROOT / "scripts" / "init_db.py")])
    run(
        [
            python,
            str(ROOT / "scripts" / "generate_static_seed.py"),
            "--output",
            str(ROOT / "data" / "seed"),
        ]
    )
    run(
        [
            python,
            str(ROOT / "scripts" / "validate_static_seed.py"),
            str(ROOT / "data" / "seed"),
        ]
    )
    run([python, str(ROOT / "scripts" / "import_static_seed.py")])
    run([python, str(ROOT / "scripts" / "build_building_buffers.py")])
    run(
        [
            python,
            str(ROOT / "scripts" / "generate_bike_reports.py"),
            "--days",
            str(args.bike_days),
            "--bikes",
            str(args.bikes),
        ]
    )
    print()
    print("种子数据已经写入本机 MongoDB。")
    print("提交作业时不要打包数据库，也不要提交 Docker volume。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
