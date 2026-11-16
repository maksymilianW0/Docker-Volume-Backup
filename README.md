# docker-volume-backup

Proste narzędzie w Pythonie, które kopiuje **całe volume Dockera** i zapisuje je jako
archiwum (`.tar.gz` domyślnie) w wybranym miejscu na dysku lokalnym.

## Jak to działa

1. Tworzy (bez uruchamiania) tymczasowy kontener `alpine:3` z volume podmontowanym **tylko do odczytu**.
2. Pobiera zawartość volume przez Docker API (jak `docker cp`) jako strumień tar.
3. Kompresuje strumień w locie i zapisuje do pliku `*.part`, po sukcesie zmienia nazwę na docelową
   (przerwany backup nie zostawia uszkodzonego archiwum).
4. Usuwa kontener pomocniczy.

Ponieważ dane płyną przez API, plik powstaje po stronie klienta – działa także ze zdalnym
`DOCKER_HOST`, a na hoście nie są potrzebne żadne bind-mounty.

## Wymagania

- Python 3.9+
- Działający Docker i dostęp do jego socketu (np. członkostwo w grupie `docker`)
- Obraz `alpine:3` (zostanie pobrany automatycznie, jeśli go nie ma)

## Instalacja

```bash
git clone <url-repo> docker-volume-backup
cd docker-volume-backup
python -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
pip install -e .            # opcjonalnie: komenda `docker-volume-backup`
```

## Użycie

### dvb to alias do docker-volume-backup

```bash
# lista dostępnych volume
docker-volume-backup --list

# backup do wskazanego katalogu -> /backups/my_volume_20261114-120000.tar.gz
docker-volume-backup my_volume -o /backups

# inny format i własna nazwa pliku
docker-volume-backup my_volume -o /backups -f tar.xz -n my_volume_latest.tar.xz --overwrite
```

Bez instalacji pakietu: `PYTHONPATH=src python -m docker_volume_backup my_volume -o ./backups`

| Opcja | Opis |
|---|---|
| `volume` | nazwa volume |
| `-o, --output` | katalog docelowy (domyślnie bieżący; tworzony, jeśli nie istnieje) |
| `-f, --format` | `tar`, `tar.gz` (domyślnie), `tar.bz2`, `tar.xz` |
| `-n, --name` | własna nazwa pliku |
| `--overwrite` | pozwól nadpisać istniejący plik |
| `--image` | obraz pomocniczy (domyślnie `alpine:3`) |
| `-l, --list` | wypisz volume i wyjdź |

Kod wyjścia: `0` – sukces, `1` – błąd (komunikat na stderr).

## Przywracanie ręczne

Archiwum to zwykły tar z zawartością volume (ścieżki względne), więc:

```bash
docker volume create my_volume_restored
docker run --rm -v my_volume_restored:/data -v /backups:/backup:ro alpine:3 \
  tar -xzf /backup/my_volume_20261114-120000.tar.gz -C /data
```

## Uwaga o spójności danych

Jeśli volume jest używane przez działający kontener (np. baza danych), kopia może być
niespójna. Narzędzie ostrzeże o takich kontenerach, ale ich nie zatrzymuje – przed backupem
baz danych rozważ `docker stop <kontener>`.

## Struktura repo

```
.
├── pyproject.toml
├── requirements.txt
├── requirements-dev.txt
├── src/docker_volume_backup/
│   ├── __init__.py
│   ├── __main__.py
│   ├── backup.py      # logika backupu
│   └── cli.py         # interfejs wiersza poleceń
└── tests/test_backup.py
```

## Testy

```bash
pip install -r requirements-dev.txt
pytest
```

Testy używają atrapy klienta Dockera – nie wymagają działającego demona.
