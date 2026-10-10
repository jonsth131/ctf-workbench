"""Tests for CLI-controlled file logging."""

from __future__ import annotations

import os
import stat

from ctfwb import AppConfig
from ctfwb.app import main
from ctfwb.logging_setup import APP_LOGGER, log_debug_exception


def test_main_logs_errors_and_only_enables_debug_with_flag(tmp_path, monkeypatch):
    data_dir = tmp_path / "user-data"
    config = AppConfig(data_dir=data_dir, config_path=tmp_path / "config.toml")
    monkeypatch.setattr("ctfwb.app.AppConfig.load", lambda _path=None: config)

    class AppStub:
        def __init__(self, *, data_store, config) -> None:
            assert config is not None
            assert data_store.data_dir == data_dir
            editor = config.editor
            editor_args = config.editor_args
            assert editor == "nvim"
            assert editor_args == ()

        def run(self) -> None:
            APP_LOGGER.error("simulated application error")
            APP_LOGGER.debug("simulated diagnostic details")
            try:
                error = RuntimeError("sensitive exception contents")
                raise error
            except RuntimeError as error:
                log_debug_exception("simulated exception traceback", error)

    monkeypatch.setattr("ctfwb.app.CTFWorkbenchApp", AppStub)
    log_path = data_dir / "logs" / "ctf-workbench.log"
    if os.name != "nt":
        log_path.parent.mkdir(parents=True)
        log_path.write_text("existing log\n", encoding="utf-8")
        log_path.chmod(0o644)

    assert main(config.config_path, argv=[]) == 0
    regular_log = log_path.read_text(encoding="utf-8")
    assert "existing log" in regular_log
    assert "simulated application error" in regular_log
    assert "simulated diagnostic details" not in regular_log
    assert "simulated exception traceback" not in regular_log

    assert main(config.config_path, argv=["--debug"]) == 0
    debug_log = log_path.read_text(encoding="utf-8")
    assert "simulated diagnostic details" in debug_log
    assert "simulated exception traceback (RuntimeError)" in debug_log
    assert "sensitive exception contents" not in debug_log
    assert "raise error" in debug_log

    if os.name != "nt":
        assert stat.S_IMODE(log_path.stat().st_mode) == 0o600
