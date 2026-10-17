from ctfwb import app
from ctfwb.tools import ExternalToolHelper


def test_doctor_reports_installed_and_missing_tools(monkeypatch, capsys):
    monkeypatch.setattr(
        ExternalToolHelper,
        "find_executable",
        lambda self: f"/usr/bin/{self.executable}",
    )

    assert app.main(argv=["doctor"]) == 0
    assert capsys.readouterr().out == (
        "External tool helpers:\n"
        "  exiftool: installed (/usr/bin/exiftool)\n"
        "  steghide: installed (/usr/bin/steghide)\n"
        "  zsteg: installed (/usr/bin/zsteg)\n"
        "  tshark: installed (/usr/bin/tshark)\n"
    )

    monkeypatch.setattr(ExternalToolHelper, "find_executable", lambda self: None)

    assert app.main(argv=["doctor"]) == 1
    assert capsys.readouterr().out == (
        "External tool helpers:\n"
        "  exiftool: missing (exiftool not found on PATH)\n"
        "  steghide: missing (steghide not found on PATH)\n"
        "  zsteg: missing (zsteg not found on PATH)\n"
        "  tshark: missing (tshark not found on PATH)\n"
    )


def test_doctor_does_not_load_configuration(monkeypatch):
    def fail_if_called(*args, **kwargs):
        raise AssertionError("doctor should not load app configuration")

    monkeypatch.setattr(app.AppConfig, "load", fail_if_called)
    monkeypatch.setattr(
        ExternalToolHelper,
        "find_executable",
        lambda self: f"/bin/{self.executable}",
    )

    assert app.main(argv=["doctor"]) == 0
