"""统计与违规接口的整形：直接采用方案快照里的真实数字，不做页侧加工。

锁名单人数、图上带锁格、统计锁定必须同一套数：
- seated / unplaced / violations / capacity 取自最新方案快照；
- locked 由调用方按当前锁表覆盖（见 seating.stats），与锁名单保持一致。
"""
from __future__ import annotations


def _as_int(v, fallback=0):
    try:
        return int(v)
    except (TypeError, ValueError):
        return fallback


def mix_stats(data: dict, stats: dict | None = None) -> dict:
    base = dict(stats or data.get("stats") or {})
    return {
        "seated": _as_int(base.get("seated")),
        "unplaced": _as_int(base.get("unplaced")),
        "violations": _as_int(base.get("violations")),
        "locked": _as_int(base.get("locked")),
        "capacity": _as_int(base.get("capacity")),
    }


def mix_violations(data: dict) -> dict:
    return {
        "violations": list(data.get("violations") or []),
        "unplaced": list(data.get("unplaced") or []),
    }
