import pytest

from ctfwb.config import AppConfig, ConfigError


def test_defaults_use_per_user_paths_and_do_not_create_config(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "settings"))
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))

    config = AppConfig.load()

    assert config.config_path == tmp_path / "settings/ctf-workbench/config.toml"
    assert config.data_dir == tmp_path / "data/ctf-workbench"
    assert not config.config_path.exists()


def test_explicit_config_and_relative_data_override(tmp_path):
    config_file = tmp_path / "settings/config.toml"
    config_file.parent.mkdir()
    config_file.write_text(
        '[paths]\ndata_dir = "../workbench-data"\n', encoding="utf-8"
    )

    config = AppConfig.load(config_file)

    assert config.config_path == config_file.resolve()
    assert config.data_dir == (tmp_path / "workbench-data").resolve()


def test_absolute_data_override_and_top_level_compatibility(tmp_path):
    config_file = tmp_path / "config.toml"
    data_dir = tmp_path / "absolute"
    config_file.write_text(f'data_dir = "{data_dir}"\n', encoding="utf-8")

    assert AppConfig.load(config_file).data_dir == data_dir.resolve()


def test_editor_and_solver_settings_are_loaded(tmp_path):
    config_file = tmp_path / "config.toml"
    config_file.write_text(
        "[editor]\n"
        'executable = "nvim"\n'
        'args = ["--wait", "--"]\n'
        "\n"
        "[solver]\n"
        'python_interpreter = "/usr/bin/python3"\n'
        "timeout_seconds = 45\n"
        "bash_execution_enabled = true\n",
        encoding="utf-8",
    )

    config = AppConfig.load(config_file)

    assert config.editor == "nvim"
    assert config.editor_args == ("--wait", "--")
    assert config.python_interpreter == "/usr/bin/python3"
    assert config.solver_timeout_seconds == 45
    assert config.bash_execution_enabled is True


def test_invalid_toml_reports_config_path_and_location(tmp_path):
    config_file = tmp_path / "bad.toml"
    config_file.write_text("[paths\n", encoding="utf-8")

    with pytest.raises(ConfigError) as exc:
        AppConfig.load(config_file)

    assert str(config_file) in str(exc.value)
    assert "line" in str(exc.value)


@pytest.mark.parametrize(
    "contents",
    ["[paths]\ndata_dir = 42\n", '[paths]\ndata_dir = ""\n', 'paths = "bad"\n'],
)
def test_invalid_config_values_are_not_accepted(tmp_path, contents):
    config_file = tmp_path / "config.toml"
    config_file.write_text(contents, encoding="utf-8")

    with pytest.raises(ConfigError) as exc:
        AppConfig.load(config_file)

    assert str(config_file) in str(exc.value)


@pytest.mark.parametrize(
    ("section", "message"),
    [
        ('[editor]\nargs = ["ok", 3]\n', "editor.args"),
        ("[solver]\ntimeout_seconds = 0\n", "timeout_seconds"),
        ('[solver]\nbash_execution_enabled = "yes"\n', "bash_execution_enabled"),
        ('[solver]\npython_interpreter = ""\n', "python_interpreter"),
    ],
)
def test_invalid_editor_and_solver_settings_report_config_path(
    tmp_path, section, message
):
    config_file = tmp_path / "config.toml"
    config_file.write_text(section, encoding="utf-8")

    with pytest.raises(ConfigError, match=message) as exc:
        AppConfig.load(config_file)

    assert str(config_file) in str(exc.value)
