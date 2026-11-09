"""The data folder (notes, images, database) must never resolve inside the repository."""
from pathlib import Path

import pytest

from backend import paths


def test_default_is_outside_repo(monkeypatch):
    monkeypatch.delenv(paths.ENV_VAR, raising=False)
    monkeypatch.setattr(paths, "_env_file_value", lambda: None)
    resolved = paths.data_dir()
    assert paths.ROOT not in resolved.parents and resolved != paths.ROOT


def test_env_var_wins(monkeypatch, tmp_path):
    monkeypatch.setenv(paths.ENV_VAR, str(tmp_path / "notes"))
    assert paths.data_dir() == (tmp_path / "notes").resolve()


def test_env_file_value_is_read(tmp_path):
    env = tmp_path / ".env"
    env.write_text(f"OTHER=1\n{paths.ENV_VAR}='/srv/traceback data'\n")
    assert paths._env_file_value(env) == "/srv/traceback data"


@pytest.mark.parametrize("value", [str(paths.ROOT), str(paths.ROOT / ".local" / "traceback")])
def test_paths_inside_repo_are_refused(value):
    with pytest.raises(ValueError, match="outside"):
        paths.resolve_data_dir(value)


def test_relative_path_is_refused():
    with pytest.raises(ValueError, match="absolute"):
        paths.resolve_data_dir("data")


def test_settings_derive_asset_dir_from_data_dir(monkeypatch, tmp_path):
    from backend.config import Settings

    monkeypatch.delenv("TRACEBACK_ASSET_DIR", raising=False)
    settings = Settings(api_token="x" * 24, data_dir=tmp_path, _env_file=None)  # type: ignore[call-arg]
    assert settings.asset_dir == tmp_path.resolve() / "assets"


def test_legacy_data_blocks_a_fresh_store(monkeypatch, tmp_path):
    legacy = tmp_path / "legacy"
    (legacy / "assets").mkdir(parents=True)
    monkeypatch.setattr(paths, "LEGACY_DATA_DIR", legacy)
    with pytest.raises(ValueError, match="move-data"):
        paths.require_no_legacy_data(tmp_path / "new")
    (tmp_path / "new").mkdir()
    paths.require_no_legacy_data(tmp_path / "new")
