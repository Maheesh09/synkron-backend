from app.agents.code_analyzer import DIFF_BUDGET, pack_diff


def _section(path: str, size: int) -> str:
    header = f"diff --git a/{path} b/{path}\n--- a/{path}\n+++ b/{path}\n@@ -1 +1 @@\n"
    line = f"+ change in {path}\n"
    return header + line * ((size - len(header)) // len(line))


def _diff():
    files = [("app/utils/strings.py", 5000), ("app/services/cache.py", 5000),
             ("scripts/cleanup.py", 5000), ("app/models/user.py", 2500),
             ("app/routers/users.py", 2500)]          # routes file LAST
    return {p: _section(p, n) for p, n in files}


def test_routes_file_survives_even_when_last_in_a_large_diff():
    sections = _diff()
    raw = "\n".join(sections.values())
    assert len(raw) > 19_000

    packed = pack_diff(raw)

    assert len(packed) <= DIFF_BUDGET + 500        # budget plus the omitted-files note
    assert sections["app/routers/users.py"].strip() in packed
    assert sections["app/models/user.py"].strip() in packed


def test_sections_are_never_cut_in_half_and_omissions_are_listed():
    sections = _diff()
    packed = pack_diff("\n".join(sections.values()))

    for path, body in sections.items():
        if f"diff --git a/{path}" in packed:
            assert body.strip() in packed, f"{path} was truncated"
        else:
            assert path in packed.split("not shown")[-1], f"{path} omitted silently"


def test_small_diff_is_unchanged():
    raw = _section("app/routers/a.py", 300) + _section("README_helper.py", 300)
    assert pack_diff(raw).strip() == raw.strip()


def test_single_oversized_file_is_cut_on_a_line_boundary():
    raw = _section("app/routers/huge.py", DIFF_BUDGET * 2)
    packed = pack_diff(raw)
    assert packed.startswith("diff --git a/app/routers/huge.py")
    body = packed.split("\n[")[0]
    assert all(l.startswith(("+", "-", " ", "diff", "---", "+++", "@@")) for l in body.splitlines())
    assert len(packed) <= DIFF_BUDGET + 500
