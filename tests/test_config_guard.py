import logging

from app import main


def test_warns_when_local_dev_is_on_in_cloud_run(caplog):
    with caplog.at_level(logging.WARNING):
        assert main.warn_if_local_dev_on_cloud_run(True, {"K_SERVICE": "synkron-backend"})
    assert "LOCAL_DEV" in caplog.text


def test_silent_when_local_dev_off_or_running_locally(caplog):
    with caplog.at_level(logging.WARNING):
        assert not main.warn_if_local_dev_on_cloud_run(False, {"K_SERVICE": "synkron-backend"})
        assert not main.warn_if_local_dev_on_cloud_run(True, {})
    assert caplog.text == ""


def test_cors_origins_are_normalised():
    raw = "example.com, https://app.example.com/*, http://localhost:3000/path, *, ,example.com"
    assert main.normalize_cors_origins(raw) == [
        "https://example.com",
        "https://app.example.com",
        "http://localhost:3000",
        "*",
    ]
