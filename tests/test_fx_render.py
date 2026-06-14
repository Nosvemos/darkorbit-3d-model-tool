"""Tests for the fx_render orchestrator helpers (no Blender)."""
import os
import zipfile

from src import config, fx_render


def test_ensure_awp_uses_zip_when_named_directly(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "FX_DIR", str(tmp_path))
    with zipfile.ZipFile(tmp_path / "foo.zip", "w") as zf:
        zf.writestr("foo.awp", "{}")
    p = fx_render.ensure_awp("foo")
    assert p.endswith("foo.awp") and os.path.exists(p)


def test_ensure_awp_falls_back_to_mismatched_name(tmp_path, monkeypatch):
    # zip is foo.zip but the .awp inside is bar.awp (real assets do this)
    monkeypatch.setattr(config, "FX_DIR", str(tmp_path))
    with zipfile.ZipFile(tmp_path / "foo.zip", "w") as zf:
        zf.writestr("bar.awp", "{}")
    p = fx_render.ensure_awp("foo")
    assert p.endswith("bar.awp") and os.path.exists(p)
