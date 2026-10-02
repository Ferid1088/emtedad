"""Static contract tests for the .claude content-production agent system.

These protect architecture (agent surface, owner gate, isolation, referenced
paths), never exact prose.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CLAUDE_DIR = ROOT / ".claude"
AGENTS_DIR = CLAUDE_DIR / "agents"
COMMAND_FILE = CLAUDE_DIR / "commands" / "produce-lesson.md"
SETTINGS_FILE = CLAUDE_DIR / "settings.json"
CLAUDE_MD = ROOT / "CLAUDE.md"

REQUIRED_AGENTS = {
    "producer",
    "source-ingestor",
    "researcher",
    "script-writer",
    "ayin-guardian",
    "fact-checker",
    "continuity-editor",
    "packager",
}


def _agent_files() -> dict[str, Path]:
    return {path.stem: path for path in AGENTS_DIR.glob("*.md")}


def _frontmatter(text: str) -> dict[str, str]:
    match = re.match(r"^---\n(.*?)\n---\n", text, re.DOTALL)
    assert match is not None, "agent file must start with YAML frontmatter"
    fields: dict[str, str] = {}
    for line in match.group(1).splitlines():
        key, _, value = line.partition(":")
        fields[key.strip()] = value.strip()
    return fields


def _command_text() -> str:
    return COMMAND_FILE.read_text(encoding="utf-8")


def _settings() -> dict[str, object]:
    return json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))


def _deny_rules() -> list[str]:
    permissions = _settings().get("permissions", {})
    assert isinstance(permissions, dict)
    deny = permissions.get("deny", [])
    assert isinstance(deny, list)
    return [str(rule) for rule in deny]


class TestAgentSurface:
    def test_all_required_agents_exist(self) -> None:
        assert set(_agent_files()) == REQUIRED_AGENTS

    def test_each_agent_has_name_description_tools(self) -> None:
        for name, path in _agent_files().items():
            fields = _frontmatter(path.read_text(encoding="utf-8"))
            assert fields.get("name") == name
            assert fields.get("description"), name
            assert fields.get("tools"), name

    def test_orchestration_references_pipeline_agents(self) -> None:
        text = _command_text()
        for name in REQUIRED_AGENTS - {"source-ingestor"}:
            assert f"`{name}`" in text, f"{name} not referenced by produce-lesson"


class TestOwnerGate:
    def test_gate_present_and_before_packager(self) -> None:
        text = _command_text()
        gate = text.find("OWNER APPROVAL")
        packager = text.find("### 7. PACKAGER")
        assert gate != -1 and packager != -1
        assert gate < packager

    def test_no_proxy_for_owner_approval(self) -> None:
        text = _command_text()
        assert "explicit owner approval" in text
        denial = text[text.find("OWNER APPROVAL") :]
        for proxy in ("reviewers passing", "blocking findings", "tests"):
            assert proxy in denial

    def test_revision_loop_capped(self) -> None:
        assert re.search(r"[Mm]aximum 3|[Mm]ax 3|3 rounds", _command_text())

    def test_continuity_runs_after_draft(self) -> None:
        text = _command_text()
        writer = text.find("script-writer")
        continuity = text.find("continuity-editor")
        assert writer != -1 and continuity != -1 and writer < continuity


class TestIsolation:
    def test_writer_has_no_shell_access(self) -> None:
        """No Bash ⇒ the writer cannot query the ledger/archive in Postgres."""

        fields = _frontmatter(
            _agent_files()["script-writer"].read_text(encoding="utf-8")
        )
        tools = {tool.strip() for tool in fields["tools"].split(",")}
        assert "Bash" not in tools
        assert "Write" in tools  # must still be able to write the draft file

    def test_writer_forbids_ledger_and_archive_input(self) -> None:
        body = _agent_files()["script-writer"].read_text(encoding="utf-8")
        assert "PROMPT-LEVEL INFORMATION BOUNDARY" in body
        assert "Channel Ledger" in body

    def test_continuity_sends_constraints_not_prose(self) -> None:
        body = _agent_files()["continuity-editor"].read_text(encoding="utf-8")
        assert "constraints" in body
        assert "never" in body and "prose" in body


class TestSettings:
    def test_settings_is_valid_json(self) -> None:
        assert _settings()["permissions"]

    def test_secrets_are_deny_read_and_write(self) -> None:
        rules = _deny_rules()
        assert any(rule.startswith("Read(./.env)") for rule in rules)
        assert any(rule.startswith(("Edit(./.env", "Write(./.env")) for rule in rules)

    def test_no_git_commit_or_push(self) -> None:
        rules = _deny_rules()
        assert any("git commit" in rule for rule in rules)
        assert any("git push" in rule for rule in rules)

    def test_canon_tree_is_write_protected(self) -> None:
        rules = _deny_rules()
        assert any("resources/**" in rule for rule in rules)

    def test_no_publication_tooling(self) -> None:
        text = SETTINGS_FILE.read_text(encoding="utf-8") + _command_text()
        for forbidden in ("yt-dlp", "youtube-dl"):
            assert forbidden in text  # denied or forbidden, never invoked
        assert "publish" not in [
            step.lower() for step in re.findall(r"### \d+\. (\w+)", _command_text())
        ]


class TestReferencedPaths:
    def test_every_repo_path_reference_resolves(self) -> None:
        sources = [CLAUDE_MD, COMMAND_FILE, *_agent_files().values()]
        pattern = re.compile(r"`((?:resources|docs|app)/[^`\s)]+)`")
        checked: set[str] = set()
        for source in sources:
            for match in pattern.findall(source.read_text(encoding="utf-8")):
                candidate = match.rstrip(".,/")
                if "*" in candidate or "<" in candidate:
                    candidate = candidate.split("<")[0].rstrip("/")
                if not candidate or candidate in checked:
                    continue
                checked.add(candidate)
                path = ROOT / candidate
                assert path.exists() or path.parent.exists(), (
                    f"{source.name} references missing path: {match}"
                )

    def test_claude_md_exists_and_points_at_canon(self) -> None:
        text = CLAUDE_MD.read_text(encoding="utf-8")
        assert "resources/editorial/lesson_canon/lessons.json" in text
        assert "docs/architecture/DOMAIN_RULES.md" in text


class TestCliSurface:
    def test_lessons_commands_registered(self) -> None:
        from app.cli import _parser

        parser = _parser()
        for argv in (
            ["lessons", "status"],
            ["lessons", "status", "1.1"],
            ["lessons", "package", "1.1"],
            ["lessons", "project", "1.1", "--target-minutes", "22"],
            [
                "lessons",
                "draft",
                "00000000-0000-0000-0000-000000000000",
                "--file",
                "x.md",
                "--target-minutes",
                "22",
            ],
            ["lessons", "ledger"],
            ["lessons", "ledger", "1.1", "--limit", "5"],
        ):
            args = parser.parse_args(argv)
            assert args.domain == "lessons"
        research = parser.parse_args(
            [
                "lessons",
                "research",
                "00000000-0000-0000-0000-000000000000",
                "--owner-focus",
                "x",
            ]
        )
        assert research.command == "research"

    def test_lessons_package_command_smoke(self) -> None:
        """The file-backed package path resolves a real lesson without a DB."""

        from app.content_strategy.lesson_canon import LessonCanonRepository

        package = LessonCanonRepository().package("1.1")
        assert package.lesson_id == "1.1"
        assert package.canonical_lesson_title
        assert package.canonical_lesson_explanation.strip()
