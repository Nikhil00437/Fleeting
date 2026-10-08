"""#170 time-estimate accuracy: predicted vs. actual time on tasks."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ..db import Database


def calculate_estimate_accuracy(db: Database) -> dict:
    """Analyze accuracy of task time estimates against actual tracked focus time.

    Compares `estimate_min` (predicted) to `spent_min` (actual focus time from #280).
    Categorizes tasks into under-estimated, over-estimated, or on-target,
    and calculates mean absolute deviation and priority breakdown.
    """
    rows = db.execute(
        """
        SELECT id, text, done, priority, due_date, estimate_min, spent_min, repo, created_at, completed_at
        FROM tasks
        WHERE (estimate_min IS NOT NULL AND estimate_min > 0)
           OR (spent_min IS NOT NULL AND spent_min > 0)
        ORDER BY completed_at DESC, created_at DESC
        """
    ).fetchall()

    evaluated_items = []
    untracked_count = 0

    counts = {"on_target": 0, "underestimated": 0, "overestimated": 0}
    by_priority: dict[str, dict] = {
        "P1": {"count": 0, "estimated_min": 0, "spent_min": 0, "accuracy_pct": 0.0},
        "P2": {"count": 0, "estimated_min": 0, "spent_min": 0, "accuracy_pct": 0.0},
        "P3": {"count": 0, "estimated_min": 0, "spent_min": 0, "accuracy_pct": 0.0},
    }

    total_estimated_min = 0
    total_spent_min = 0
    total_abs_error = 0
    ratios = []

    for r in rows:
        est = r["estimate_min"] or 0
        spent = r["spent_min"] or 0

        if est > 0 and spent > 0:
            diff = spent - est
            ratio = round(spent / est, 2)
            max_val = max(spent, est)
            accuracy_pct = round(max(0.0, 100.0 * (1.0 - abs(diff) / max_val)), 1) if max_val > 0 else 100.0

            if spent > est * 1.15:
                status = "underestimated"
                counts["underestimated"] += 1
            elif spent < est * 0.85:
                status = "overestimated"
                counts["overestimated"] += 1
            else:
                status = "on_target"
                counts["on_target"] += 1

            total_estimated_min += est
            total_spent_min += spent
            total_abs_error += abs(diff)
            ratios.append(spent / est)

            prio = r["priority"] or "P2"
            if prio in by_priority:
                by_priority[prio]["count"] += 1
                by_priority[prio]["estimated_min"] += est
                by_priority[prio]["spent_min"] += spent

            evaluated_items.append(
                {
                    "id": r["id"],
                    "text": r["text"],
                    "done": r["done"],
                    "priority": prio,
                    "due_date": r["due_date"],
                    "estimate_min": est,
                    "spent_min": spent,
                    "diff_min": diff,
                    "ratio": ratio,
                    "accuracy_pct": accuracy_pct,
                    "status": status,
                    "repo": r["repo"],
                    "created_at": r["created_at"],
                    "completed_at": r["completed_at"],
                }
            )
        elif est > 0 and spent == 0:
            untracked_count += 1

    total_evaluated = len(evaluated_items)
    if total_evaluated > 0:
        max_total = max(total_spent_min, total_estimated_min)
        overall_accuracy_pct = (
            round(max(0.0, 100.0 * (1.0 - abs(total_spent_min - total_estimated_min) / max_total)), 1)
            if max_total > 0
            else 100.0
        )
        avg_error_min = round(total_abs_error / total_evaluated, 1)
        average_ratio = round(sum(ratios) / total_evaluated, 2)

        if average_ratio > 1.15:
            bias = "underestimating"
        elif average_ratio < 0.85:
            bias = "overestimating"
        else:
            bias = "accurate"

        for p_data in by_priority.values():
            if p_data["count"] > 0:
                p_max = max(p_data["spent_min"], p_data["estimated_min"])
                p_data["accuracy_pct"] = (
                    round(max(0.0, 100.0 * (1.0 - abs(p_data["spent_min"] - p_data["estimated_min"]) / p_max)), 1)
                    if p_max > 0
                    else 100.0
                )
    else:
        overall_accuracy_pct = 0.0
        avg_error_min = 0.0
        average_ratio = 1.0
        bias = "no_data"

    return {
        "total_evaluated": total_evaluated,
        "untracked_count": untracked_count,
        "total_estimated_min": total_estimated_min,
        "total_spent_min": total_spent_min,
        "avg_error_min": avg_error_min,
        "overall_accuracy_pct": overall_accuracy_pct,
        "average_ratio": average_ratio,
        "bias": bias,
        "counts": counts,
        "by_priority": by_priority,
        "items": evaluated_items[:50],
    }
