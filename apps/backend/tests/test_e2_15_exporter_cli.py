from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from scripts import export_personal_transfer as cli


OWNER_ID = "00000000-0000-4000-8000-000000000001"
SECRET = "GH145_SENTINEL_DATABASE_SECRET"
DATABASE_URL = (
    "postgresql+psycopg://nutrition:"
    f"{SECRET}"
    "@127.0.0.1:5432/nutrition"
)


def test_transfer_cli_requires_owner_and_output(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as failure:
        cli.main([])

    captured = capsys.readouterr()

    assert failure.value.code == 2
    assert captured.out == ""
    assert "--owner-id" in captured.err
    assert "--output" in captured.err


def test_transfer_cli_rejects_unknown_argument_before_export(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output = tmp_path / "owner.nutrition-transfer.json"
    calls: list[object] = []

    monkeypatch.setenv(
        "NUTRITION_DATABASE_URL",
        DATABASE_URL,
    )
    monkeypatch.setattr(
        cli,
        "export_personal_transfer",
        lambda *args, **kwargs: calls.append((args, kwargs)),
    )

    with pytest.raises(SystemExit) as failure:
        cli.main(
            [
                "--owner-id",
                OWNER_ID,
                "--output",
                str(output),
                "--unsupported-option",
            ]
        )

    captured = capsys.readouterr()

    assert failure.value.code == 2
    assert captured.out == ""
    assert "unrecognized arguments: --unsupported-option" in captured.err
    assert calls == []
    assert not output.exists()
    assert SECRET not in captured.err
    assert DATABASE_URL not in captured.err


def test_transfer_cli_requires_database_configuration_without_creating_artifact(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output = tmp_path / "owner.nutrition-transfer.json"

    monkeypatch.delenv(
        "NUTRITION_DATABASE_URL",
        raising=False,
    )

    with pytest.raises(SystemExit) as failure:
        cli.main(
            [
                "--owner-id",
                OWNER_ID,
                "--output",
                str(output),
            ]
        )

    captured = capsys.readouterr()

    assert failure.value.code == 2
    assert captured.out == ""
    assert "NUTRITION_DATABASE_URL is required" in captured.err
    assert not output.exists()


def test_transfer_cli_success_wires_arguments_and_emits_contract_summary(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output = tmp_path / "owner.nutrition-transfer.json"
    calls: list[tuple[object, ...]] = []

    def fake_export(
        database_url: str,
        owner_id: str,
        output_path: Path,
        *,
        frozen_writes_acknowledged: bool,
    ) -> SimpleNamespace:
        calls.append(
            (
                database_url,
                owner_id,
                output_path,
                frozen_writes_acknowledged,
            )
        )

        output_path.write_text(
            '{"fixture":"cli-boundary"}\n',
            encoding="utf-8",
        )

        return SimpleNamespace(
            byte_count=27,
            overall_digest="a" * 64,
            section_counts={
                "foods": 1,
                "recipes": 2,
            },
        )

    monkeypatch.setenv(
        "NUTRITION_DATABASE_URL",
        DATABASE_URL,
    )
    monkeypatch.setattr(
        cli,
        "export_personal_transfer",
        fake_export,
    )

    result = cli.main(
        [
            "--owner-id",
            OWNER_ID,
            "--output",
            str(output),
            "--acknowledge-frozen-writes",
        ]
    )

    captured = capsys.readouterr()

    assert result == 0
    assert captured.err == ""

    assert calls == [
        (
            DATABASE_URL,
            OWNER_ID,
            output,
            True,
        )
    ]

    assert output.is_file()

    assert json.loads(captured.out) == {
        "byte_count": 27,
        "format_version": cli.CONTRACT["format_version"],
        "overall_digest": "a" * 64,
        "schema_contract": cli.CONTRACT["source"]["schema_contract"],
        "section_counts": {
            "foods": 1,
            "recipes": 2,
        },
        "status": "complete",
    }

    assert SECRET not in captured.out
    assert DATABASE_URL not in captured.out
    assert SECRET not in captured.err
    assert DATABASE_URL not in captured.err


def test_transfer_cli_export_failure_is_sanitized_and_nonzero(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    output = tmp_path / "owner.nutrition-transfer.json"
    calls: list[tuple[object, ...]] = []

    internal_diagnostic = (
        "internal exporter diagnostic containing "
        f"{SECRET} and {DATABASE_URL}"
    )

    def failing_export(
        database_url: str,
        owner_id: str,
        output_path: Path,
        *,
        frozen_writes_acknowledged: bool,
    ) -> None:
        calls.append(
            (
                database_url,
                owner_id,
                output_path,
                frozen_writes_acknowledged,
            )
        )

        raise cli.TransferExportError(
            "owner_not_found",
            internal_diagnostic,
        )

    monkeypatch.setenv(
        "NUTRITION_DATABASE_URL",
        DATABASE_URL,
    )
    monkeypatch.setattr(
        cli,
        "export_personal_transfer",
        failing_export,
    )

    result = cli.main(
        [
            "--owner-id",
            OWNER_ID,
            "--output",
            str(output),
        ]
    )

    captured = capsys.readouterr()

    assert result == 1
    assert captured.err == ""

    assert calls == [
        (
            DATABASE_URL,
            OWNER_ID,
            output,
            False,
        )
    ]

    assert json.loads(captured.out) == {
        "code": "owner_not_found",
        "status": "failed",
    }

    assert not output.exists()

    assert SECRET not in captured.out
    assert DATABASE_URL not in captured.out
    assert internal_diagnostic not in captured.out

    assert SECRET not in captured.err
    assert DATABASE_URL not in captured.err
    assert internal_diagnostic not in captured.err
