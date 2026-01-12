#!/usr/bin/env python3
"""
Toy SwiftUI accessibility linter + autofixer (POC quality).

Rule A11Y001:
  If a Button's label contains Image(systemName: "...") and there is no
  .accessibilityLabel(...) nearby, flag it.

This is intentionally heuristic for a demo. A real product should use SwiftSyntax.
"""

from __future__ import annotations

import argparse
import json
import os
import re
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List, Optional, Tuple

RULE_ID = "A11Y001"
RULE_TITLE = "Icon-only Button missing accessibilityLabel"

# Tiny, dumb mapping for demo “smartness”.
SF_SYMBOL_TO_LABEL = {
    "gearshape": "Settings",
    "gearshape.fill": "Settings",
    "magnifyingglass": "Search",
    "plus": "Add",
    "trash": "Delete",
    "pencil": "Edit",
    "xmark": "Close",
    "chevron.left": "Back",
}

IGNORE_DIRS = {
    ".git", ".github", "DerivedData", "Pods", "Carthage", ".build", "build"
}

IMAGE_RE = re.compile(r'Image\s*\(\s*systemName\s*:\s*"([^"]+)"\s*\)')
BUTTON_RE = re.compile(r'\bButton\b')


@dataclass
class Issue:
    rule: str
    title: str
    path: str
    line: int
    symbol: str
    suggested_label: str
    message: str


def iter_swift_files(root: Path) -> List[Path]:
    files: List[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        # prune ignored dirs
        dirnames[:] = [d for d in dirnames if d not in IGNORE_DIRS]
        for fn in filenames:
            if fn.endswith(".swift"):
                files.append(Path(dirpath) / fn)
    return files


def find_issues_in_file(path: Path) -> List[Issue]:
    lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    issues: List[Issue] = []
    seen = set()  # <--- ADD THIS

    # Heuristic:
    # For each line that contains "Button", look at a small window after it.
    # If we see Image(systemName: ...) in that window but no accessibilityLabel, flag it.
    for i, line in enumerate(lines):
        if not BUTTON_RE.search(line):
            continue

        window_start = i
        window_end = min(len(lines), i + 40)
        window = "\n".join(lines[window_start:window_end])

        if ".accessibilityLabel" in window:
            continue

        # Find first Image(systemName:) in window.
        m = IMAGE_RE.search(window)
        if not m:
            continue

        symbol = m.group(1)
        suggested = SF_SYMBOL_TO_LABEL.get(symbol, "TODO")

        # Find the line number for that Image(...) match.
        # We re-scan line by line in the window to locate it.
        image_line_idx = None
        for j in range(window_start, window_end):
            if IMAGE_RE.search(lines[j]):
                image_line_idx = j
                break

        msg = (
            f"Add .accessibilityLabel(\"{suggested}\") so VoiceOver/TalkBack "
            "announce what this icon button does."
        )
        if image_line_idx is None:
            continue

        key = (str(path.as_posix()), image_line_idx + 1, symbol, RULE_ID)
        if key in seen:
            continue
        seen.add(key)
        issues.append(Issue(
            rule=RULE_ID,
            title=RULE_TITLE,
            path=str(path.as_posix()),
            line=image_line_idx + 1,
            symbol=symbol,
            suggested_label=suggested,
            message=msg,
        ))

    return issues


def emit_github_annotations(issues: List[Issue]) -> None:
    # GitHub workflow command format:
    # ::error file=...,line=...,title=...::message
    # Docs: Workflow commands create annotations tied to a file/line.  [oai_citation:2‡GitHub Docs](https://docs.github.com/en/actions/reference/workflows-and-actions/workflow-commands?utm_source=chatgpt.com)
    for iss in issues:
        title = f"{iss.rule} {iss.title}"
        print(f"::error file={iss.path},line={iss.line},title={title}::{iss.message}")


def write_markdown_report(issues: List[Issue], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if not issues:
        body = """<!-- a11y-bot -->
## ✅ SwiftUI Accessibility Report

No issues found.
"""
        out_path.write_text(body, encoding="utf-8")
        return

    lines = []
    lines.append("<!-- a11y-bot -->")
    lines.append("## ❌ SwiftUI Accessibility Report")
    lines.append("")
    lines.append(f"Found **{len(issues)}** issue(s).")
    lines.append("")
    for idx, iss in enumerate(issues, start=1):
        lines.append(f"### {idx}) `{iss.rule}` — {iss.title}")
        lines.append(f"- File: `{iss.path}:{iss.line}`")
        lines.append(f"- Detected icon: `{iss.symbol}`")
        lines.append(f"- Recommended label: **{iss.suggested_label}**")
        lines.append("")
        lines.append("Suggested fix:")
        lines.append("```swift")
        lines.append(f'Image(systemName: "{iss.symbol}")')
        lines.append(f'    .accessibilityLabel("{iss.suggested_label}")')
        lines.append("```")
        lines.append("")
        lines.append("Why this matters:")
        lines.append("- Screen readers use accessibility metadata. Without a label, users may only hear “Button” with no meaning.")
        lines.append("")
        lines.append("To auto-fix this PR, comment:")
        lines.append("`/a11y-fix`")
        lines.append("")

    out_path.write_text("\n".join(lines).strip() + "\n", encoding="utf-8")


def write_json_report(issues: List[Issue], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "count": len(issues),
        "issues": [asdict(i) for i in issues],
    }
    out_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")


def apply_autofix(root: Path, issues: List[Issue]) -> int:
    """
    Simple fix: after the first Image(systemName: "...") in the flagged window,
    insert `.accessibilityLabel("...")` on the next line if not present.
    """
    changed_files = 0

    by_file: dict[str, List[Issue]] = {}
    for iss in issues:
        by_file.setdefault(iss.path, []).append(iss)

    for file_path, file_issues in by_file.items():
        p = (root / file_path).resolve()
        if not p.exists():
            continue
        lines = p.read_text(encoding="utf-8", errors="replace").splitlines()

        changed = False
        for iss in sorted(file_issues, key=lambda x: x.line, reverse=True):
            idx = iss.line - 1
            if idx < 0 or idx >= len(lines):
                continue

            # Don’t double-add if label already present in next few lines
            lookahead = "\n".join(lines[idx: min(len(lines), idx + 6)])
            if ".accessibilityLabel" in lookahead:
                continue

            indent = re.match(r"^\s*", lines[idx]).group(0)
            # Standard SwiftUI indentation for chained modifiers
            insert_line = indent + "    " + f'.accessibilityLabel("{iss.suggested_label}")'
            lines.insert(idx + 1, insert_line)
            changed = True

        if changed:
            p.write_text("\n".join(lines) + "\n", encoding="utf-8")
            changed_files += 1

    return changed_files


def main() -> int:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)

    lint = sub.add_parser("lint")
    lint.add_argument("--root", default=".")
    lint.add_argument("--report", default="out/a11y_report.md")
    lint.add_argument("--json", default="out/a11y_report.json")
    lint.add_argument("--github-annotations", action="store_true")

    fix = sub.add_parser("autofix")
    fix.add_argument("--root", default=".")
    fix.add_argument("--report", default="out/a11y_fix_report.md")
    fix.add_argument("--json", default="out/a11y_fix_report.json")
    fix.add_argument("--github-annotations", action="store_true")

    args = ap.parse_args()
    root = Path(args.root).resolve()

    all_issues: List[Issue] = []
    for f in iter_swift_files(root):
        file_issues = find_issues_in_file(f)
        # rewrite issue paths to be repo-relative
        for iss in file_issues:
            iss.path = str(Path(iss.path).resolve().relative_to(root))
        all_issues.extend(file_issues)

    if getattr(args, "github_annotations", False):
        emit_github_annotations(all_issues)

    if args.cmd == "lint":
        write_markdown_report(all_issues, Path(args.report))
        write_json_report(all_issues, Path(args.json))
        return 0

    if args.cmd == "autofix":
        changed_files = apply_autofix(root, all_issues)
        write_markdown_report(all_issues, Path(args.report))
        write_json_report(all_issues, Path(args.json))
        print(f"AutoFix changed {changed_files} file(s).")
        return 0

    return 0


if __name__ == "__main__":
    raise SystemExit(main())