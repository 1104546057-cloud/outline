"""轨迹持久化与运行日志单元测试（M3/M5 收尾）。

覆盖：
1. upsert_track_history 插入路径（新轨迹 → 新行 + 缓存行 id）
2. upsert_track_history 更新路径（已有行 → 更新 bbox/last_seen/frame_count）
3. 缓存清理（消失轨迹从缓存移除，历史行保留）
4. log_run_event 写入运行日志

运行::

    cd backend
    python -m pytest inference/tests/ -v
"""

from __future__ import annotations

from inference.base import Track
from inference.track_history import log_run_event, upsert_track_history


def _track(track_id, cls="person"):
    return Track(track_id=track_id, bbox=(0.0, 0.0, 10.0, 10.0), confidence=0.9, class_name=cls, frame_idx=0)


class FakeRow:
    def __init__(self, track_id):
        self.id = 999
        self.track_id = track_id
        self.class_name = None
        self.bbox = None
        self.last_seen = None
        self.frame_count = 5


class FakeQuery:
    def __init__(self, row):
        self._row = row

    def filter(self, *args):
        return self

    def first(self):
        return self._row


class FakeSession:
    def __init__(self, existing_row=None):
        self.added = []
        self._existing = existing_row
        self.committed = False

    def add(self, obj):
        self.added.append(obj)

    def flush(self):
        for i, obj in enumerate(self.added):
            if obj.id is None:
                obj.id = 100 + i

    def query(self, model):
        return FakeQuery(self._existing)

    def commit(self):
        self.committed = True

    def rollback(self):
        pass

    def close(self):
        pass


# ============================================================
# 轨迹元数据 upsert
# ============================================================

class TestUpsertTrackHistory:
    def test_insert_path(self):
        db = FakeSession()
        cache = {}
        upsert_track_history(3, [_track(1), _track(2, cls="car")], cache, db=db, frames_delta=10)

        assert len(db.added) == 2
        assert set(cache) == {1, 2}
        row = db.added[0]
        assert row.device_id == 3
        assert row.track_id == 1
        assert row.global_track_id == "1"
        assert row.bbox == [0.0, 0.0, 10.0, 10.0]
        assert row.frame_count == 10
        # 注入会话时不提交
        assert not db.committed

    def test_update_path(self):
        existing = FakeRow(1)
        db = FakeSession(existing_row=existing)
        cache = {1: 999}
        upsert_track_history(3, [_track(1)], cache, db=db, frames_delta=10)

        assert db.added == []  # 不再新增
        assert existing.frame_count == 15
        assert existing.bbox == [0.0, 0.0, 10.0, 10.0]
        assert cache == {1: 999}

    def test_evicts_gone_tracks(self):
        db = FakeSession(existing_row=FakeRow(2))
        cache = {1: 101, 2: 999}
        upsert_track_history(3, [_track(2)], cache, db=db, frames_delta=1)

        # track 1 已消失 → 从缓存移除；track 2 更新
        assert cache == {2: 999}


# ============================================================
# 运行日志
# ============================================================

class TestLogRunEvent:
    def test_write_log(self):
        db = FakeSession()
        row_id = log_run_event(3, "stop", {"fps": 5.2}, db=db)
        assert len(db.added) == 1
        row = db.added[0]
        assert row.device_id == 3
        assert row.action == "stop"
        assert row.detail == {"fps": 5.2}
        assert row_id == 100  # fake flush 分配的自增 id
        assert not db.committed
