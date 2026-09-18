#!/usr/bin/env python3
"""Guard: every plugin.json's "description" must fit within DESCRIPTION_LIMIT chars.

A too-long description broke plugin installation for a student (Eli Tal,
15/09/2026 feedback): skills/rebuild-plugin's description was 541 chars and
the plugin was rejected on install. Anthropic's own manifest docs recommend
50-200 chars for the description field (no documented hard cap was found);
500 is used here as a conservative outer ceiling - comfortably below the
541 chars that actually broke an install, and far above the recommended
range, so it won't flag reasonably-written descriptions.

Usage:
    python3 scripts/check_plugin_descriptions.py              # check the repo
    python3 scripts/check_plugin_descriptions.py --self-test  # prove the guard isn't vacuous
"""
import argparse
import json
import sys
from pathlib import Path

DESCRIPTION_LIMIT = 500
REPO_ROOT = Path(__file__).resolve().parent.parent

# The exact description that broke rebuild-plugin's install for a student.
# Kept verbatim as a fixture so the guard proves itself against a real
# failure instead of a synthetic string.
KNOWN_BAD_DESCRIPTION = (
    "אריזת סוכן מחדש לקובץ פלאגין (.plugin), התקנה אוטומטית והחלפת הגרסה הישנה - "
    "עם 4 בדיקות מבנה (שורש הפלאגין, מיקום SKILL.md, BOM, סכמת plugin.json), "
    "רישום מלא של הפלאגין (installed_plugins + marketplace + enabledPlugins), "
    "אריזה תקינה בכל מערכת הפעלה, וגיבוי+אימות+שחזור בהתקנה. לתלמידי טירונות סוכנים. "
    "Repackage an agent into a .plugin and auto-install/replace the old version, "
    "with 4 structure checks, full plugin registration (installed_plugins + "
    "marketplace + enabledPlugins), cross-OS-safe archiving, and backup/verify/"
    "restore on install."
)


def find_plugin_manifests(root: Path):
    return sorted(root.rglob(".claude-plugin/plugin.json"))


def description_fits(description: str, limit: int = DESCRIPTION_LIMIT) -> bool:
    return len(description) <= limit


def run_self_test() -> None:
    known_bad_len = len(KNOWN_BAD_DESCRIPTION)
    assert known_bad_len == 541, (
        f"fixture drifted: expected the known-bad description to be 541 chars, "
        f"got {known_bad_len} - update KNOWN_BAD_DESCRIPTION or this assertion"
    )
    assert not description_fits(KNOWN_BAD_DESCRIPTION), (
        "guard failed to flag the known-bad (541-char) description that actually "
        "broke a student's install - the guard is vacuous"
    )
    assert description_fits("x" * DESCRIPTION_LIMIT), (
        "guard rejected a description exactly at the limit (off-by-one)"
    )
    assert not description_fits("x" * (DESCRIPTION_LIMIT + 1)), (
        "guard accepted a description one char over the limit (off-by-one)"
    )
    print(
        f"self-test OK: guard correctly flags descriptions over {DESCRIPTION_LIMIT} "
        f"chars, proven against the 541-char description that broke a real install"
    )


def run_repo_check(root: Path) -> int:
    manifests = find_plugin_manifests(root)
    if not manifests:
        print(f"no plugin.json files found under {root}", file=sys.stderr)
        return 1

    failures = []
    for path in manifests:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            failures.append((path, f"invalid JSON: {exc}"))
            continue
        description = data.get("description", "")
        if not description_fits(description):
            failures.append(
                (path, f"description is {len(description)} chars (limit {DESCRIPTION_LIMIT})")
            )

    if failures:
        print(f"FAIL: {len(failures)} plugin.json manifest(s) exceed the description limit:")
        for path, reason in failures:
            print(f"  - {path.relative_to(root)}: {reason}")
        return 1

    print(f"OK: {len(manifests)} plugin.json manifest(s) checked, all descriptions <= {DESCRIPTION_LIMIT} chars")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="prove the guard logic isn't vacuous (checks fixtures, not the repo), then exit",
    )
    args = parser.parse_args()

    if args.self_test:
        run_self_test()
        return 0

    return run_repo_check(REPO_ROOT)


if __name__ == "__main__":
    raise SystemExit(main())
