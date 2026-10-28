import os
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
QUERIES = [
    "01_write.py",
    "02_nearby.py",
    "03_within.py",
    "04_contains.py",
    "05_coverage.py",
    "06_heatmap.py",
    "07_anomalies.py",
    "08_status.py",
]


def run(script: Path) -> tuple[int, str]:
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    completed = subprocess.run(
        [sys.executable, str(script)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        env=env,
    )
    output = (completed.stdout or "") + (completed.stderr or "")
    return completed.returncode, output


def emit(text: str) -> None:
    sys.stdout.buffer.write(text.encode("utf-8", errors="replace"))
    if not text.endswith("\n"):
        sys.stdout.buffer.write(b"\n")


def main() -> int:
    chunks = []
    failed = False
    code, output = run(ROOT / "scripts" / "measure_storage.py")
    chunks.append(f"===== storage exit {code} =====\n{output}")
    failed = failed or code != 0
    emit(output)
    for name in QUERIES:
        code, output = run(ROOT / "scripts" / "queries" / name)
        chunks.append(f"===== {name} exit {code} =====\n{output}")
        failed = failed or code != 0
        emit(output)
    text = "\n".join(chunks)
    path = ROOT / "results" / "acceptance.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    emit(str(path))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
