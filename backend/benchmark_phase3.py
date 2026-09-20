"""Repeatable Phase 3 acceptance benchmark.

Run from ``backend`` with:
    python benchmark_phase3.py

It creates an isolated 300-row batch (299 valid image copies plus one
deliberately unreadable JPEG), runs the real worker pool, and asserts the
database result.  The benchmark batch is retained so its job progress and
photo rows can be inspected afterwards.
"""

from __future__ import annotations

import shutil
import sqlite3
import time
import os
import json
import threading
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from pathlib import Path
from uuid import uuid4

from db import DB_PATH, init_db


ROOT = Path(__file__).resolve().parent.parent
UPLOADS = ROOT / "uploads" / "originals"
os.environ.setdefault("UPLOAD_DIR", str(UPLOADS))


def main() -> None:
    init_db()
    source = next(path for path in UPLOADS.glob("*/*") if path.is_file())
    batch_id = f"benchmark-{uuid4()}"
    batch_dir = UPLOADS / batch_id
    batch_dir.mkdir(parents=True)

    conn = sqlite3.connect(DB_PATH)
    try:
        for number in range(299):
            photo_id = str(uuid4())
            filename = f"benchmark-{number}{source.suffix.lower()}"
            shutil.copyfile(source, batch_dir / f"{photo_id}{source.suffix.lower()}")
            conn.execute(
                "INSERT INTO photos (id, filename, batch_id, status) VALUES (?, ?, ?, 'review')",
                (photo_id, filename, batch_id),
            )

        corrupt_id = str(uuid4())
        (batch_dir / f"{corrupt_id}.jpg").write_bytes(b"not an image")
        conn.execute(
            "INSERT INTO photos (id, filename, batch_id, status) VALUES (?, ?, ?, 'review')",
            (corrupt_id, "corrupt.jpg", batch_id),
        )
        conn.commit()
    finally:
        conn.close()

    # Exercise the real HTTP contract.  BackgroundTasks sends the 202 response
    # before it invokes the worker, unlike in-process TestClient shortcuts.
    import uvicorn
    from main import app

    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=8765, log_level="error"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(100):
        try:
            urlopen("http://127.0.0.1:8765/health", timeout=0.2).read()
            break
        except OSError:
            time.sleep(0.05)
    else:
        raise RuntimeError("acceptance server did not start")

    started = time.perf_counter()
    request = Request(
        f"http://127.0.0.1:8765/batches/{batch_id}/analyze", method="POST"
    )
    with urlopen(request, timeout=5) as response:
        start_payload = json.load(response)
    post_seconds = time.perf_counter() - started
    assert start_payload["status"] == "started" and post_seconds < 1, (start_payload, post_seconds)
    try:
        urlopen(request, timeout=5)
        raise AssertionError("second analyze request unexpectedly started")
    except HTTPError as exc:
        assert exc.code == 409 and b"already" in exc.read().lower(), exc.code

    observed_progress = []
    while True:
        with urlopen(f"http://127.0.0.1:8765/batches/{batch_id}/status", timeout=5) as response:
            status = json.load(response)
        observed_progress.append(status["processed"])
        if status["status"] in ("completed", "failed"):
            break
        time.sleep(0.05)
    elapsed = time.perf_counter() - started
    server.should_exit = True
    thread.join(timeout=5)

    conn = sqlite3.connect(DB_PATH)
    try:
        job = conn.execute(
            "SELECT status, total, processed, failed FROM jobs WHERE batch_id = ?",
            (batch_id,),
        ).fetchone()
        populated = conn.execute(
            """SELECT COUNT(*) FROM photos WHERE batch_id = ?
               AND processing_error IS NULL
               AND sharpness_score IS NOT NULL
               AND mean_brightness IS NOT NULL
               AND face_count IS NOT NULL
               AND closed_eyes_detected IS NOT NULL""",
            (batch_id,),
        ).fetchone()[0]
        corrupt = conn.execute(
            "SELECT processing_error, status FROM photos WHERE id = ?", (corrupt_id,)
        ).fetchone()
    finally:
        conn.close()

    assert job == ("completed", 300, 299, 1), job
    assert populated == 299, populated
    assert corrupt[0] and corrupt[1] == "error", corrupt
    assert any(0 < value < 299 for value in observed_progress), observed_progress
    print(
        f"PASS batch={batch_id} post_seconds={post_seconds:.3f} "
        f"elapsed_seconds={elapsed:.2f} valid=299 failed=1"
    )


if __name__ == "__main__":
    main()
