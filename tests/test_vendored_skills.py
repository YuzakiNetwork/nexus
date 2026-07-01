"""Test untuk vendor skill: pastikan file tersedia dan lisensi MIT."""
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
VENDOR_DIR = PROJECT_ROOT / "vendor" / "ponytail"


def test_vendor_dir_exists():
    assert VENDOR_DIR.exists(), "vendor/ponytail harus ada di repo"


@pytest.mark.parametrize("name", ["ponytail.md", "ponytail-review.md"])
def test_vendored_skill_present(name):
    p = VENDOR_DIR / name
    assert p.exists()
    # Harus ada frontmatter
    first = p.read_text(encoding="utf-8").splitlines()[0]
    assert first.strip() == "---", f"{name} harus pakai frontmatter YAML"


def test_vendored_license_mit():
    """Lisensi vendor harus MIT dan menyertakan copyright."""
    lic = VENDOR_DIR / "LICENSE"
    assert lic.exists()
    text = lic.read_text(encoding="utf-8")
    assert "MIT License" in text
    assert "Copyright" in text


def test_vendored_skill_loadable_by_skill_store():
    """File vendor harus bisa dimuat oleh SkillStore nexus_cli."""
    from nexus_cli.agent import SkillStore
    store = SkillStore([VENDOR_DIR])
    names = {s["name"] for s in store.list()}
    assert "ponytail" in names
    assert "ponytail-review" in names


def test_third_party_notice_exists():
    """THIRD_PARTY.md harus ada untuk compliance redistribusi."""
    p = PROJECT_ROOT / "THIRD_PARTY.md"
    assert p.exists()
    text = p.read_text(encoding="utf-8")
    assert "ponytail" in text.lower()
    assert "MIT" in text
