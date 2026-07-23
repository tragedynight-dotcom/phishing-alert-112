"""Streamlit 외 프로세스에서도 secrets.toml 을 읽을 수 있게 합니다."""

from __future__ import annotations

from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore


def secrets_path() -> Path:
    return Path(__file__).resolve().parent / ".streamlit" / "secrets.toml"


def load_secrets() -> dict:
    path = secrets_path()
    if not path.is_file():
        return {}
    with path.open("rb") as fh:
        return tomllib.load(fh)


def get_naver_credentials() -> tuple[str | None, str | None]:
    secrets = load_secrets()
    client_id = secrets.get("NAVER_CLIENT_ID")
    client_secret = secrets.get("NAVER_CLIENT_SECRET")
    if (
        not client_id
        or not client_secret
        or "your_client" in str(client_id)
        or "your_client" in str(client_secret)
    ):
        return None, None
    return str(client_id), str(client_secret)


def get_vapid_config() -> dict[str, str]:
    secrets = load_secrets()
    return {
        "public_key": str(secrets.get("VAPID_PUBLIC_KEY", "") or ""),
        "private_key": str(secrets.get("VAPID_PRIVATE_KEY", "") or ""),
        "claims_email": str(secrets.get("VAPID_CLAIMS_EMAIL", "") or "mailto:admin@example.com"),
    }
