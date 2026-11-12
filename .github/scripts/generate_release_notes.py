#!/usr/bin/env python3
"""Generate Chinese release notes from Conventional Commit messages."""

from __future__ import annotations

import argparse
import os
import re
import subprocess
from collections import defaultdict
from pathlib import Path


FIELD_SEPARATOR = "\x1f"
RECORD_SEPARATOR = "\x1e"

CATEGORY_ORDER = (
    "新功能",
    "问题修复",
    "性能与可靠性",
    "文档",
    "构建与发布",
    "测试",
    "其他维护",
)

TYPE_TO_CATEGORY = {
    "feat": "新功能",
    "fix": "问题修复",
    "revert": "问题修复",
    "perf": "性能与可靠性",
    "refactor": "性能与可靠性",
    "docs": "文档",
    "build": "构建与发布",
    "ci": "构建与发布",
    "test": "测试",
    "chore": "其他维护",
    "style": "其他维护",
}

CONVENTIONAL_COMMIT = re.compile(
    r"^(?P<type>[a-zA-Z]+)(?:\((?P<scope>[^)]+)\))?!?:\s*(?P<summary>.+)$"
)


def git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    return result.stdout.rstrip("\r\n")


def find_previous_tag(tag: str) -> str | None:
    try:
        parent = git("rev-list", "-n", "1", tag + "^")
    except subprocess.CalledProcessError:
        return None

    tags = git("tag", "--merged", parent, "--sort=-version:refname", "--list", "v*")
    return next((candidate for candidate in tags.splitlines() if candidate != tag), None)


def repository_name() -> str:
    configured = os.environ.get("GITHUB_REPOSITORY", "").strip()
    if configured:
        return configured

    remote = git("remote", "get-url", "origin")
    match = re.search(r"github\.com[:/](?P<repo>[^/]+/[^/]+?)(?:\.git)?$", remote)
    if not match:
        raise SystemExit("无法从 origin 识别 GitHub 仓库，请设置 GITHUB_REPOSITORY")
    return match.group("repo")


def collect_commits(tag: str, previous_tag: str | None) -> list[dict[str, str]]:
    revision = tag if previous_tag is None else previous_tag + ".." + tag
    raw = git(
        "log",
        "--reverse",
        "--format=%H%x1f%s%x1f%b%x1e",
        revision,
    )

    commits = []
    for record in raw.split(RECORD_SEPARATOR):
        record = record.strip("\r\n")
        if not record:
            continue
        fields = record.split(FIELD_SEPARATOR, 2)
        if len(fields) != 3:
            continue
        sha, subject, body = fields
        match = CONVENTIONAL_COMMIT.match(subject.strip())
        if match:
            summary = match.group("summary").strip()
            scope = (match.group("scope") or "").strip()
            category = TYPE_TO_CATEGORY.get(match.group("type").lower(), "其他维护")
        else:
            summary = subject.strip()
            scope = ""
            category = "其他维护"

        commits.append(
            {
                "sha": sha[:7],
                "summary": summary,
                "scope": scope,
                "category": category,
                "body": body.strip(),
            }
        )
    return commits


def render_notes(
    tag: str,
    repository: str,
    previous_tag: str | None,
    commits: list[dict[str, str]],
) -> str:
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    for commit in commits:
        grouped[commit["category"]].append(commit)

    lines = [
        "## UESTC 电费监控 " + tag,
        "",
        "本次发布包含以下变更。",
        "",
    ]

    for category in CATEGORY_ORDER:
        items = grouped.get(category)
        if not items:
            continue
        lines.extend(["### " + category, ""])
        for item in items:
            scope = "**" + item["scope"] + "**：" if item["scope"] else ""
            link = (
                "https://github.com/"
                + repository
                + "/commit/"
                + item["sha"]
            )
            lines.append("- " + scope + item["summary"] + "（[" + item["sha"] + "](" + link + ")）")
        lines.append("")

    lines.extend(
        [
            "### 下载说明",
            "",
            "- **Windows 单文件**：`uestc-energy-windows.exe`，解压运行。",
            "- **Windows 目录版**：`uestc-energy-windows-onedir.zip`，适合单文件版被安全软件拦截时使用。",
            "- **Linux 单文件**：`uestc-energy-linux`，添加执行权限后运行。",
            "- **Linux 目录版**：`uestc-energy-linux-onedir.zip`，适合单文件版无法启动时使用。",
            "",
        ]
    )

    if previous_tag:
        compare_url = (
            "https://github.com/"
            + repository
            + "/compare/"
            + previous_tag
            + "..."
            + tag
        )
        lines.append("**完整变更**：[" + previous_tag + "..." + tag + "](" + compare_url + ")")
    else:
        lines.append(
            "**完整变更**：[查看 "
            + tag
            + "](https://github.com/"
            + repository
            + "/tree/"
            + tag
            + ")"
        )

    return "\n".join(lines).rstrip() + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--tag",
        default=os.environ.get("GITHUB_REF_NAME", ""),
        help="Release tag, defaults to GITHUB_REF_NAME",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("release-notes.md"),
        help="Output Markdown path",
    )
    args = parser.parse_args()

    if not args.tag:
        parser.error("--tag is required when GITHUB_REF_NAME is not set")

    try:
        git("rev-parse", "--verify", "refs/tags/" + args.tag + "^{commit}")
    except subprocess.CalledProcessError as exc:
        raise SystemExit("找不到标签：" + args.tag) from exc

    previous_tag = find_previous_tag(args.tag)
    commits = collect_commits(args.tag, previous_tag)
    notes = render_notes(args.tag, repository_name(), previous_tag, commits)
    args.output.write_text(notes, encoding="utf-8")
    print("Generated " + str(args.output) + " for " + args.tag)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
