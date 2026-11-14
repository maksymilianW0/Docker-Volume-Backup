from __future__ import annotations

import argparse
import logging
import sys
from typing import Optional, Sequence

from . import __version__
from .backup import (
    DEFAULT_FORMAT,
    DEFAULT_HELPER_IMAGE,
    SUPPORTED_FORMATS,
    BackupError,
    backup_volume,
    connect,
    list_volumes,
)


def _human(n: float) -> str:
    for unit in ("B", "KiB", "MiB", "GiB"):
        if n < 1024:
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} TiB"


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="docker-volume-backup",
        description="Kopia zapasowa całego volume Dockera do lokalnego archiwum.",
    )
    p.add_argument("volume", nargs="?", help="nazwa volume do skopiowania")
    p.add_argument("-o", "--output", default=".", metavar="KATALOG",
                   help="katalog docelowy (domyślnie: bieżący)")
    p.add_argument("-f", "--format", default=DEFAULT_FORMAT, choices=SUPPORTED_FORMATS,
                   help=f"format archiwum (domyślnie: {DEFAULT_FORMAT})")
    p.add_argument("-n", "--name", metavar="PLIK",
                   help="własna nazwa pliku (domyślnie: <volume>_<data>.<format>)")
    p.add_argument("--overwrite", action="store_true",
                   help="nadpisz istniejący plik")
    p.add_argument("--image", default=DEFAULT_HELPER_IMAGE,
                   help=f"obraz pomocniczy (domyślnie: {DEFAULT_HELPER_IMAGE})")
    p.add_argument("-l", "--list", action="store_true", help="pokaż dostępne volume i wyjdź")
    p.add_argument("-v", "--verbose", action="store_true", help="więcej logów")
    p.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return p


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(levelname)s: %(message)s",
    )

    if not args.list and not args.volume:
        parser.error("podaj nazwę volume albo użyj --list")

    try:
        client = connect()

        if args.list:
            for name in list_volumes(client):
                print(name)
            return 0

        is_tty = sys.stderr.isatty()

        def progress(total: int) -> None:
            if is_tty:
                print(f"\rPobrano: {_human(total)}", end="", file=sys.stderr, flush=True)

        path = backup_volume(
            args.volume,
            args.output,
            fmt=args.format,
            output_name=args.name,
            overwrite=args.overwrite,
            helper_image=args.image,
            client=client,
            progress=progress,
        )
        if is_tty:
            print(file=sys.stderr)
        print(f"{path} ({_human(path.stat().st_size)})")
        return 0
    except BackupError as exc:
        print(f"Błąd: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nPrzerwano.", file=sys.stderr)
        return 130
