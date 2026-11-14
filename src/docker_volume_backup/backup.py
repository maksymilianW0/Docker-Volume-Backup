"""Logika: strumieniowe wyciągnięcie zawartości volume Dockera do lokalnego archiwum.

Jak to działa: tworzymy (ale NIE uruchamiamy) tymczasowy kontener z podmontowanym
volume w trybie tylko-do-odczytu, a potem pobieramy jego zawartość przez Docker API
(odpowiednik `docker cp`). Strumień tar jest kompresowany "w locie" i zapisywany
lokalnie, więc nie potrzeba bind-mountów ani uprawnień roota na hoście i działa to
też ze zdalnym demonem Dockera (DOCKER_HOST).
"""

from __future__ import annotations

import bz2
import gzip
import logging
import lzma
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, BinaryIO, Callable, Optional

import docker
from docker.errors import DockerException, ImageNotFound, NotFound

logger = logging.getLogger(__name__)

DEFAULT_HELPER_IMAGE = "alpine:3"
MOUNT_POINT = "/data"
DEFAULT_FORMAT = "tar.gz"

_OPENERS: dict[str, Callable[[Path], BinaryIO]] = {
    "tar": lambda p: open(p, "wb"),
    "tar.gz": lambda p: gzip.open(p, "wb", compresslevel=6),
    "tar.bz2": lambda p: bz2.open(p, "wb", compresslevel=9),
    "tar.xz": lambda p: lzma.open(p, "wb", preset=6),
}
SUPPORTED_FORMATS = tuple(_OPENERS)


class BackupError(Exception):
    """Błąd, który można pokazać użytkownikowi bez stack trace'a."""


def default_archive_name(
    volume: str, fmt: str = DEFAULT_FORMAT, now: Optional[datetime] = None
) -> str:
    now = now or datetime.now(timezone.utc)
    return f"{volume}_{now:%Y%m%d-%H%M%S}.{fmt}"


def connect() -> "docker.DockerClient":
    """Łączy się z demonem Dockera wg zmiennych środowiskowych (DOCKER_HOST itd.)."""
    try:
        client = docker.from_env()
        client.ping()
        return client
    except DockerException as exc:
        raise BackupError(
            f"Nie można połączyć się z demonem Dockera. Czy Docker działa? ({exc})"
        ) from exc


def list_volumes(client: Any) -> list[str]:
    try:
        return sorted(v.name for v in client.volumes.list())
    except DockerException as exc:
        raise BackupError(f"Nie udało się pobrać listy volume: {exc}") from exc


def _ensure_image(client: Any, image: str) -> None:
    try:
        client.images.get(image)
    except ImageNotFound:
        logger.info("Pobieram obraz pomocniczy %s ...", image)
        client.images.pull(image)


def backup_volume(
    volume_name: str,
    destination: "str | os.PathLike[str]",
    *,
    fmt: str = DEFAULT_FORMAT,
    output_name: Optional[str] = None,
    overwrite: bool = False,
    helper_image: str = DEFAULT_HELPER_IMAGE,
    client: Any = None,
    progress: Optional[Callable[[int], None]] = None,
) -> Path:
    """Zapisuje całe volume jako archiwum w katalogu `destination`.

    Zwraca ścieżkę do utworzonego pliku. `progress(n)` dostaje łączną liczbę
    bajtów (nieskompresowanych) pobranych dotąd z Dockera.
    """
    if fmt not in _OPENERS:
        raise BackupError(
            f"Nieobsługiwany format '{fmt}'. Dostępne: {', '.join(SUPPORTED_FORMATS)}"
        )

    if output_name is not None:
        if Path(output_name).name != output_name or not output_name:
            raise BackupError("--name musi być samą nazwą pliku, bez ścieżki.")
        filename = output_name
    else:
        filename = default_archive_name(volume_name, fmt)

    dest_dir = Path(destination).expanduser().resolve()
    target = dest_dir / filename
    tmp = target.with_name(target.name + ".part")

    if target.exists() and not overwrite:
        raise BackupError(f"Plik {target} już istnieje (użyj --overwrite).")

    client = client or connect()
    container = None
    try:
        try:
            client.volumes.get(volume_name)
        except NotFound as exc:
            raise BackupError(f"Volume '{volume_name}' nie istnieje.") from exc

        users = [c.name for c in client.containers.list(filters={"volume": volume_name})]
        if users:
            logger.warning(
                "Volume jest używane przez działające kontenery (%s). Kopia może "
                "być niespójna, jeśli aplikacje zapisują dane w trakcie backupu.",
                ", ".join(users),
            )

        dest_dir.mkdir(parents=True, exist_ok=True)
        _ensure_image(client, helper_image)

        container = client.containers.create(
            helper_image,
            volumes={volume_name: {"bind": MOUNT_POINT, "mode": "ro"}},
            network_disabled=True,
            labels={"docker-volume-backup": "helper"},
        )
        stream, _stat = container.get_archive(f"{MOUNT_POINT}/.")

        total = 0
        try:
            with _OPENERS[fmt](tmp) as out:
                for chunk in stream:
                    out.write(chunk)
                    total += len(chunk)
                    if progress:
                        progress(total)
            os.replace(tmp, target)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise
    except DockerException as exc:
        raise BackupError(f"Błąd Dockera: {exc}") from exc
    except OSError as exc:
        raise BackupError(f"Błąd zapisu na dysku: {exc}") from exc
    finally:
        if container is not None:
            try:
                container.remove(force=True)
            except DockerException as exc:
                logger.warning("Nie udało się usunąć kontenera pomocniczego: %s", exc)

    logger.info("Gotowe: %s", target)
    return target
