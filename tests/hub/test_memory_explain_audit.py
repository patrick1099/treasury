"""memory-explain / memory-audit 的契约测试（CLI-AI 信封 + 退出码 + 判定正确性）。

见 docs/plans/2026-08-31-hub-memory-layering.md §4 / §3.5：
- explain 必须从全量出发解释 scope miss（硬要求 1）；字节数对实际渲染字符串算（硬要求 2）；
  --tool 省略 = 解释全部四个工具（硬要求 3）。
- audit 只列不改：跑完金库 git 状态必须零变化。
"""
import io
import json
import os
import subprocess
from datetime import date, timedelta
from pathlib import Path

import pytest

from hub import cliout
from hub.cli import main
from hub.memview import (MemoryViewEntry, render_view_file, expanded_entry_text)
from hub.memory_ops import (explain_memories, audit_memories, EXPLAIN_TOOLS)


# ---- 金库脚手架 -----------------------------------------------------------

def _meta(name, type_, desc, scope, group=None, archived=None, index=None):
    meta = [f"  type: {type_}", f"  scope: {scope}"]
    if group is not None:
        meta.append(f"  group: {group}")
    if archived is not None:
        meta.append(f"  archived: {archived}")
    if index is not None:
        meta.append(f"  index: {index}")
    return (f"---\nname: {name}\ndescription: {desc}\nmetadata:\n"
            + "\n".join(meta) + "\n---\n正文\n")


def _write_mem(vault, name, type_, desc, scope="[global]", group=None, archived=None, index=None):
    d = vault / "shared" / "memory"
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{name}.md").write_text(
        _meta(name, type_, desc, scope, group, archived, index), encoding="utf-8")


def _mk_vault(tmp_path, host="h1"):
    vault = tmp_path / "vault"
    (vault / host).mkdir(parents=True, exist_ok=True)
    (vault / "vault.toml").write_text("version = 2\n", encoding="utf-8")
    (vault / host / "device.toml").write_text(
        'class = []\nprojects = []\n[paths]\nVAULT = "' + vault.as_posix() + '"\n',
        encoding="utf-8")
    return vault


def _init_git(repo):
    for args in (["init", "-q"], ["config", "user.email", "t@t"],
                 ["config", "user.name", "t"]):
        subprocess.run(["git", *args], cwd=repo, check=True, capture_output=True, text=True)


def _commit(repo, when=None, message="c"):
    env = dict(os.environ)
    if when is not None:
        iso = when.strftime("%Y-%m-%dT%H:%M:%S+08:00")
        env["GIT_AUTHOR_DATE"] = iso
        env["GIT_COMMITTER_DATE"] = iso
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True, text=True)
    subprocess.run(["git", "commit", "-m", message], cwd=repo, check=True,
                   capture_output=True, text=True, env=env)


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


# ---- memory-explain：信封 + 判定 + 字节 -----------------------------------

def test_explain_json_success_envelope(machine_out, machine_err, tmp_path):
    vault = _mk_vault(tmp_path)
    _write_mem(vault, "fb_1", "feedback", "约束A")
    _write_mem(vault, "grp_1", "reference", "说明", group="固件")
    _write_mem(vault, "arc_1", "project", "旧东西", archived="2026-01-01")
    _write_mem(vault, "miss_1", "reference", "只有 codex",
               scope="[tool:codex]")
    rc = main(["memory-explain", "--vault", str(vault), "--host", "h1",
               "--tool", "claude", "--json"])
    assert rc == 0
    assert machine_err.getvalue() == b""
    env = json.loads(machine_out.getvalue().decode("utf-8"))
    assert env["ok"] is True and env["error"] is None
    data = env["data"]
    assert data["tool"] == "claude" and data["host"] == "h1"
    assert len(data["tools"]) == 1
    per = data["tools"][0]
    assert per["tool"] == "claude"
    by_name = {r["name"]: r for r in per["entries"]}
    assert by_name["fb_1"]["decision"] == "expanded"
    assert by_name["fb_1"]["rule"] == "type=feedback"
    assert by_name["grp_1"]["decision"] == "folded"
    assert by_name["grp_1"]["rule"] == "group=固件"
    assert by_name["arc_1"]["decision"] == "archived"
    assert by_name["arc_1"]["rule"] == "archived=2026-01-01"
    assert by_name["miss_1"]["decision"] == "scope_miss"
    assert "tool 不匹配" in by_name["miss_1"]["rule"]
    assert by_name["miss_1"]["bytes"] == 0
    s = per["summary"]
    assert s == {"total": 4, "expanded": 1, "folded": 1, "archived": 1,
                 "scope_miss": 1,
                 "bytes": {"expanded": s["bytes"]["expanded"],
                           "folded": s["bytes"]["folded"],
                           "archived": s["bytes"]["archived"],
                           "total": s["bytes"]["total"]}}


def test_explain_omitted_tool_covers_four_tools(machine_out, tmp_path):
    vault = _mk_vault(tmp_path)
    _write_mem(vault, "fb_1", "feedback", "约束A")
    rc = main(["memory-explain", "--vault", str(vault), "--host", "h1", "--json"])
    assert rc == 0
    data = json.loads(machine_out.getvalue().decode("utf-8"))["data"]
    assert data["tool"] is None
    assert [t["tool"] for t in data["tools"]] == list(EXPLAIN_TOOLS)


def test_explain_scope_miss_device_subscription(machine_out, tmp_path):
    """class/project 谓词对不上本机 → 解释成设备订阅不匹配，而不是悄悄消失。"""
    vault = _mk_vault(tmp_path)
    _write_mem(vault, "w_1", "reference", "只给 work", scope="[class:work]")
    _write_mem(vault, "p_1", "reference", "只给 projx", scope="[project:projx]")
    rc = main(["memory-explain", "--vault", str(vault), "--host", "h1",
               "--tool", "claude", "--json"])
    assert rc == 0
    data = json.loads(machine_out.getvalue().decode("utf-8"))["data"]
    by_name = {r["name"]: r for r in data["tools"][0]["entries"]}
    assert by_name["w_1"]["decision"] == "scope_miss"
    assert "设备订阅不匹配" in by_name["w_1"]["rule"]
    assert "class:work" in by_name["w_1"]["rule"]
    assert by_name["p_1"]["decision"] == "scope_miss"
    assert "project:projx" in by_name["p_1"]["rule"]


def test_explain_index_override_rule(machine_out, tmp_path):
    """index=expanded 的 project 进展开段，规则标 index=expanded（不是 type）。"""
    vault = _mk_vault(tmp_path)
    _write_mem(vault, "idx_1", "project", "项目约束", index="expanded")
    rc = main(["memory-explain", "--vault", str(vault), "--host", "h1",
               "--tool", "claude", "--json"])
    assert rc == 0
    data = json.loads(machine_out.getvalue().decode("utf-8"))["data"]
    row = next(r for r in data["tools"][0]["entries"] if r["name"] == "idx_1")
    assert row["decision"] == "expanded" and row["rule"] == "index=expanded"


def test_explain_bytes_measure_actual_rendered_text(machine_out, tmp_path):
    """字节数必须等于实际渲染串 len(text.encode("utf-8"))——展开条就是渲染视图里那行。"""
    vault = _mk_vault(tmp_path)
    _write_mem(vault, "fb_1", "feedback", "约束A")
    _write_mem(vault, "grp_1", "reference", "说明", group="固件")
    _write_mem(vault, "arc_1", "project", "旧东西", archived="2026-01-01")
    rc = main(["memory-explain", "--vault", str(vault), "--host", "h1",
               "--tool", "claude", "--json"])
    assert rc == 0
    data = json.loads(machine_out.getvalue().decode("utf-8"))["data"]
    by_name = {r["name"]: r for r in data["tools"][0]["entries"]}
    fb_entry = MemoryViewEntry(name="fb_1", description="约束A", type="feedback",
                               scope=["global"], group=None, archived=None,
                               index=None, source=Path("C:/vault/shared/memory/fb_1.md"))
    line = expanded_entry_text(fb_entry)
    assert by_name["fb_1"]["bytes"] == len(line.encode("utf-8"))
    assert line in render_view_file([fb_entry], "claude", "h")
    assert by_name["grp_1"]["bytes"] == len("grp_1".encode("utf-8"))
    assert by_name["arc_1"]["bytes"] == len("arc_1".encode("utf-8"))


def test_explain_human_mode(tmp_path, capsys):
    vault = _mk_vault(tmp_path)
    _write_mem(vault, "fb_1", "feedback", "约束A")
    rc = main(["memory-explain", "--vault", str(vault), "--host", "h1",
               "--tool", "claude"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "# memory-explain" in out and "claude" in out
    assert "type=feedback" in out


def test_explain_without_vault_rc1(machine_out, machine_err):
    rc = main(["memory-explain", "--host", "h1", "--json"])
    assert rc == 1
    err = json.loads(machine_err.getvalue().decode("utf-8"))
    assert err["ok"] is False and err["error"]["code"] == "E_NOT_FOUND"


def test_explain_bad_tool_rc2(machine_out, machine_err, tmp_path):
    vault = _mk_vault(tmp_path)
    with pytest.raises(SystemExit) as ei:
        main(["memory-explain", "--vault", str(vault), "--host", "h1",
              "--tool", "bogus", "--json"])
    assert ei.value.code == 2
    err = json.loads(machine_err.getvalue().decode("utf-8"))
    assert err["error"]["code"] == "E_VALIDATION"


# ---- memory-audit：三类候选 + 只读 ----------------------------------------

def _done_project(vault, name, desc="已闭环"):
    _write_mem(vault, name, "project", desc)


def test_audit_json_success(machine_out, machine_err, tmp_path):
    vault = _mk_vault(tmp_path)
    _init_git(vault)
    _done_project(vault, "done_1")                                   # 疑似完成
    _write_mem(vault, "plain_1", "project", "长期约束，无完成词")       # 不是候选
    _write_mem(vault, "stale_1", "project", "老项目", archived=None)
    _write_mem(vault, "old_arc", "reference", "退役", archived="2026-01-01")
    _commit(vault, when=date.today() - timedelta(days=200))
    rc = main(["memory-audit", "--vault", str(vault), "--host", "h1", "--json"])
    assert rc == 0
    assert machine_err.getvalue() == b""
    env = json.loads(machine_out.getvalue().decode("utf-8"))
    assert env["ok"] is True and env["error"] is None
    data = env["data"]
    assert data["stale_days"] == 90 and data["archived_days"] == 180
    assert data["git_available"] is True and data["git_clean"] is True
    cand = data["candidates"]
    assert [c["name"] for c in cand["possibly_done"]] == ["done_1"]
    assert "已闭环" in cand["possibly_done"][0]["words"]
    assert [c["name"] for c in cand["stale"]] == ["done_1", "plain_1", "stale_1"]
    assert all(c["days"] > 90 for c in cand["stale"])
    assert [c["name"] for c in cand["archived_long"]] == ["old_arc"]
    assert cand["archived_long"][0]["days"] > 180


def test_audit_thresholds_are_cli_args(machine_out, tmp_path):
    """两个阈值必须可调：把 stale 阈值调小/大，候选跟着进出。"""
    vault = _mk_vault(tmp_path)
    _init_git(vault)
    _done_project(vault, "done_1")
    _write_mem(vault, "stale_1", "project", "老项目")
    _write_mem(vault, "old_arc", "reference", "退役", archived="2026-01-01")
    _commit(vault, when=date.today() - timedelta(days=100))
    main(["memory-audit", "--vault", str(vault), "--host", "h1",
          "--stale-days", "150", "--archived-days", "60", "--json"])
    data = json.loads(machine_out.getvalue().decode("utf-8"))["data"]
    assert data["stale_days"] == 150 and data["archived_days"] == 60
    assert data["candidates"]["stale"] == []           # 100 天 < 150，不列
    assert len(data["candidates"]["archived_long"]) == 1   # 200 天 > 60，列


def test_audit_read_only_git_status_unchanged(machine_out, tmp_path):
    """只列不改：跑完 audit，金库 git 状态必须仍是干净的。"""
    vault = _mk_vault(tmp_path)
    _init_git(vault)
    _done_project(vault, "done_1")
    _commit(vault)
    before = subprocess.run(["git", "-C", str(vault), "status", "--porcelain"],
                            capture_output=True, text=True).stdout
    rc = main(["memory-audit", "--vault", str(vault), "--host", "h1", "--json"])
    assert rc == 0
    after = subprocess.run(["git", "-C", str(vault), "status", "--porcelain"],
                           capture_output=True, text=True).stdout
    assert after == before == ""
    assert json.loads(machine_out.getvalue().decode("utf-8"))["data"]["git_clean"] is True


def test_audit_not_git_vault(machine_out, tmp_path):
    """不是 git 仓：不崩、git_available False、久未更新段为空。"""
    vault = _mk_vault(tmp_path)
    _write_mem(vault, "done_1", "project", "已闭环")
    rc = main(["memory-audit", "--vault", str(vault), "--host", "h1", "--json"])
    assert rc == 0
    data = json.loads(machine_out.getvalue().decode("utf-8"))["data"]
    assert data["git_available"] is False
    assert data["candidates"]["stale"] == []
    assert [c["name"] for c in data["candidates"]["possibly_done"]] == ["done_1"]


def test_audit_human_mode(tmp_path, capsys):
    vault = _mk_vault(tmp_path)
    _init_git(vault)
    _done_project(vault, "done_1")
    _commit(vault)
    rc = main(["memory-audit", "--vault", str(vault), "--host", "h1"])
    assert rc == 0
    out = capsys.readouterr().out
    assert "# memory-audit" in out and "疑似完成" in out
    assert "done_1" in out


def test_audit_missing_vault_rc1(machine_out, machine_err):
    rc = main(["memory-audit", "--json"])
    assert rc == 1
    err = json.loads(machine_err.getvalue().decode("utf-8"))
    assert err["error"]["code"] == "E_NOT_FOUND"


def test_audit_vault_dir_missing_rc1(machine_out, machine_err, tmp_path):
    rc = main(["memory-audit", "--vault", str(tmp_path / "nope"),
               "--host", "h1", "--json"])
    assert rc == 1
    err = json.loads(machine_err.getvalue().decode("utf-8"))
    assert err["error"]["code"] == "E_NOT_FOUND"


def test_core_functions_share_classify_entries(tmp_path):
    """audit 的归档池走 classify_entries（与视图同一判据）——不是又一套『什么算归档』。"""
    vault = _mk_vault(tmp_path)
    _write_mem(vault, "arc_1", "project", "旧东西", archived="2026-01-01")
    _write_mem(vault, "live_1", "project", "进行中")
    from hub.memview import load_shared_memories, validate_scopes, classify_entries, _view_entry
    mems = load_shared_memories(vault)
    validate_scopes(mems)
    cls = classify_entries([_view_entry(m, vault) for m in mems])
    assert [e.name for e in cls.archived] == ["arc_1"]
