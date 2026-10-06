from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session
from app.database import get_db
from app.models.models import Hall
router = APIRouter(prefix="/halls", tags=["halls"])


class HallUpdate(BaseModel):
    min_manhattan: int | None = None


def _hall_dict(r: Hall) -> dict:
    return {"id": r.id, "code": r.code, "name": r.name, "rows": r.rows, "cols": r.cols,
            "min_manhattan": r.min_manhattan}


@router.get("")
def list_halls(db: Session = Depends(get_db)):
    return [_hall_dict(r) for r in db.scalars(select(Hall).order_by(Hall.id)).all()]


@router.put("/{hall_id}")
def update_hall(hall_id: int, body: HallUpdate, db: Session = Depends(get_db)):
    hall = db.get(Hall, hall_id)
    if not hall:
        raise HTTPException(404, "考室不存在")
    if body.min_manhattan is not None:
        if body.min_manhattan < 1:
            raise HTTPException(422, "最小曼哈顿间距必须 >= 1")
        hall.min_manhattan = body.min_manhattan
    db.commit()
    db.refresh(hall)
    # 改距不当场重排、不改写已落下的方案；新间距在下一次手动排座时生效，
    # 若锁位在新间距下已不合法，那次排座整场失败（409）且方案数不增
    return _hall_dict(hall)
