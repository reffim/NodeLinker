def test_job_log_chunk_model_importable():
    from app.models.models import JobLogChunk
    assert JobLogChunk.__tablename__ == "job_log_chunks"


def test_job_node_has_no_log_file_url():
    from app.models.models import JobNode
    assert not hasattr(JobNode, "log_file_url")
