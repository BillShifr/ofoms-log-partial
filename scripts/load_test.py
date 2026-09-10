"""Лёгкий нагрузочный прогон против dev-сервера (Этап 7).

Только стандартная библиотека: многопоточный HTTP-клиент с замерами
латентности и агрегатами (qps, p50/p95/p99, ошибки).

Пример:
    python scripts/load_test.py --base http://127.0.0.1:8123 --workers 16 --per-worker 50
"""

import argparse
import random
import statistics
import threading
import time
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

DEFAULT_PATHS = [
    "/accounts/login/",
    "/healthz",
    "/static/css/portal.css",
]

_HEADERS = {"User-Agent": "load-test/1.0 (phase-7)"}


def _request_once(base, path):
    start = time.perf_counter()
    try:
        with urlopen(Request(base + path, headers=_HEADERS), timeout=15) as resp:
            code = resp.status
    except (HTTPError, URLError):
        code = 0
    return start, time.perf_counter() - start, code


def _worker(base, paths, count, results, errors):
    for _ in range(count):
        path = random.choice(paths)
        start, elapsed, code = _request_once(base, path)
        results.append(elapsed)
        if code not in (200, 302):
            errors.append((code, path))


def _percentile(sorted_values, pct):
    if not sorted_values:
        return 0.0
    idx = min(len(sorted_values) - 1, int(len(sorted_values) * pct / 100))
    return sorted_values[idx]


def main():
    parser = argparse.ArgumentParser(description="Нагрузочный прогон (Этап 7)")
    parser.add_argument("--base", default="http://127.0.0.1:8123")
    parser.add_argument("--workers", type=int, default=16)
    parser.add_argument("--per-worker", type=int, default=50)
    parser.add_argument("--paths", nargs="*", default=DEFAULT_PATHS)
    args = parser.parse_args()

    results = []
    errors = []
    threads = [
        threading.Thread(
            target=_worker,
            args=(args.base.rstrip("/"), args.paths, args.per_worker, results, errors),
        )
        for _ in range(args.workers)
    ]
    started = time.perf_counter()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    wall = time.perf_counter() - started

    total = len(results)
    errors_rate = len(errors) / total * 100 if total else 100.0
    order = sorted(results)
    print(f"Запросов: {total}  Время: {wall:.1f} с  QPS: {total / wall:.1f}")
    if order:
        print(
            f"Латентность, мс: avg={statistics.mean(order) * 1000:.1f} "
            f"p50={_percentile(order, 50) * 1000:.1f} "
            f"p95={_percentile(order, 95) * 1000:.1f} "
            f"p99={_percentile(order, 99) * 1000:.1f}"
        )
    print(f"Ошибки: {len(errors)} ({errors_rate:.1f}%)")
    for code, path in errors[:10]:
        print(f"  {code} {path}")
    if errors_rate >= 5.0:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
