from app.models.pipeline_run import PipelineRun


def test_each_run_gets_a_unique_id():
    a = PipelineRun(repo_id=1, commit_sha="a")
    b = PipelineRun(repo_id=1, commit_sha="b")
    assert a.run_id and b.run_id
    assert a.run_id != b.run_id


def test_run_id_is_stored_in_the_inserted_document():
    """The orchestrator inserts run.dict(); run_id must be in it, not null."""
    doc = PipelineRun(repo_id=1, commit_sha="a").dict()
    assert doc["run_id"]
