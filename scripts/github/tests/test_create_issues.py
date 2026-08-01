"""Unit tests for the Markdown backlog issue creator."""

from __future__ import annotations

import importlib.util
import io
import json
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest import mock


MODULE_PATH = Path(__file__).resolve().parents[1] / "create_issues.py"
SPEC = importlib.util.spec_from_file_location("create_issues", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
create_issues = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = create_issues
SPEC.loader.exec_module(create_issues)


SECTIONS = """
### Purpose

Purpose text.

### Background

Background text.

### Acceptance criteria

- It works.

### Out of scope

- Nothing else.

### Dependencies

- None.

### Backend work

- None.

### Frontend work

- Implement it.

### API work

- None.

### Migration work

- None.

### Testing requirements

- Test it.

### Estimated implementation size

S
""".strip()


def backlog_text(*issue_ids: str) -> str:
    """Build a minimal valid backlog fixture."""

    issues = "\n\n".join(
        f"## {identifier} — Issue {identifier}\n\n{SECTIONS}" for identifier in issue_ids
    )
    return (
        "# Example Epic\n\n"
        "## Backlog status\n\nApproved.\n\n"
        "# Milestone 1 — Foundation\n\n"
        f"{issues}\n\n"
        "# Recommended implementation order\n\nIgnored appendix.\n"
    )


class ParseBacklogTests(unittest.TestCase):
    def test_parses_epic_milestone_and_children(self) -> None:
        parsed = create_issues.parse_backlog(backlog_text("EX-01", "EX-02"))

        self.assertEqual(parsed.title, "Example Epic")
        self.assertEqual(parsed.milestones, ("Milestone 1 — Foundation",))
        self.assertEqual([item.identifier for item in parsed.issues], ["EX-01", "EX-02"])
        self.assertIn("Approved.", parsed.intro)
        self.assertNotIn("Ignored appendix", parsed.issues[-1].body)

    def test_parses_optional_epic_and_child_labels(self) -> None:
        source = backlog_text("EX-01").replace(
            "## Backlog status", "Labels: planning, API\n\n## Backlog status"
        ).replace(
            "## EX-01 — Issue EX-01\n\n",
            "## EX-01 — Issue EX-01\n\nLabels: backend, api, backend\n\n",
        )

        parsed = create_issues.parse_backlog(source)

        self.assertEqual(parsed.labels, ("planning", "API"))
        self.assertEqual(parsed.issues[0].labels, ("backend", "api"))
        self.assertNotIn("Labels:", parsed.intro)
        self.assertNotIn("Labels:", parsed.issues[0].body)

    def test_rejects_duplicate_identifiers(self) -> None:
        with self.assertRaisesRegex(create_issues.BacklogFormatError, "Duplicate issue"):
            create_issues.parse_backlog(backlog_text("EX-01", "EX-01"))

    def test_rejects_missing_required_section(self) -> None:
        source = backlog_text("EX-01").replace("### API work", "### Interface work")
        with self.assertRaisesRegex(create_issues.BacklogFormatError, "API work"):
            create_issues.parse_backlog(source)

    def test_rejects_empty_required_section(self) -> None:
        source = backlog_text("EX-01").replace(
            "### Migration work\n\n- None.", "### Migration work\n"
        )
        with self.assertRaisesRegex(create_issues.BacklogFormatError, "empty.*Migration work"):
            create_issues.parse_backlog(source)


class RenderingTests(unittest.TestCase):
    def test_checklist_groups_and_links_every_child(self) -> None:
        backlog = create_issues.parse_backlog(backlog_text("EX-01", "EX-02"))
        records = {
            "EX-01": create_issues.RemoteIssue(11, "one", "https://example/issues/11", "", "open"),
            "EX-02": create_issues.RemoteIssue(12, "two", "https://example/issues/12", "", "open"),
        }

        checklist = create_issues.build_checklist(backlog, records)

        self.assertIn("### Milestone 1 — Foundation", checklist)
        self.assertIn("[#11 — EX-01 — Issue EX-01](https://example/issues/11)", checklist)
        self.assertIn("[#12 — EX-02 — Issue EX-02](https://example/issues/12)", checklist)

    def test_checklist_replacement_preserves_human_text(self) -> None:
        old = (
            "Human introduction.\n\n"
            f"{create_issues.MANAGED_CHECKLIST_START}\nold\n"
            f"{create_issues.MANAGED_CHECKLIST_END}\n\nHuman footer.\n"
        )
        new_block = (
            f"{create_issues.MANAGED_CHECKLIST_START}\nnew\n"
            f"{create_issues.MANAGED_CHECKLIST_END}"
        )

        updated = create_issues.replace_managed_checklist(old, new_block)

        self.assertIn("Human introduction.", updated)
        self.assertIn("Human footer.", updated)
        self.assertIn("\nnew\n", updated)
        self.assertNotIn("\nold\n", updated)

    def test_child_marker_is_stable_and_present(self) -> None:
        issue = create_issues.parse_backlog(backlog_text("EX-01")).issues[0]
        body = create_issues.build_child_body(issue, "example-key")

        self.assertIn(create_issues.child_marker("example-key", "EX-01"), body)
        self.assertIn("> Milestone: Milestone 1 — Foundation", body)

    def test_generated_epic_metadata_reports_progress_sources_and_project(self) -> None:
        backlog = create_issues.parse_backlog(backlog_text("EX-01", "EX-02"))
        records = {
            "EX-01": create_issues.RemoteIssue(
                11, "one", "https://example/issues/11", "", "closed"
            ),
            "EX-02": create_issues.RemoteIssue(
                12, "two", "https://example/issues/12", "", "open"
            ),
        }
        milestone = create_issues.MilestoneRecord(
            1,
            "Milestone 1 — Foundation",
            "https://example/milestone/1",
            "open",
        )
        project = create_issues.ProjectRecord(
            2, "PVT_project", "Delivery", "https://example/projects/2"
        )

        generated = create_issues.build_generated_epic_section(
            backlog,
            records,
            {milestone.title: milestone},
            (create_issues.PlanningDocument("Feature PRD", "https://example/prd"),),
            project,
        )

        self.assertIn("### Purpose", generated)
        self.assertIn("1 of 2 issues complete (50%)", generated)
        self.assertIn("[Feature PRD](https://example/prd)", generated)
        self.assertIn("[Delivery](https://example/projects/2)", generated)
        self.assertIn("- [x] [#11", generated)
        self.assertIn("- [ ] [#12", generated)


class StateTests(unittest.TestCase):
    def test_state_write_is_valid_and_reloadable(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "nested" / "state.json"
            source = Path(directory) / "backlog.md"
            state = create_issues.empty_state("example-key", "owner/repo", source)
            create_issues.write_state(path, state)

            loaded = create_issues.load_state(
                path,
                backlog_key="example-key",
                repository="owner/repo",
                source=source,
            )

            self.assertEqual(loaded, json.loads(path.read_text(encoding="utf-8")))
            self.assertEqual(loaded["repository"], "owner/repo")

    def test_remote_marker_recovers_issue_without_state(self) -> None:
        backlog = create_issues.parse_backlog(backlog_text("EX-01"))
        key = "example-key"
        epic = create_issues.RemoteIssue(
            10,
            backlog.title,
            "https://example/issues/10",
            create_issues.epic_marker(key),
            "open",
        )
        child = create_issues.RemoteIssue(
            11,
            backlog.issues[0].github_title,
            "https://example/issues/11",
            create_issues.child_marker(key, "EX-01"),
            "open",
        )

        indexed, _ = create_issues.index_owned_issues([epic, child], backlog, key)

        self.assertEqual(indexed["epic"].number, 10)
        self.assertEqual(indexed["EX-01"].number, 11)

    def test_rerun_resolves_state_to_the_same_issue(self) -> None:
        record = create_issues.RemoteIssue(
            11,
            "EX-01 — Existing",
            "https://example/issues/11",
            create_issues.child_marker("example-key", "EX-01"),
            "open",
        )
        arguments = {
            "label": "EX-01",
            "marker": create_issues.child_marker("example-key", "EX-01"),
            "state_entry": {"number": 11},
            "by_number": {11: record},
            "by_marker": {"EX-01": record},
        }

        first = create_issues.resolve_existing(**arguments)
        second = create_issues.resolve_existing(**arguments)

        self.assertIs(first, record)
        self.assertIs(second, record)

    def test_duplicate_remote_marker_fails_closed(self) -> None:
        backlog = create_issues.parse_backlog(backlog_text("EX-01"))
        marker = create_issues.child_marker("example-key", "EX-01")
        duplicates = [
            create_issues.RemoteIssue(11, "one", "https://example/issues/11", marker, "open"),
            create_issues.RemoteIssue(12, "two", "https://example/issues/12", marker, "open"),
        ]

        with self.assertRaisesRegex(create_issues.StateFileError, "Duplicate"):
            create_issues.index_owned_issues(duplicates, backlog, "example-key")

    def test_dry_run_does_not_write_state(self) -> None:
        backlog_source = backlog_text("EX-01")
        backlog = create_issues.parse_backlog(backlog_source)
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "backlog.md"
            state = Path(directory) / "state.json"
            source.write_text(backlog_source, encoding="utf-8")

            result = create_issues.execute(
                source=source,
                backlog=backlog,
                source_text=backlog_source,
                repository="owner/repo",
                state_path=state,
                backlog_key="example-key",
                dry_run=True,
            )

            self.assertEqual(result, 0)
            self.assertFalse(state.exists())


class LabelAndMilestoneTests(unittest.TestCase):
    def test_creates_only_missing_labels_and_reuses_case_insensitively(self) -> None:
        class FakeGitHub:
            def __init__(self) -> None:
                self.labels = ["API"]
                self.created: list[str] = []

            def list_labels(self, _repository: str):
                return tuple(self.labels)

            def create_label(self, _repository: str, name: str) -> None:
                self.created.append(name)
                self.labels.append(name)

        gh = FakeGitHub()

        resolved = create_issues.ensure_labels(gh, "owner/repo", ("api", "backend"))
        rerun = create_issues.ensure_labels(gh, "owner/repo", ("api", "backend"))

        self.assertEqual(gh.created, ["backend"])
        self.assertEqual(resolved, {"api": "API", "backend": "backend"})
        self.assertEqual(rerun, resolved)

    def test_creates_only_missing_milestones_and_reuses_on_rerun(self) -> None:
        class FakeGitHub:
            def __init__(self) -> None:
                self.milestones = [
                    create_issues.MilestoneRecord(
                        1, "Milestone 1 — Foundation", "https://example/m/1", "open"
                    )
                ]
                self.created: list[str] = []

            def list_milestones(self, _repository: str):
                return tuple(self.milestones)

            def create_milestone(self, _repository: str, title: str):
                self.created.append(title)
                value = create_issues.MilestoneRecord(
                    2, title, "https://example/m/2", "open"
                )
                self.milestones.append(value)
                return value

        gh = FakeGitHub()
        titles = ("Milestone 1 — Foundation", "Milestone 2 — Delivery")

        first = create_issues.ensure_milestones(gh, "owner/repo", titles)
        second = create_issues.ensure_milestones(gh, "owner/repo", titles)

        self.assertEqual(gh.created, ["Milestone 2 — Delivery"])
        self.assertEqual(first, second)

    def test_issue_creation_applies_labels_and_milestone(self) -> None:
        cli = object.__new__(create_issues.GitHubCli)
        observed = {}

        def fake_run(arguments, *, input_text=None):
            observed["arguments"] = arguments
            observed["body"] = input_text
            return "https://github.com/owner/repo/issues/42"

        cli.run = fake_run

        record = cli.create_issue(
            "owner/repo",
            "EX-01 — Test",
            "Body",
            labels=("backend", "api"),
            milestone="Milestone 1 — Foundation",
        )

        self.assertEqual(record.number, 42)
        self.assertEqual(record.labels, ("backend", "api"))
        self.assertEqual(record.milestone, "Milestone 1 — Foundation")
        self.assertIn("--label", observed["arguments"])
        self.assertIn("backend", observed["arguments"])
        self.assertIn("--milestone", observed["arguments"])
        self.assertEqual(observed["body"], "Body")


class ProjectTests(unittest.TestCase):
    def test_creates_project_once_and_reuses_it_on_rerun(self) -> None:
        class FakeGitHub:
            def __init__(self) -> None:
                self.projects = []
                self.create_count = 0

            def list_projects(self, _owner: str):
                return tuple(self.projects)

            def create_project(self, _owner: str, title: str):
                self.create_count += 1
                project = create_issues.ProjectRecord(
                    7, "PVT_7", title, "https://example/projects/7"
                )
                self.projects.append(project)
                return project

        gh = FakeGitHub()

        first, first_created = create_issues.ensure_project(gh, "owner", "Delivery")
        second, second_created = create_issues.ensure_project(gh, "owner", "Delivery")

        self.assertTrue(first_created)
        self.assertFalse(second_created)
        self.assertEqual(first, second)
        self.assertEqual(gh.create_count, 1)

    def test_duplicate_project_titles_fail_closed(self) -> None:
        class FakeGitHub:
            def list_projects(self, _owner: str):
                return (
                    create_issues.ProjectRecord(
                        7, "PVT_7", "Delivery", "https://example/projects/7"
                    ),
                    create_issues.ProjectRecord(
                        8, "PVT_8", "delivery", "https://example/projects/8"
                    ),
                )

        with self.assertRaisesRegex(create_issues.StateFileError, "Multiple"):
            create_issues.ensure_project(FakeGitHub(), "owner", "Delivery")

    def test_existing_project_workflow_customization_is_preserved(self) -> None:
        class FakeGitHub:
            def __init__(self) -> None:
                self.set_count = 0

            def list_project_fields(self, _owner: str, _project):
                return (
                    create_issues.ProjectField(
                        "field",
                        "Status",
                        "ProjectV2SingleSelectField",
                        (
                            create_issues.ProjectOption("custom", "Needs design"),
                            create_issues.ProjectOption("done", "Done"),
                        ),
                    ),
                )

            def set_project_workflow(self, _field_id: str) -> None:
                self.set_count += 1

        gh = FakeGitHub()
        project = create_issues.ProjectRecord(
            7, "PVT_7", "Delivery", "https://example/projects/7"
        )

        _, backlog_option, _ = create_issues.initialize_project_workflow(
            gh, "owner", project, may_modify=False
        )

        self.assertIsNone(backlog_option)
        self.assertEqual(gh.set_count, 0)

    def test_new_project_receives_default_five_state_workflow(self) -> None:
        class FakeGitHub:
            def __init__(self) -> None:
                self.initialized = False

            def list_project_fields(self, _owner: str, _project):
                names = (
                    create_issues.DEFAULT_PROJECT_WORKFLOW
                    if self.initialized
                    else ("Todo", "In Progress", "Done")
                )
                return (
                    create_issues.ProjectField(
                        "status-field",
                        "Status",
                        "ProjectV2SingleSelectField",
                        tuple(
                            create_issues.ProjectOption(f"option-{index}", name)
                            for index, name in enumerate(names)
                        ),
                    ),
                )

            def set_project_workflow(self, field_id: str) -> None:
                self.asserted_field_id = field_id
                self.initialized = True

        gh = FakeGitHub()
        project = create_issues.ProjectRecord(
            7, "PVT_7", "Delivery", "https://example/projects/7"
        )

        field, backlog_option, initialized = create_issues.initialize_project_workflow(
            gh, "owner", project, may_modify=True
        )

        self.assertTrue(initialized)
        self.assertTrue(gh.initialized)
        self.assertEqual(field.field_id, "status-field")
        self.assertEqual(backlog_option.name, "Backlog")

    def test_project_item_addition_is_idempotent(self) -> None:
        class FakeGitHub:
            def __init__(self) -> None:
                self.items = []
                self.added: list[str] = []

            def list_project_items(self, _owner: str, _project):
                return tuple(self.items)

            def add_project_item(self, _owner: str, _project, issue_url: str):
                self.added.append(issue_url)
                item = create_issues.ProjectItem(f"item-{len(self.items)}", issue_url)
                self.items.append(item)
                return item

            def set_project_item_status(self, *_args) -> None:
                pass

        gh = FakeGitHub()
        project = create_issues.ProjectRecord(
            7, "PVT_7", "Delivery", "https://example/projects/7"
        )
        issue = create_issues.RemoteIssue(
            11, "Issue", "https://example/issues/11", "", "open"
        )

        create_issues.ensure_project_items(gh, "owner", project, (issue,), None, None)
        create_issues.ensure_project_items(gh, "owner", project, (issue,), None, None)

        self.assertEqual(gh.added, [issue.url])


class WorkflowExecutionTests(unittest.TestCase):
    def test_complete_workflow_rerun_reuses_all_remote_artifacts(self) -> None:
        class FakeGitHub:
            def __init__(self) -> None:
                self.labels = []
                self.milestones = []
                self.projects = []
                self.issues = []
                self.items = []
                self.workflow_initialized = False
                self.issue_create_count = 0
                self.project_create_count = 0

            def repository_details(self, repository: str):
                return create_issues.RepositoryDetails(
                    repository, "https://github.com/owner/repo", "main"
                )

            def list_labels(self, _repository: str):
                return tuple(self.labels)

            def create_label(self, _repository: str, name: str) -> None:
                self.labels.append(name)

            def list_milestones(self, _repository: str):
                return tuple(self.milestones)

            def create_milestone(self, _repository: str, title: str):
                milestone = create_issues.MilestoneRecord(
                    1, title, "https://github.com/owner/repo/milestone/1", "open"
                )
                self.milestones.append(milestone)
                return milestone

            def list_projects(self, _owner: str):
                return tuple(self.projects)

            def create_project(self, _owner: str, title: str):
                self.project_create_count += 1
                project = create_issues.ProjectRecord(
                    1,
                    "PVT_project",
                    title,
                    "https://github.com/users/owner/projects/1",
                )
                self.projects.append(project)
                return project

            def list_project_fields(self, _owner: str, _project):
                names = (
                    create_issues.DEFAULT_PROJECT_WORKFLOW
                    if self.workflow_initialized
                    else ("Todo", "In Progress", "Done")
                )
                return (
                    create_issues.ProjectField(
                        "status",
                        "Status",
                        "ProjectV2SingleSelectField",
                        tuple(
                            create_issues.ProjectOption(f"option-{index}", name)
                            for index, name in enumerate(names)
                        ),
                    ),
                )

            def set_project_workflow(self, _field_id: str) -> None:
                self.workflow_initialized = True

            def list_issues(self, _repository: str):
                return tuple(self.issues)

            def create_issue(
                self,
                _repository: str,
                title: str,
                body: str,
                *,
                labels=(),
                milestone=None,
            ):
                self.issue_create_count += 1
                number = self.issue_create_count
                record = create_issues.RemoteIssue(
                    number,
                    title,
                    f"https://github.com/owner/repo/issues/{number}",
                    body,
                    "open",
                    tuple(labels),
                    milestone,
                )
                self.issues.append(record)
                return record

            def update_issue_metadata(
                self, _repository: str, number: int, *, labels, milestone
            ) -> None:
                for index, issue in enumerate(self.issues):
                    if issue.number == number:
                        self.issues[index] = create_issues.replace(
                            issue,
                            labels=(*issue.labels, *labels),
                            milestone=milestone or issue.milestone,
                        )

            def read_issue(self, _repository: str, number: int):
                return next(issue for issue in self.issues if issue.number == number)

            def update_issue_body(self, _repository: str, number: int, body: str) -> None:
                for index, issue in enumerate(self.issues):
                    if issue.number == number:
                        self.issues[index] = create_issues.replace(issue, body=body)

            def list_project_items(self, _owner: str, _project):
                return tuple(self.items)

            def add_project_item(self, _owner: str, _project, issue_url: str):
                item = create_issues.ProjectItem(f"item-{len(self.items)}", issue_url)
                self.items.append(item)
                return item

            def set_project_item_status(self, *_args) -> None:
                pass

        source_text = backlog_text("EX-01").replace(
            "## Backlog status", "Labels: planning\n\n## Backlog status"
        ).replace(
            "## EX-01 — Issue EX-01\n\n",
            "## EX-01 — Issue EX-01\n\nLabels: backend\n\n",
        )
        backlog = create_issues.parse_backlog(source_text)
        gh = FakeGitHub()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "backlog.md"
            state = root / "state.json"
            source.write_text(source_text, encoding="utf-8")
            patches = (
                mock.patch.object(create_issues, "GitHubCli", return_value=gh),
                mock.patch.object(create_issues, "repository_root", return_value=root),
                mock.patch.object(
                    create_issues,
                    "discover_planning_documents",
                    return_value=(
                        create_issues.PlanningDocument(
                            "Implementation Backlog",
                            "https://github.com/owner/repo/blob/main/backlog.md",
                        ),
                    ),
                ),
            )
            with patches[0], patches[1], patches[2], redirect_stdout(io.StringIO()):
                first = create_issues.execute(
                    source=source,
                    backlog=backlog,
                    source_text=source_text,
                    repository="owner/repo",
                    state_path=state,
                    backlog_key="example-key",
                    dry_run=False,
                    project_title="Delivery",
                )
                second = create_issues.execute(
                    source=source,
                    backlog=backlog,
                    source_text=source_text,
                    repository="owner/repo",
                    state_path=state,
                    backlog_key="example-key",
                    dry_run=False,
                    project_title=None,
                )

        self.assertEqual(first, 0)
        self.assertEqual(second, 0)
        self.assertEqual(gh.issue_create_count, 2)
        self.assertEqual(gh.project_create_count, 1)
        self.assertEqual(set(gh.labels), {"planning", "backend"})
        self.assertEqual(len(gh.milestones), 1)
        self.assertEqual(len(gh.items), 2)
        child = next(issue for issue in gh.issues if issue.number == 2)
        self.assertEqual(child.labels, ("backend",))
        self.assertEqual(child.milestone, "Milestone 1 — Foundation")


if __name__ == "__main__":
    unittest.main()
