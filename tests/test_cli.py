from ctfwb import app
from ctfwb.tools.external import ExternalToolHelper


def test_doctor_reports_installed_and_missing_tools(monkeypatch, capsys):
    monkeypatch.setattr(
        ExternalToolHelper,
        "find_executable",
        lambda self: "/usr/bin/exiftool",
    )

    assert app.main(argv=["doctor"]) == 0
    assert capsys.readouterr().out == (
        "External tool helpers:\n  exiftool: installed (/usr/bin/exiftool)\n"
    )

    monkeypatch.setattr(ExternalToolHelper, "find_executable", lambda self: None)

    assert app.main(argv=["doctor"]) == 1
    assert capsys.readouterr().out == (
        "External tool helpers:\n  exiftool: missing (exiftool not found on PATH)\n"
    )


def test_doctor_does_not_load_configuration(monkeypatch):
    def fail_if_called(*args, **kwargs):
        raise AssertionError("doctor should not load app configuration")

    monkeypatch.setattr(app.AppConfig, "load", fail_if_called)
    monkeypatch.setattr(
        ExternalToolHelper,
        "find_executable",
        lambda self: "/bin/exiftool",
    )

    assert app.main(argv=["doctor"]) == 0
