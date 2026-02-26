import pytest
from django.conf import settings


def pytest_configure(config):
    settings.STORAGES["staticfiles"]["BACKEND"] = (
        "django.contrib.staticfiles.storage.StaticFilesStorage"
    )


@pytest.fixture(autouse=True)
def disable_background_tasks(monkeypatch):
    from core import models, signals

    monkeypatch.setattr(models, "async_task", lambda *args, **kwargs: None)
    monkeypatch.setattr(signals, "async_task", lambda *args, **kwargs: None)


@pytest.fixture
def user(django_user_model):
    return django_user_model.objects.create_user(
        username="testuser",
        email="testuser@example.com",
        password="password123",
    )


@pytest.fixture
def auth_client(client, user):
    client.force_login(user)
    return client


@pytest.fixture
def profile(user):
    return user.profile


@pytest.fixture
def sync_state_transitions(monkeypatch):
    from core import models
    from core.tasks import track_state_change

    def _sync(task_name, *args, **kwargs):
        if task_name != "core.tasks.track_state_change":
            raise AssertionError(f"Unexpected task: {task_name}")
        allowed_keys = {
            "profile_id",
            "from_state",
            "to_state",
            "metadata",
            "source_function",
        }
        filtered_kwargs = {key: value for key, value in kwargs.items() if key in allowed_keys}
        return track_state_change(**filtered_kwargs)

    monkeypatch.setattr(models, "async_task", _sync)
