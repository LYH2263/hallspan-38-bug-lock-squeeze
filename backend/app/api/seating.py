import json
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.models import Candidate, Hall, SeatLock, SeatPlan
from app.services.seat_engine import (
    Lock,
    PlacementError,
    find_violations,
    place_candidates,
    plan_to_dict,
)

from app.services.page_rollup import mix_stats, mix_violations
router = APIRouter(prefix="/seating", tags=["seating"])


class LockIn(BaseModel):
    candidate_id: int
    row: int
    col: int


def _hall_or_404(db: Session, hall_id: int) -> Hall:
    hall = db.get(Hall, hall_id)
    if not hall:
        raise HTTPException(404, "考室不存在")
    return hall


def _candidate_or_404(db: Session, hall_id: int, candidate_id: int) -> Candidate:
    cand = db.get(Candidate, candidate_id)
    if not cand or cand.hall_id != hall_id:
        raise HTTPException(404, "考生不在本考室考生名单中")
    return cand


def _current_locks(db: Session, hall_id: int) -> list[Lock]:
    rows = db.scalars(select(SeatLock).where(SeatLock.hall_id == hall_id)).all()
    return [Lock(candidate_id=r.candidate_id, row=r.row, col=r.col) for r in rows]


def _candidates(db: Session, hall_id: int) -> list[dict]:
    return [{"id": c.id, "name": c.name, "ticket_no": c.ticket_no, "paper_id": c.paper_id}
            for c in db.scalars(select(Candidate).where(Candidate.hall_id == hall_id)).all()]


def run_seating_plan(db: Session, hall: Hall) -> dict:
    """按当前锁位执行排座并落库一个新方案。

    锁位在当前约束下不合法时抛 PlacementError：整场失败、不写 SeatPlan，
    绝不为了排其他人而拆掉锁位。
    """
    cands = _candidates(db, hall.id)
    locks = _current_locks(db, hall.id)
    assigns, unplaced = place_candidates(hall.rows, hall.cols, hall.min_manhattan, cands, locks)
    viols = find_violations(hall.rows, hall.cols, hall.min_manhattan, assigns)
    result = plan_to_dict(assigns, unplaced, viols, hall.rows, hall.cols, locks)
    result["hall"] = {"id": hall.id, "name": hall.name, "min_manhattan": hall.min_manhattan}
    plan = SeatPlan(hall_id=hall.id, created_at=datetime.utcnow(),
                    result_json=json.dumps(result, ensure_ascii=False))
    db.add(plan)
    db.commit()
    db.refresh(plan)
    return {"id": plan.id, **result}


@router.post("/run")
def run_seating(hall_id: int = 1, db: Session = Depends(get_db)):
    hall = _hall_or_404(db, hall_id)
    try:
        return run_seating_plan(db, hall)
    except PlacementError as exc:
        # 保锁失败：不新增任何方案，保留历史方案与当前锁位不动
        db.rollback()
        raise HTTPException(status_code=409, detail=f"锁位在当前约束下已不合法，已取消本次排座：{exc}")


@router.get("/latest")
def latest(hall_id: int = 1, db: Session = Depends(get_db)):
    plan = db.scalars(select(SeatPlan).where(SeatPlan.hall_id == hall_id).order_by(SeatPlan.id.desc())).first()
    if not plan:
        return run_seating(hall_id=hall_id, db=db)
    # 原样返回历史快照：锁标记、锁名单、统计都是落方案那一刻的数，
    # 当前锁表的增删绝不回刷已落下的方案
    return {"id": plan.id, **json.loads(plan.result_json)}


@router.get("/violations")
def violations(hall_id: int = 1, db: Session = Depends(get_db)):
    data = latest(hall_id=hall_id, db=db)
    return {"hall_id": hall_id, **mix_violations(data)}


@router.get("/stats")
def stats(hall_id: int = 1, db: Session = Depends(get_db)):
    _hall_or_404(db, hall_id)
    data = latest(hall_id=hall_id, db=db)
    out = mix_stats(data)
    # 统计锁定人数与当前锁名单同一套数（图上带锁格也按当前锁表渲染）
    out["locked"] = len(_current_locks(db, hall_id))
    return {"hall_id": hall_id, **out}


@router.get("/locks")
def list_locks(hall_id: int = 1, db: Session = Depends(get_db)):
    _hall_or_404(db, hall_id)
    rows = db.scalars(select(SeatLock).where(SeatLock.hall_id == hall_id).order_by(SeatLock.id)).all()
    return {"hall_id": hall_id,
            "locks": [{"candidate_id": r.candidate_id, "row": r.row, "col": r.col} for r in rows]}


@router.post("/locks")
def add_lock(body: LockIn, hall_id: int = 1, db: Session = Depends(get_db)):
    hall = _hall_or_404(db, hall_id)
    cand = _candidate_or_404(db, hall_id, body.candidate_id)
    # 全部校验先于任何写入：任一项失败，锁名单、方案、统计都原样不动
    if not (0 <= body.row < hall.rows and 0 <= body.col < hall.cols):
        raise HTTPException(422, f"格位 ({body.row},{body.col}) 越出 {hall.rows}x{hall.cols} 考室网格")
    same_cell = db.scalars(
        select(SeatLock).where(SeatLock.hall_id == hall_id, SeatLock.row == body.row, SeatLock.col == body.col)
    ).first()
    if same_cell and same_cell.candidate_id != body.candidate_id:
        raise HTTPException(409, f"该格已锁定给考生 {same_cell.candidate_id}，一格只能锁一人")
    # 考生必须当前就坐在该格（以最新方案为准）；找不到人或人没坐在那格，整请求失败
    plan = db.scalars(select(SeatPlan).where(SeatPlan.hall_id == hall_id).order_by(SeatPlan.id.desc())).first()
    seated = None
    if plan:
        snap = json.loads(plan.result_json)
        seated = next((a for a in snap.get("assignments") or []
                       if a.get("candidate_id") == body.candidate_id), None)
    if seated is None or (seated.get("row"), seated.get("col")) != (body.row, body.col):
        raise HTTPException(409, f"考生 {cand.name} 当前未坐在 ({body.row},{body.col}) 格"
                                 "（方案可能已更新），未写入任何锁定")
    existing = db.scalars(
        select(SeatLock).where(SeatLock.hall_id == hall_id, SeatLock.candidate_id == body.candidate_id)
    ).first()
    if existing:
        existing.row, existing.col = body.row, body.col
    else:
        db.add(SeatLock(hall_id=hall_id, candidate_id=body.candidate_id, row=body.row, col=body.col))
    db.commit()
    # 不改写任何已落下的方案：新锁只影响下一次排座
    return {"ok": True, "candidate_id": body.candidate_id, "row": body.row, "col": body.col}


@router.delete("/locks/{candidate_id}")
def remove_lock(candidate_id: int, hall_id: int = 1, db: Session = Depends(get_db)):
    _hall_or_404(db, hall_id)
    existing = db.scalars(
        select(SeatLock).where(SeatLock.hall_id == hall_id, SeatLock.candidate_id == candidate_id)
    ).first()
    if existing:
        db.delete(existing)
        db.commit()
    # 已落下的方案快照保持原字：解锁只影响下一次排座
    return {"ok": True, "candidate_id": candidate_id, "unlocked": bool(existing)}
