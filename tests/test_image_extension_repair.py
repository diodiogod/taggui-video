from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'taggui'))

from models.image_list_model import scan_directory_snapshot


def test_scan_repairs_cache_buster_image_extensions(tmp_path):
    (tmp_path / 'extensionless').write_bytes(b'\xff\xd8\xff\xe0')
    (tmp_path / '1280x720.c.jpg.v1699743618').write_bytes(b'\xff\xd8\xff\xe0')
    (tmp_path / '1280x720.c.jpg.v1668609859').write_bytes(
        b'RIFF\x00\x00\x00\x00WEBP'
    )
    (tmp_path / '1280x720.c.jpg.v1689196977').write_bytes(b'\xff\xd8\xff\xe0')
    (tmp_path / '1280x720.c.jpg(1).v1689196977').write_bytes(b'\xff\xd8\xff\xe0')

    paths, _stats, _dir_mtimes = scan_directory_snapshot(
        tmp_path,
        repair_extensionless_images=True,
    )

    names = {path.name for path in paths}
    assert 'extensionless.jpg' in names
    assert '1280x720.c.jpg' in names
    assert '1280x720.c(2).jpg' in names
    assert '1280x720.c.webp' in names
    assert '1280x720.c(1).jpg' in names
    assert not any(name.endswith('.v1699743618') for name in names)
    assert not any(name.endswith('.v1668609859') for name in names)
    assert not any(name.endswith('.v1689196977') for name in names)
