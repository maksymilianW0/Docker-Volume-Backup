import gzip
import io
import tarfile
from types import SimpleNamespace

import pytest
from docker.errors import ImageNotFound, NotFound

from docker_volume_backup import BackupError, backup_volume


def make_tar(files):
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        for name, data in files.items():
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


class FakeContainer:
    def __init__(self, data, fail_midway=False):
        self.data = data
        self.fail_midway = fail_midway
        self.removed = False
        self.requested_path = None

    def get_archive(self, path, **_):
        self.requested_path = path

        def gen():
            half = len(self.data) // 2
            yield self.data[:half]
            if self.fail_midway:
                raise OSError("boom")
            yield self.data[half:]

        return gen(), {}

    def remove(self, force=False):
        self.removed = True


class FakeClient:
    def __init__(self, files=None, volumes=("vol",), image_present=True, fail_midway=False):
        self.files = files or {"a.txt": b"hello", "sub/b.txt": b"world" * 1000}
        self.volume_names = set(volumes)
        self.image_present = image_present
        self.pulled = []
        self.created = []
        self.container = FakeContainer(make_tar(self.files), fail_midway)
        self.volumes = SimpleNamespace(get=self._get_volume)
        self.containers = SimpleNamespace(create=self._create, list=lambda **_: [])
        self.images = SimpleNamespace(get=self._get_image, pull=self.pulled.append)

    def _get_volume(self, name):
        if name not in self.volume_names:
            raise NotFound("no such volume")
        return SimpleNamespace(name=name)

    def _get_image(self, name):
        if not self.image_present:
            raise ImageNotFound("no image")

    def _create(self, image, **kwargs):
        self.created.append((image, kwargs))
        return self.container


def read_tar_gz(path):
    with gzip.open(path, "rb") as f, tarfile.open(fileobj=f) as tar:
        return {m.name.lstrip("./"): tar.extractfile(m).read() for m in tar if m.isfile()}


def test_creates_tar_gz_with_volume_contents(tmp_path):
    client = FakeClient()
    path = backup_volume("vol", tmp_path / "out", client=client)

    assert path.parent == tmp_path / "out"
    assert path.name.startswith("vol_") and path.name.endswith(".tar.gz")
    assert read_tar_gz(path) == client.files
    assert not list(path.parent.glob("*.part"))


def test_helper_container_mounts_volume_read_only_and_is_removed(tmp_path):
    client = FakeClient()
    backup_volume("vol", tmp_path, client=client)

    _image, kwargs = client.created[0]
    assert kwargs["volumes"] == {"vol": {"bind": "/data", "mode": "ro"}}
    assert client.container.requested_path == "/data/."
    assert client.container.removed


@pytest.mark.parametrize("fmt", ["tar", "tar.gz", "tar.bz2", "tar.xz"])
def test_all_formats_are_valid_tar_archives(tmp_path, fmt):
    client = FakeClient()
    path = backup_volume("vol", tmp_path, fmt=fmt, client=client)

    assert path.name.endswith(f".{fmt}")
    with tarfile.open(path, "r:*") as tar:
        assert {m.name.lstrip("./") for m in tar if m.isfile()} == set(client.files)


def test_missing_volume(tmp_path):
    with pytest.raises(BackupError, match="nie istnieje"):
        backup_volume("nope", tmp_path, client=FakeClient())


def test_failure_leaves_no_partial_file_and_removes_container(tmp_path):
    client = FakeClient(fail_midway=True)
    with pytest.raises(BackupError):
        backup_volume("vol", tmp_path, client=client)

    assert list(tmp_path.iterdir()) == []
    assert client.container.removed


def test_custom_name_and_overwrite_protection(tmp_path):
    client = FakeClient()
    path = backup_volume("vol", tmp_path, output_name="mine.tar.gz", client=client)
    assert path.name == "mine.tar.gz"

    with pytest.raises(BackupError, match="już istnieje"):
        backup_volume("vol", tmp_path, output_name="mine.tar.gz", client=client)
    backup_volume("vol", tmp_path, output_name="mine.tar.gz", overwrite=True, client=client)


def test_name_with_path_is_rejected(tmp_path):
    with pytest.raises(BackupError):
        backup_volume("vol", tmp_path, output_name="../evil.tar.gz", client=FakeClient())


def test_unknown_format(tmp_path):
    with pytest.raises(BackupError, match="Nieobsługiwany"):
        backup_volume("vol", tmp_path, fmt="zip", client=FakeClient())


def test_pulls_helper_image_when_missing(tmp_path):
    client = FakeClient(image_present=False)
    backup_volume("vol", tmp_path, client=client)
    assert client.pulled == ["alpine:3"]
