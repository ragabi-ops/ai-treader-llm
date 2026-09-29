#!/usr/bin/env python3
"""Validate the CSV task authority and select the next local task."""
import csv
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKLOG = ROOT / "tasks" / "BACKLOG.csv"
LOCAL = "ai-treader-llm"
STATUSES = {"done", "not_started", "in_progress", "blocked", "done_pending_signoff"}
TYPES = {"task", "decision", "cross_repo"}


def dependencies(row):
    return [item.strip() for item in row["dependencies"].split(",") if item.strip()]


def main():
    try:
        with BACKLOG.open(newline="", encoding="utf-8") as source:
            rows = list(csv.DictReader(source))
        ids = [row["id"] for row in rows]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate task IDs")
        by_id = {row["id"]: row for row in rows}
        orders = []
        for row in rows:
            ident = row["id"]
            if row["status"] not in STATUSES:
                raise ValueError(f"{ident}: invalid status {row['status']}")
            if row["task_type"] not in TYPES:
                raise ValueError(f"{ident}: invalid task_type {row['task_type']}")
            if row["repository"] not in {LOCAL, "ai-treader-platform"}:
                raise ValueError(f"{ident}: invalid repository {row['repository']}")
            order = int(row["execution_order"]) if row["execution_order"] else None
            if row["repository"] == LOCAL and row["status"] != "done" and order is None:
                raise ValueError(f"{ident}: unfinished local task needs execution_order")
            if row["repository"] != LOCAL and order is not None:
                raise ValueError(f"{ident}: external mirror row must not own execution_order")
            if order is not None:
                if order <= 0:
                    raise ValueError(f"{ident}: execution_order must be positive")
                orders.append(order)
            unknown = [dep for dep in dependencies(row) if dep not in by_id]
            if unknown:
                raise ValueError(f"{ident}: unknown dependencies: {', '.join(unknown)}")
        if len(orders) != len(set(orders)):
            raise ValueError("execution_order values must be unique")
        queue = sorted(
            (row for row in rows if row["repository"] == LOCAL and row["status"] != "done"),
            key=lambda row: int(row["execution_order"]),
        )
        selected = queue[0] if queue else None
        expected = selected["id"] if selected else "none"
        status = (ROOT / "STATUS.md").read_text(encoding="utf-8")
        pointer = re.search(r"\*\*Next task: ([A-Za-z0-9]+)\b", status)
        if not pointer or pointer.group(1) != expected:
            raise ValueError(f"STATUS.md must say '**Next task: {expected}'")
        print("PASS: backlog IDs, repositories, statuses, orders, dependencies and STATUS pointer")
        if selected:
            pending = [dep for dep in dependencies(selected) if by_id[dep]["status"] != "done"]
            print(f"NEXT: {selected['id']} ({selected['status']}) — {selected['deliverable']}")
            if pending or selected["status"] == "blocked":
                print("BLOCKED: " + (", ".join(pending) if pending else selected["notes"]))
                return 1
            print("ACCEPTANCE: " + selected["acceptance"])
        return 0
    except (OSError, ValueError, KeyError) as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
