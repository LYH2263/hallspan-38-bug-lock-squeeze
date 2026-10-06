from app.services.seat_engine import (
    Lock,
    PlacementError,
    find_violations,
    manhattan,
    place_candidates,
    SeatAssign,
)
import pytest


def _cands(n: int, papers: int = 3) -> list[dict]:
    return [{"id": i + 1, "name": f"C{i + 1}", "ticket_no": f"T{i + 1}",
             "paper_id": 1 + (i % papers)} for i in range(n)]


def _pos(assigns, cid):
    return next((a.row, a.col) for a in assigns if a.candidate_id == cid)


def test_manhattan():
    assert manhattan((0, 0), (2, 1)) == 3

def test_min_distance_placement():
    cands = [{"id": i, "name": f"C{i}", "ticket_no": f"T{i}", "paper_id": 1 + (i % 2)} for i in range(4)]
    assigns, unplaced = place_candidates(4, 4, 2, cands)
    assert len(assigns) + len(unplaced) == 4
    for i, a in enumerate(assigns):
        for b in assigns[i+1:]:
            assert manhattan((a.row, a.col), (b.row, b.col)) >= 2

def test_same_paper_not_adjacent_in_result():
    # Force two same paper — engine should avoid 4-neigh
    cands = [
        {"id": 1, "name": "A", "ticket_no": "T1", "paper_id": 1},
        {"id": 2, "name": "B", "ticket_no": "T2", "paper_id": 1},
        {"id": 3, "name": "C", "ticket_no": "T3", "paper_id": 2},
    ]
    assigns, _ = place_candidates(3, 3, 1, cands)
    viols = find_violations(3, 3, 1, assigns)
    assert not any(v.kind == "same_paper_adjacent" for v in viols)

def test_violation_detection():
    assigns = [
        SeatAssign(1, "A", "T1", 1, 0, 0),
        SeatAssign(2, "B", "T2", 1, 0, 1),
    ]
    viols = find_violations(2, 2, 2, assigns)
    kinds = {v.kind for v in viols}
    assert "distance" in kinds
    assert "same_paper_adjacent" in kinds


def test_locked_corner_candidate_keeps_seat_on_rerun():
    # 先排一次，取落在左上角 (0,0) 的考生，将其锁在边角后再排：行列必须不变
    assigns0, _ = place_candidates(5, 6, 2, _cands(12))
    corner = next(a for a in assigns0 if (a.row, a.col) == (0, 0))
    locks = [Lock(corner.candidate_id, 0, 0)]
    assigns, unplaced = place_candidates(5, 6, 2, _cands(12), locks)
    assert _pos(assigns, corner.candidate_id) == (0, 0)
    locked_assign = next(a for a in assigns if a.candidate_id == corner.candidate_id)
    assert locked_assign.locked is True
    # 锁格绝不允许排别人
    assert sum(1 for a in assigns if (a.row, a.col) == (0, 0)) == 1
    assert not unplaced or all(u["id"] != corner.candidate_id for u in unplaced)


def test_lock_cell_never_reassigned_to_others():
    cands = _cands(6)
    # 锁 3 号在 (2,2)；其他人不得占该格，也不得与其违反约束
    assigns, _ = place_candidates(5, 6, 2, cands, [Lock(3, 2, 2)])
    cell3 = _pos(assigns, 3)
    assert cell3 == (2, 2)
    for a in assigns:
        if a.candidate_id == 3:
            continue
        assert (a.row, a.col) != (2, 2)
        assert manhattan((a.row, a.col), (2, 2)) >= 2


def test_tightening_min_dist_against_lock_fails_whole_run():
    # 两锁相距 2，min_dist=2 合法；把最小距提到 3，锁位即违法，整场失败
    locks = [Lock(1, 0, 0), Lock(3, 0, 2)]  # 卷1 与 卷3，距离 2
    assigns, _ = place_candidates(5, 6, 2, _cands(12), locks)
    assert _pos(assigns, 1) == (0, 0) and _pos(assigns, 3) == (0, 2)
    with pytest.raises(PlacementError):
        place_candidates(5, 6, 3, _cands(12), locks)


def test_locked_same_paper_adjacent_fails():
    # 同卷锁在四邻位：锁位本身违法，必须失败而不是拆掉其中一把锁
    locks = [Lock(1, 0, 0), Lock(4, 0, 1)]  # 两者均为卷1
    with pytest.raises(PlacementError):
        place_candidates(5, 6, 1, _cands(12), locks)


def test_out_of_range_or_duplicate_lock_fails():
    with pytest.raises(PlacementError):
        place_candidates(5, 6, 2, _cands(12), [Lock(1, 5, 0)])  # 行越界
    with pytest.raises(PlacementError):
        place_candidates(5, 6, 2, _cands(12), [Lock(1, 0, 0), Lock(2, 0, 0)])  # 同格两锁
    with pytest.raises(PlacementError):
        place_candidates(5, 6, 2, _cands(12), [Lock(99, 0, 0)])  # 名单外考生


def test_unlock_allows_rearrange_next_run():
    cands = _cands(6)
    # 锁定时 3 号钉在 (0,0)，1 号（顺序最靠前的自由人）只能去别处
    assigns_locked, _ = place_candidates(5, 6, 2, cands, [Lock(3, 0, 0)])
    assert _pos(assigns_locked, 3) == (0, 0)
    assert _pos(assigns_locked, 1) != (0, 0)
    # 解锁后下一次排座：原格可被重排，顺序最靠前的 1 号回到 (0,0)
    assigns_free, _ = place_candidates(5, 6, 2, cands)
    assert _pos(assigns_free, 1) == (0, 0)
