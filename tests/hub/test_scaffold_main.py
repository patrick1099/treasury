import io
import json
import pytest
from hub import cliout
from hub.scaffold_vault import main


@pytest.fixture
def machine_out(monkeypatch):
    buf = io.BytesIO()
    monkeypatch.setattr(cliout, "_MACHINE_OUT", buf)
    return buf


@pytest.fixture
def machine_err(monkeypatch):
    buf = io.BytesIO()
    monkeypatch.setattr(cliout, "_MACHINE_ERR", buf)
    return buf


def test_json_success_envelope(machine_out, machine_err, tmp_path):
    rc = main([str(tmp_path), "box1", "--json"])
    assert rc == 0
    assert machine_err.getvalue() == b""
    parsed = json.loads(machine_out.getvalue().decode("utf-8"))
    assert parsed["ok"] is True
    assert parsed["error"] is None
    assert parsed["data"]["vault"] == str(tmp_path)
    assert parsed["data"]["host"] == "box1"
    assert parsed["data"]["dry_run"] is False
    assert (tmp_path / "vault.toml").is_file()


def test_json_business_failure_envelope(machine_out, machine_err, tmp_path):
    (tmp_path / "别人的文件.txt").write_text("x", encoding="utf-8")
    rc = main([str(tmp_path), "box1", "--json"])
    assert rc == 1
    assert machine_out.getvalue() == b""
    err = json.loads(machine_err.getvalue().decode("utf-8"))
    assert err["ok"] is False
    assert err["data"] is None
    assert err["error"]["code"] == "E_VALIDATION"
    assert err["error"]["retryable"] is False
    assert "vault.toml" in err["error"]["message"]


def test_json_argparse_error_envelope(machine_out, machine_err):
    with pytest.raises(SystemExit) as ei:
        main(["--json"])
    assert ei.value.code == 2
    assert machine_out.getvalue() == b""
    err = json.loads(machine_err.getvalue().decode("utf-8"))
    assert err["ok"] is False
    assert err["error"]["code"] == "E_VALIDATION"


def test_format_json_equiv(machine_out, tmp_path):
    base = str(tmp_path)
    cases = (
        [base, "box1", "--json", "--dry-run"],
        [base, "box1", "--format", "json", "--dry-run"],
        [base, "box1", "--format=json", "--dry-run"],
    )
    outs = []
    for argv in cases:
        machine_out.truncate(0)
        machine_out.seek(0)
        assert main(argv) == 0
        outs.append(machine_out.getvalue())
    assert outs[0] == outs[1] == outs[2]
    assert list(tmp_path.iterdir()) == []


def test_ai_help_content(machine_out):
    assert main(["--ai-help"]) == 0
    text = machine_out.getvalue().decode("utf-8")
    assert "name: hub-scaffold" in text
    assert "description:" in text
    assert "ai_help_version: 0.1.0" in text
    for sec in ("## When to Use", "## Quick Reference", "## Command Reference",
                "## Side Effects & Safety", "## Exit Codes", "## Errors & Recovery"):
        assert sec in text


def test_ai_help_eager_produces_no_files(machine_out, tmp_path):
    rc = main([str(tmp_path), "box1", "--ai-help"])
    assert rc == 0
    assert b"name: hub-scaffold" in machine_out.getvalue()
    assert list(tmp_path.iterdir()) == []


def test_ai_help_eager_unknown_args(machine_out):
    assert main(["--garbage", "--ai-help"]) == 0
    assert b"name: hub-scaffold" in machine_out.getvalue()


def test_ai_help_terminator(machine_out):
    with pytest.raises(SystemExit) as ei:
        main(["--", "--ai-help"])
    assert ei.value.code == 2
    assert machine_out.getvalue() == b""


def test_json_dry_run(machine_out, machine_err, tmp_path):
    rc = main([str(tmp_path), "box1", "--json", "--dry-run"])
    assert rc == 0
    parsed = json.loads(machine_out.getvalue().decode("utf-8"))
    assert parsed["ok"] is True
    assert parsed["data"]["dry_run"] is True
    assert list(tmp_path.iterdir()) == []


def test_human_default_success(tmp_path, capsys):
    rc = main([str(tmp_path), "box1"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "金库已建在" in out
    out.encode("utf-8")
    assert (tmp_path / "vault.toml").is_file()


def test_human_business_failure_stderr(tmp_path, capsys):
    (tmp_path / "x.txt").write_text("x", encoding="utf-8")
    rc = main([str(tmp_path), "box1"])
    assert rc == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "vault.toml" in captured.err


def test_machine_channel_single_envelope_no_pollution(machine_out, machine_err,
                                                      tmp_path, capsys):
    rc = main([str(tmp_path), "box1", "--json"])
    assert rc == 0
    json.loads(machine_out.getvalue())
    assert machine_err.getvalue() == b""
    assert capsys.readouterr().out == ""


def test_machine_channel_error_single_envelope_no_pollution(machine_out, machine_err,
                                                            tmp_path, capsys):
    target = tmp_path / "nonempty"
    target.mkdir()
    (target / "x.txt").write_text("x", encoding="utf-8")
    rc = main([str(target), "box1", "--json"])
    assert rc == 1
    assert machine_out.getvalue() == b""
    err = json.loads(machine_err.getvalue().decode("utf-8"))
    assert err["error"]["code"] == "E_VALIDATION"
    assert capsys.readouterr().out == ""
