from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path


def _parse_dotenv(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.is_file():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key] = value
    return values


def _first_value(process: dict[str, str], file_values: dict[str, str], *names: str) -> str | None:
    for name in names:
        value = process.get(name)
        if value:
            return value
    for name in names:
        value = file_values.get(name)
        if value:
            return value
    return None


@dataclass(frozen=True, repr=False)
class Settings:
    workdir: Path
    apinex_api_key: str | None
    apinex_base_url: str
    timeout: float = 20.0

    def __repr__(self) -> str:
        return (
            "Settings(workdir={!r}, apinex_api_key='[REDACTED]', "
            "apinex_base_url={!r}, timeout={!r})"
        ).format(self.workdir, self.apinex_base_url, self.timeout)

    def secret(self, name: str) -> str | None:
        if name == "APINEX_API_KEY":
            return self.apinex_api_key
        return None


def load_settings(workdir: Path) -> Settings:
    workdir = Path(workdir).resolve()
    file_values = _parse_dotenv(workdir / ".env")
    process = dict(os.environ)
    return Settings(
        workdir=workdir,
        apinex_api_key=_first_value(process, file_values, "APINEX_API_KEY", "apinex_api_key"),
        apinex_base_url=(
            _first_value(process, file_values, "APINEX_BASE_URL", "apinex_base_url")
            or "https://api.apinex.bond/v1"
        ).rstrip("/"),
    )
