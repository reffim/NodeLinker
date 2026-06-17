def test_job_log_chunk_model_importable():
    from app.models.models import JobLogChunk
    assert JobLogChunk.__tablename__ == "job_log_chunks"


def test_job_node_has_no_log_file_url():
    from app.models.models import JobNode
    assert not hasattr(JobNode, "log_file_url")


import pytest
from unittest.mock import AsyncMock, MagicMock


def _make_scalar_result(obj):
    result = MagicMock()
    result.scalar_one_or_none.return_value = obj
    result.scalars.return_value.all.return_value = [obj] if obj else []
    return result


def _make_scalars_result(objs):
    result = MagicMock()
    result.scalars.return_value.all.return_value = objs
    return result


def test_job_log_chunk_response_schema():
    from app.schemas.jobs import JobLogChunkResponse
    import uuid
    from datetime import datetime, timezone
    chunk = JobLogChunkResponse(
        id=1,
        job_id=uuid.uuid4(),
        node_id=uuid.uuid4(),
        chunk_seq=0,
        content="line one\nline two",
        created_at=datetime.now(timezone.utc),
    )
    assert chunk.chunk_seq == 0


def test_job_node_response_has_no_log_file_url():
    from app.schemas.jobs import JobNodeResponse
    import uuid
    jn = JobNodeResponse(node_id=uuid.uuid4(), status="pending", exit_code=None)
    assert not hasattr(jn, "log_file_url")


@pytest.mark.asyncio
async def test_get_job_log_chunks_returns_chunks():
    from app.api.v1.jobs import get_job_log_chunks
    from datetime import datetime, timezone
    import uuid

    job_id = uuid.uuid4()
    node_id = uuid.uuid4()

    mock_job = MagicMock()
    mock_job.id = job_id

    chunk = MagicMock()
    chunk.id = 42
    chunk.job_id = job_id
    chunk.node_id = node_id
    chunk.chunk_seq = 0
    chunk.content = "hello\nworld"
    chunk.created_at = datetime.now(timezone.utc)

    db = AsyncMock()
    db.execute = AsyncMock(
        side_effect=[
            _make_scalar_result(mock_job),
            _make_scalars_result([chunk]),
        ]
    )

    user = MagicMock()
    result = await get_job_log_chunks(job_id=job_id, after=0, node_id=None, db=db, _current_user=user)
    assert len(result) == 1
    assert result[0].id == 42


@pytest.mark.asyncio
async def test_get_job_log_chunks_404_when_job_missing():
    from app.api.v1.jobs import get_job_log_chunks
    from fastapi import HTTPException
    import uuid

    db = AsyncMock()
    db.execute = AsyncMock(return_value=_make_scalar_result(None))

    user = MagicMock()
    with pytest.raises(HTTPException) as exc_info:
        await get_job_log_chunks(job_id=uuid.uuid4(), after=0, node_id=None, db=db, _current_user=user)
    assert exc_info.value.status_code == 404
