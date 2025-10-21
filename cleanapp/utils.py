import structlog


def get_cleanapp_logger(name):
    """This will add a `cleanapp` prefix to logger for easy configuration."""

    return structlog.get_logger(
        f"cleanapp.{name}",
        project="cleanapp"
    )
