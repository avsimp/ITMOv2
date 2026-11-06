import pytest

from app.errors import ApiError
from app.storage import Storage

pytestmark = pytest.mark.controlled


def test_internal_path_guard(setup, tmp_path):
    store = Storage(setup[1])
    for ident in ("../outside", "/tmp/x", "not-a-uuid"):
        with pytest.raises(ApiError) as exc:
            store.folder(ident)
        assert exc.value.status == 404


def test_marker_is_exclusive(setup):
    from datetime import datetime, timezone
    from app.schemas import WorkRecord
    store = Storage(setup[1])
    ident, folder = store.allocate()
    for name in store.files(False).values():
        (folder / name).write_bytes(b"original")
    record = WorkRecord(work_id=ident, name="Work", created_at=datetime.now(timezone.utc).isoformat(),
                        topic_ids=[1], count=1, attachments=[], schema_version=1, has_archive=False,
                        files=store.files(False))
    store.publish(folder, record)
    before = (folder / "work.json").read_bytes()
    with pytest.raises(ApiError) as exc:
        store.publish(folder, record)
    assert exc.value.status == 409
    assert (folder / "work.json").read_bytes() == before
