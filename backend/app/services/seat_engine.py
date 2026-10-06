"""Exam seating: min Manhattan distance; same paper_id cannot be 4-neighbor adjacent.

锁位（locks）：被锁考生必须留在原格，排座时锁位预占。
- 保锁：锁格只放锁主，其余考生绕开，绝不拆锁硬排别人。
- 若锁位本身在当前约束下已不合法（越界、重复、锁间距离不足、同卷四邻相邻），
  抛 PlacementError —— 整场失败，由上层决定不新增方案。
"""
from __future__ import annotations

from dataclasses import asdict, dataclass


class PlacementError(Exception):
    """锁位在当前约束下不合法，整场排座失败（保锁与拆锁硬排互斥）。"""


@dataclass
class SeatAssign:
    candidate_id: int
    name: str
    ticket_no: str
    paper_id: int
    row: int
    col: int
    locked: bool = False


@dataclass
class Lock:
    candidate_id: int
    row: int
    col: int


@dataclass
class Violation:
    kind: str
    a_id: int
    b_id: int
    detail: str


def manhattan(a: tuple[int, int], b: tuple[int, int]) -> int:
    return abs(a[0] - b[0]) + abs(a[1] - b[1])


def neighbors4(r: int, c: int, rows: int, cols: int) -> list[tuple[int, int]]:
    out = []
    for dr, dc in ((0, 1), (0, -1), (1, 0), (-1, 0)):
        nr, nc = r + dr, c + dc
        if 0 <= nr < rows and 0 <= nc < cols:
            out.append((nr, nc))
    return out


def _assign_for(cand: dict, row: int, col: int, locked: bool) -> SeatAssign:
    return SeatAssign(cand["id"], cand["name"], cand["ticket_no"], cand["paper_id"], row, col, locked)


def validate_locks(rows: int, cols: int, min_dist: int,
                   candidates: list[dict], locks: list[Lock]) -> dict[int, SeatAssign]:
    """校验锁位并生成锁考生的 SeatAssign（预占）。

    锁位必须属于本考室考生、不越界、不重复，且锁与锁之间满足最小间距与同卷不四邻。
    任一条件不满足即抛 PlacementError —— 不允许通过拆掉锁位来硬排。
    """
    by_id = {c["id"]: c for c in candidates}
    locked: dict[int, SeatAssign] = {}
    pos_owner: dict[tuple[int, int], int] = {}
    for lk in locks:
        cand = by_id.get(lk.candidate_id)
        if cand is None:
            raise PlacementError(f"锁定的考生 {lk.candidate_id} 不在本考室考生名单中")
        if not (0 <= lk.row < rows and 0 <= lk.col < cols):
            raise PlacementError(
                f"考生 {cand['name']} 的锁位 ({lk.row},{lk.col}) 越出 {rows}x{cols} 考室网格")
        if lk.candidate_id in locked:
            raise PlacementError(f"考生 {cand['name']} 被重复锁定")
        if (lk.row, lk.col) in pos_owner:
            other = by_id[pos_owner[(lk.row, lk.col)]]["name"]
            raise PlacementError(f"锁位 ({lk.row},{lk.col}) 同时锁定给 {other} 与 {cand['name']}")
        new_assign = _assign_for(cand, lk.row, lk.col, True)
        # 锁与锁之间也必须合法，否则新约束下锁位已不合法
        for other in locked.values():
            d = manhattan((lk.row, lk.col), (other.row, other.col))
            if d < min_dist:
                raise PlacementError(
                    f"最小间距 {min_dist} 下，锁位考生 {cand['name']} 与 {other.name} 距离仅 {d}，锁位已不合法")
            if new_assign.paper_id == other.paper_id and (other.row, other.col) in neighbors4(
                    lk.row, lk.col, rows, cols):
                raise PlacementError(
                    f"锁位考生 {cand['name']} 与 {other.name} 同试卷套 {new_assign.paper_id} 且四邻相邻，锁位已不合法")
        locked[lk.candidate_id] = new_assign
        pos_owner[(lk.row, lk.col)] = lk.candidate_id
    return locked


def place_candidates(rows: int, cols: int, min_dist: int, candidates: list[dict],
                     locks: list[Lock] | None = None) -> tuple[list[SeatAssign], list[dict]]:
    """Greedy: try seats row-major; accept if manhattan >= min_dist to all placed AND no same paper 4-neigh.

    提供 locks 时：先校验锁位（不合法抛 PlacementError，绝不拆锁硬排），
    锁考生预占原格，其余考生绕开锁格、并与锁考生同样满足间距与同卷约束。
    锁格绝不分给别人，锁考生绝不进 unplaced。
    """
    locks = locks or []
    locked = validate_locks(rows, cols, min_dist, candidates, locks)
    occupied: dict[tuple[int, int], SeatAssign] = {}
    for assign in locked.values():
        occupied[(assign.row, assign.col)] = assign
    unplaced: list[dict] = []
    for cand in candidates:
        if cand["id"] in locked:
            continue
        placed = False
        for r in range(rows):
            for c in range(cols):
                if (r, c) in occupied:
                    continue
                ok = True
                for pos in occupied:
                    if manhattan((r, c), pos) < min_dist:
                        ok = False
                        break
                if not ok:
                    continue
                for nr, nc in neighbors4(r, c, rows, cols):
                    if (nr, nc) in occupied and occupied[(nr, nc)].paper_id == cand["paper_id"]:
                        ok = False
                        break
                if not ok:
                    continue
                occupied[(r, c)] = _assign_for(cand, r, c, False)
                placed = True
                break
            if placed:
                break
        if not placed:
            unplaced.append(cand)
    assigns = [locked[c["id"]] for c in candidates if c["id"] in locked]
    assigns += [a for a in occupied.values() if not a.locked]
    return assigns, unplaced


def find_violations(rows: int, cols: int, min_dist: int, assigns: list[SeatAssign]) -> list[Violation]:
    viols: list[Violation] = []
    for i, a in enumerate(assigns):
        for b in assigns[i + 1:]:
            d = manhattan((a.row, a.col), (b.row, b.col))
            if d < min_dist:
                viols.append(Violation("distance", a.candidate_id, b.candidate_id,
                                       f"曼哈顿距离 {d} < 最小要求 {min_dist}"))
            if a.paper_id == b.paper_id and (b.row, b.col) in neighbors4(a.row, a.col, rows, cols):
                viols.append(Violation("same_paper_adjacent", a.candidate_id, b.candidate_id,
                                       f"同试卷套 {a.paper_id} 四邻相邻"))
    return viols


def locks_to_list(locks: list[Lock]) -> list[dict]:
    return [asdict(lk) for lk in locks]


def plan_to_dict(assigns: list[SeatAssign], unplaced: list[dict], viols: list[Violation],
                 rows: int, cols: int, locks: list[Lock] | None = None) -> dict:
    locks = locks or []
    return {
        "rows": rows,
        "cols": cols,
        "assignments": [asdict(a) for a in assigns],
        "unplaced": unplaced,
        "violations": [asdict(v) for v in viols],
        "locks": locks_to_list(locks),
        "stats": {
            "seated": len(assigns),
            "unplaced": len(unplaced),
            "violations": len(viols),
            "locked": len(locks),
            "capacity": rows * cols,
        },
    }
