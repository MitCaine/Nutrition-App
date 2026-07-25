from __future__ import annotations

import pytest

from app.operators import phase5c_contracts as canonical
from app.operators import phase5c4_roles as roles
from scripts import manage_phase5c4_roles as cli


def test_manifest_command_accepts_only_explicit_policy_revisions() -> None:
    parsed = cli.parse_args(
        ["manifest", "--revision", roles.PROMOTION_PREREQUISITES_REVISION]
    )
    assert parsed.command == "manifest"
    assert parsed.revision == roles.PROMOTION_PREREQUISITES_REVISION

    with pytest.raises(SystemExit):
        cli.parse_args(["manifest", "--revision", "9999_unrelated"])


def test_qualify_command_binds_an_optional_exact_policy_revision() -> None:
    parsed = cli.parse_args(
        [
            "qualify",
            "--expected-state",
            "maintenance",
            "--policy-revision",
            roles.PROMOTION_PREREQUISITES_REVISION,
        ]
    )
    assert parsed.expected_state == "maintenance"
    assert parsed.policy_revision == roles.PROMOTION_PREREQUISITES_REVISION


def test_legacy_0018_refresh_requires_database_confirmation() -> None:
    parsed = cli.parse_args(
        [
            "refresh-legacy-0018-policy",
            "--confirm-database",
            "nutrition_app",
        ]
    )
    assert parsed.command == "refresh-legacy-0018-policy"
    assert parsed.confirm_database == "nutrition_app"

    with pytest.raises(SystemExit):
        cli.parse_args(["refresh-legacy-0018-policy"])


def test_manifest_main_emits_the_canonical_revisioned_contract(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        "sys.argv",
        [
            "manage_phase5c4_roles.py",
            "manifest",
            "--revision",
            roles.IMMUTABLE_PROVENANCE_REVISION,
        ],
    )

    cli.main()

    output = capsys.readouterr().out.strip()
    expected = roles.build_revision_privilege_manifest(
        roles.IMMUTABLE_PROVENANCE_REVISION
    )
    assert output == canonical.canonical_json(expected)
