from agent_harness.graph.diff_viewer import (
    compute_checkpoint_diffs,
    format_colored_diff,
    generate_unified_diff,
)


def test_generate_unified_diff():
    before = "line 1\nline 2\nline 3\n"
    after = "line 1\nline 2 modified\nline 3\nline 4\n"

    diff = generate_unified_diff(before, after, filename="config.py")
    assert "--- a/config.py" in diff
    assert "+++ b/config.py" in diff
    assert "-line 2" in diff
    assert "+line 2 modified" in diff
    assert "+line 4" in diff


def test_format_colored_diff():
    diff = "--- a/test\n+++ b/test\n@@ -1 +1 @@\n-old\n+new\n"
    rich_text = format_colored_diff(diff)
    assert len(rich_text.spans) >= 4


def test_compute_checkpoint_diffs(temp_workspace):
    snaps_dir = temp_workspace / "snaps"
    ckpt_a = snaps_dir / "ckpt_1"
    ckpt_b = snaps_dir / "ckpt_2"

    ckpt_a.mkdir(parents=True)
    ckpt_b.mkdir(parents=True)

    (ckpt_a / "app.py").write_text("def hello(): pass\n", encoding="utf-8")
    (ckpt_b / "app.py").write_text("def hello(): return 'world'\n", encoding="utf-8")

    diffs = compute_checkpoint_diffs(snaps_dir, "ckpt_1", "ckpt_2")
    assert "app.py" in diffs
    assert "+def hello(): return 'world'" in diffs["app.py"]
