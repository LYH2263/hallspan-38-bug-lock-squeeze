"""API 级保锁测试：失败不增方案、历史锁快照不被当前锁表回刷、解锁后下一次排座可重排。"""
import os

os.environ["DATABASE_URL"] = "sqlite://"  # 仅为避免 create_engine 加载 psycopg2；实际使用下方覆盖引擎

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models.models import Candidate, Hall, PaperSet, SeatLock, SeatPlan


@pytest.fixture()
def client():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestingSession = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    db = TestingSession()
    hall = Hall(code="H101", name="一号考室", rows=5, cols=6, min_manhattan=2)
    db.add(hall)
    db.flush()
    papers = []
    for code in ("P-A", "P-B", "P-C"):
        p = PaperSet(code=code, title=code)
        db.add(p)
        db.flush()
        papers.append(p)
    for i in range(12):
        db.add(Candidate(hall_id=hall.id, name=f"考生{i + 1}", ticket_no=f"T{2026001 + i}",
                         paper_id=papers[i % 3].id))
    db.commit()

    def override_get_db():
        sess = TestingSession()
        try:
            yield sess
        finally:
            sess.close()

    app.dependency_overrides[get_db] = override_get_db
    # 不进入 with：跳过 lifespan（不触碰真实引擎）
    yield TestClient(app), TestingSession
    app.dependency_overrides.clear()
    db.close()
    Base.metadata.drop_all(bind=engine)


def _plan_count(Session):
    with Session() as s:
        return len(s.scalars(select(SeatPlan)).all())


def test_locked_rerun_keeps_seat_and_failed_run_adds_no_plan(client):
    c, Session = client
    # 首次排座
    r1 = c.post("/api/seating/run?hall_id=1")
    assert r1.status_code == 200
    plan1 = r1.json()
    corner = next(a for a in plan1["assignments"] if (a["row"], a["col"]) == (0, 0))
    far = next(a for a in plan1["assignments"] if (a["row"], a["col"]) == (0, 2))  # 与边角相距 2
    assert _plan_count(Session) == 1

    # 锁两把，间距恰为 2（min_dist=2 合法）
    assert c.post("/api/seating/locks?hall_id=1",
                  json={"candidate_id": corner["candidate_id"], "row": 0, "col": 0}).status_code == 200
    assert c.post("/api/seating/locks?hall_id=1",
                  json={"candidate_id": far["candidate_id"], "row": 0, "col": 2}).status_code == 200

    # 再排：两个被锁考生行列不变，锁格不排别人，方案 +1
    r2 = c.post("/api/seating/run?hall_id=1")
    assert r2.status_code == 200
    plan2 = r2.json()
    amap = {a["candidate_id"]: a for a in plan2["assignments"]}
    assert (amap[corner["candidate_id"]]["row"], amap[corner["candidate_id"]]["col"]) == (0, 0)
    assert (amap[far["candidate_id"]]["row"], amap[far["candidate_id"]]["col"]) == (0, 2)
    assert amap[corner["candidate_id"]]["locked"] is True
    assert sum(1 for a in plan2["assignments"] if (a["row"], a["col"]) in ((0, 0), (0, 2))) == 2
    assert plan2["stats"]["locked"] == 2
    assert plan2["id"] == 2 and _plan_count(Session) == 2

    # 把最小距改到锁位违法（距离 2 < 3）：再排失败，列表不增，锁位不被拆掉
    assert c.put("/api/halls/1", json={"min_manhattan": 3}).status_code == 200
    r3 = c.post("/api/seating/run?hall_id=1")
    assert r3.status_code == 409
    assert "锁位" in r3.json()["detail"]
    assert _plan_count(Session) == 2

    with Session() as s:
        locks = s.scalars(select(SeatLock).where(SeatLock.hall_id == 1)).all()
        assert {(lk.candidate_id, lk.row, lk.col) for lk in locks} == {
            (corner["candidate_id"], 0, 0), (far["candidate_id"], 0, 2)}
        # 最新方案仍是 id=2
        latest = s.scalars(select(SeatPlan).order_by(SeatPlan.id.desc())).first()
        assert latest.id == 2

    # /latest 仍是旧图（方案 2），不是失败的那次
    latest_resp = c.get("/api/seating/latest?hall_id=1").json()
    assert latest_resp["id"] == 2
    assert latest_resp["stats"]["locked"] == 2

    # 恢复最小距后再排成功
    assert c.put("/api/halls/1", json={"min_manhattan": 2}).status_code == 200
    assert c.post("/api/seating/run?hall_id=1").status_code == 200
    assert _plan_count(Session) == 3


def test_history_plan_lock_snapshot_not_rewritten(client):
    c, Session = client
    r1 = c.post("/api/seating/run?hall_id=1").json()
    corner = next(a for a in r1["assignments"] if (a["row"], a["col"]) == (0, 0))
    far = next(a for a in r1["assignments"] if (a["row"], a["col"]) == (0, 2))
    c.post("/api/seating/locks?hall_id=1",
           json={"candidate_id": corner["candidate_id"], "row": 0, "col": 0})
    c.post("/api/seating/locks?hall_id=1",
           json={"candidate_id": far["candidate_id"], "row": 0, "col": 2})
    locked_plan = c.post("/api/seating/run?hall_id=1").json()
    assert len(locked_plan["locks"]) == 2

    # 事后解锁一把：历史方案（id=2）的锁标记不得被回刷
    c.delete(f"/api/seating/locks/{far['candidate_id']}?hall_id=1")
    history = c.get("/api/seating/latest?hall_id=1").json()
    assert history["id"] == locked_plan["id"]
    assert {(x["candidate_id"], x["row"], x["col"]) for x in history["locks"]} == {
        (corner["candidate_id"], 0, 0), (far["candidate_id"], 0, 2)}
    # 当前锁表只剩一把
    cur = c.get("/api/seating/locks?hall_id=1").json()["locks"]
    assert [x["candidate_id"] for x in cur] == [corner["candidate_id"]]


def test_unlock_takes_effect_on_next_run_only(client):
    c, Session = client
    r1 = c.post("/api/seating/run?hall_id=1").json()
    corner = next(a for a in r1["assignments"] if (a["row"], a["col"]) == (0, 0))

    # 把边角考生锁到 (0,0)（该生未必是名单首位）
    c.post("/api/seating/locks?hall_id=1",
           json={"candidate_id": corner["candidate_id"], "row": 0, "col": 0})
    locked_plan = c.post("/api/seating/run?hall_id=1").json()
    amap = {a["candidate_id"]: a for a in locked_plan["assignments"]}
    assert (amap[corner["candidate_id"]]["row"], amap[corner["candidate_id"]]["col"]) == (0, 0)

    # 解锁后下一次排座：原格允许重排，锁快照归零/更新
    c.delete(f"/api/seating/locks/{corner['candidate_id']}?hall_id=1")
    r3 = c.post("/api/seating/run?hall_id=1").json()
    assert r3["stats"]["locked"] == 0
    assert r3["locks"] == []
    # 贪心首位自由考生重新占回 (0,0)
    first_seat = next(a for a in r3["assignments"] if (a["row"], a["col"]) == (0, 0))
    assert first_seat["locked"] is False


def test_lock_conflicts_and_bounds(client):
    c, _ = client
    r1 = c.post("/api/seating/run?hall_id=1").json()
    a00 = next(a for a in r1["assignments"] if (a["row"], a["col"]) == (0, 0))
    a02 = next(a for a in r1["assignments"] if (a["row"], a["col"]) == (0, 2))
    c.post("/api/seating/locks?hall_id=1",
           json={"candidate_id": a00["candidate_id"], "row": 0, "col": 0})
    # 同一格锁给第二人 → 409
    conflict = c.post("/api/seating/locks?hall_id=1",
                      json={"candidate_id": a02["candidate_id"], "row": 0, "col": 0})
    assert conflict.status_code == 409
    # 越界 → 422
    out = c.post("/api/seating/locks?hall_id=1",
                 json={"candidate_id": a02["candidate_id"], "row": 99, "col": 0})
    assert out.status_code == 422
    # 重新锁定到合法格成功
    ok = c.post("/api/seating/locks?hall_id=1",
                json={"candidate_id": a02["candidate_id"], "row": 0, "col": 2})
    assert ok.status_code == 200
