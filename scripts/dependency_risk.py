from __future__ import annotations

import argparse
import copy
import json
import os
import re
import subprocess
import sys
import urllib.request
from pathlib import Path
from typing import Any


DEFAULT_ROOT = Path(__file__).resolve().parents[1]
REGISTER_RELATIVE = Path(
    "engineering/security/dependency-risk-register.json"
)
MOBILE_RELATIVE = Path("apps/mobile")

TRACKED_ALERTS = {
    2: (
        "uuid",
        "GHSA-w5hq-g745-h8pq",
        "medium",
    ),
    16: (
        "image-size",
        "GHSA-5p2g-fcmc-qvqq",
        "high",
    ),
    17: (
        "image-size",
        "GHSA-w3rx-r6r6-pgpr",
        "high",
    ),
}


class DependencyRiskError(RuntimeError):
    pass


def require(
    condition: bool,
    message: str,
) -> None:
    if not condition:
        raise DependencyRiskError(message)


def read_json(path: Path) -> Any:
    return json.loads(
        path.read_text(encoding="utf-8")
    )


def write_json(
    path: Path,
    value: Any,
) -> None:
    path.write_text(
        json.dumps(
            value,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )


def dependency_map(
    package_node: dict[str, Any],
) -> dict[str, str]:
    result: dict[str, str] = {}

    for key in (
        "dependencies",
        "devDependencies",
        "optionalDependencies",
    ):
        values = package_node.get(key)

        if isinstance(values, dict):
            for name, requested in values.items():
                if isinstance(requested, str):
                    result[name] = requested

    return result


def validate_register_schema(
    register: dict[str, Any],
) -> None:
    require(
        register.get("schema_version") == 1,
        "schema_version must be 1",
    )

    require(
        register.get("source_issue") == 166,
        "source_issue must be 166",
    )

    reviewed_at = register.get(
        "reviewed_at"
    )

    reviewed_commit = register.get(
        "reviewed_commit"
    )

    require(
        isinstance(reviewed_at, str)
        and re.fullmatch(
            r"\d{4}-\d{2}-\d{2}",
            reviewed_at,
        )
        is not None,
        "reviewed_at must be YYYY-MM-DD",
    )

    require(
        isinstance(reviewed_commit, str)
        and re.fullmatch(
            r"[0-9a-f]{40}",
            reviewed_commit,
        )
        is not None,
        "reviewed_commit must be a full SHA",
    )

    policy = register.get("policy")

    require(
        isinstance(policy, dict),
        "policy missing",
    )

    for key in (
        "alerts_are_not_dismissed_for_dashboard_cleanliness",
        "unsupported_transitive_forcing_is_prohibited",
        "network_monitoring_is_separate_from_offline_validation",
    ):
        require(
            policy.get(key) is True,
            f"policy contract missing: {key}",
        )

    records = register.get("records")

    require(
        isinstance(records, list)
        and len(records) == 3,
        (
            "register must contain "
            "exactly three records"
        ),
    )

    seen_alerts: set[int] = set()
    seen_ids: set[str] = set()

    for record in records:
        require(
            isinstance(record, dict),
            "record must be an object",
        )

        alert_number = record.get(
            "alert_number"
        )

        risk_id = record.get("risk_id")

        require(
            alert_number in TRACKED_ALERTS,
            f"unexpected alert: {alert_number}",
        )

        require(
            alert_number not in seen_alerts,
            f"duplicate alert: {alert_number}",
        )

        require(
            isinstance(risk_id, str)
            and bool(risk_id),
            "risk_id missing",
        )

        require(
            risk_id not in seen_ids,
            f"duplicate risk_id: {risk_id}",
        )

        seen_alerts.add(alert_number)
        seen_ids.add(risk_id)

        (
            package,
            advisory_id,
            severity,
        ) = TRACKED_ALERTS[alert_number]

        require(
            record.get("package")
            == package,
            (
                f"alert {alert_number} "
                "package drift"
            ),
        )

        require(
            record.get("advisory_id")
            == advisory_id,
            (
                f"alert {alert_number} "
                "advisory drift"
            ),
        )

        require(
            record.get("severity")
            == severity,
            (
                f"alert {alert_number} "
                "severity drift"
            ),
        )

        for key in (
            "manifest_path",
            "installed_version",
            "vulnerable_version_range",
            "classification",
            "vulnerable_precondition",
            "disposition",
            "reviewed_at",
            "reviewed_commit",
            "owner",
        ):
            require(
                isinstance(
                    record.get(key),
                    str,
                )
                and bool(
                    record.get(key)
                ),
                (
                    f"alert {alert_number} "
                    f"missing {key}"
                ),
            )

        require(
            record.get("source_issue")
            == 166,
            (
                f"alert {alert_number} "
                "source issue drift"
            ),
        )

        path = record.get(
            "dependency_path"
        )

        require(
            isinstance(path, list)
            and len(path) >= 3,
            (
                f"alert {alert_number} "
                "dependency_path invalid"
            ),
        )

        for index, node in enumerate(
            path
        ):
            require(
                isinstance(node, dict),
                (
                    f"alert {alert_number} "
                    "path node invalid"
                ),
            )

            for key in (
                "name",
                "version",
                "location",
            ):
                require(
                    isinstance(
                        node.get(key),
                        str,
                    ),
                    (
                        f"alert {alert_number} "
                        f"path node {key} invalid"
                    ),
                )

            requested = node.get(
                "requested"
            )

            if index == 0:
                require(
                    requested is None,
                    (
                        f"alert {alert_number} "
                        "root requested must be null"
                    ),
                )
            else:
                require(
                    isinstance(
                        requested,
                        str,
                    )
                    and bool(requested),
                    (
                        f"alert {alert_number} "
                        "dependency request missing"
                    ),
                )

        terminal = path[-1]

        require(
            terminal["name"]
            == record["package"],
            (
                f"alert {alert_number} "
                "terminal package drift"
            ),
        )

        require(
            terminal["version"]
            == record["installed_version"],
            (
                f"alert {alert_number} "
                "terminal version drift"
            ),
        )

        reachability = record.get(
            "repository_reachability"
        )

        require(
            isinstance(
                reachability,
                dict,
            )
            and isinstance(
                reachability.get(
                    "conclusion"
                ),
                str,
            )
            and bool(
                reachability.get(
                    "conclusion"
                )
            )
            and isinstance(
                reachability.get(
                    "evidence"
                ),
                list,
            )
            and bool(
                reachability.get(
                    "evidence"
                )
            ),
            (
                f"alert {alert_number} "
                "reachability evidence missing"
            ),
        )

        remediation = record.get(
            "remediation"
        )

        require(
            isinstance(
                remediation,
                dict,
            )
            and isinstance(
                remediation.get(
                    "supported_fix_available"
                ),
                bool,
            )
            and isinstance(
                remediation.get(
                    "reason"
                ),
                str,
            )
            and bool(
                remediation.get(
                    "reason"
                )
            ),
            (
                f"alert {alert_number} "
                "remediation state missing"
            ),
        )

        triggers = record.get(
            "reevaluation_triggers"
        )

        require(
            isinstance(triggers, list)
            and bool(triggers)
            and all(
                isinstance(item, str)
                and bool(item)
                for item in triggers
            ),
            (
                f"alert {alert_number} "
                "reevaluation triggers missing"
            ),
        )

    require(
        seen_alerts
        == set(TRACKED_ALERTS),
        "tracked alert set incomplete",
    )

    baseline = register.get(
        "monitor_baseline"
    )

    require(
        isinstance(baseline, dict)
        and isinstance(
            baseline.get(
                "remote_snapshot"
            ),
            dict,
        ),
        "monitor baseline missing",
    )


def validate_lock_path(
    record: dict[str, Any],
    lock_document: dict[str, Any],
) -> None:
    packages = lock_document.get(
        "packages"
    )

    require(
        isinstance(packages, dict),
        "package-lock packages map missing",
    )

    path = record["dependency_path"]

    for index, node in enumerate(
        path
    ):
        location = node["location"]

        package_node = packages.get(
            location
        )

        require(
            isinstance(
                package_node,
                dict,
            ),
            (
                f"alert {record['alert_number']} "
                "package disappeared: "
                f"{location or '<root>'}"
            ),
        )

        require(
            package_node.get("version")
            == node["version"],
            (
                f"alert {record['alert_number']} "
                "version drift: "
                f"{location or '<root>'}"
            ),
        )

        if index == 0:
            require(
                package_node.get("name")
                == node["name"],
                (
                    f"alert {record['alert_number']} "
                    "root package name drift"
                ),
            )

            continue

        parent_node = packages.get(
            path[index - 1][
                "location"
            ]
        )

        require(
            isinstance(
                parent_node,
                dict,
            ),
            (
                f"alert {record['alert_number']} "
                "parent package disappeared"
            ),
        )

        observed_request = (
            dependency_map(
                parent_node
            ).get(
                node["name"]
            )
        )

        require(
            observed_request
            == node["requested"],
            (
                f"alert {record['alert_number']} "
                "dependency edge drift: "
                f"{path[index - 1]['name']} "
                f"-> {node['name']}; "
                f"expected={node['requested']} "
                f"observed={observed_request}"
            ),
        )


def relevant_application_files(
    mobile_root: Path,
) -> list[Path]:
    suffixes = {
        ".c",
        ".cc",
        ".cpp",
        ".h",
        ".hpp",
        ".js",
        ".jsx",
        ".m",
        ".mm",
        ".swift",
        ".ts",
        ".tsx",
    }

    result: list[Path] = []

    for source_root in (
        mobile_root / "src",
        mobile_root / "modules",
    ):
        if not source_root.exists():
            continue

        result.extend(
            path
            for path in source_root.rglob(
                "*"
            )
            if path.is_file()
            and path.suffix.lower()
            in suffixes
        )

    return sorted(result)


def validate_reachability_boundary(
    repo_root: Path,
) -> None:
    mobile_root = (
        repo_root / MOBILE_RELATIVE
    )

    direct_refs: list[str] = []

    for path in relevant_application_files(
        mobile_root
    ):
        try:
            text = path.read_text(
                encoding="utf-8"
            )
        except UnicodeDecodeError:
            continue

        if "image-size" in text:
            direct_refs.append(
                str(
                    path.relative_to(
                        repo_root
                    )
                )
            )

    require(
        not direct_refs,
        (
            "application/runtime source "
            "now references image-size: "
            + ", ".join(direct_refs)
        ),
    )

    ocr_path = (
        mobile_root
        / "modules"
        / "nutrition-ocr"
        / "ios"
        / "NutritionOcrModule.swift"
    )

    require(
        ocr_path.is_file(),
        "NutritionOcrModule.swift missing",
    )

    ocr_text = ocr_path.read_text(
        encoding="utf-8"
    )

    for token in (
        "CGImageSourceCreate",
        "VNImageRequestHandler",
    ):
        require(
            token in ocr_text,
            (
                "native OCR boundary drift: "
                f"missing {token}"
            ),
        )


def validate_workflow_binding(
    repo_root: Path,
) -> None:
    workflow = (
        repo_root
        / ".github"
        / "workflows"
        / "dependency-risk-monitor.yml"
    )

    require(
        workflow.is_file(),
        (
            "dependency risk monitor "
            "workflow missing"
        ),
    )

    text = workflow.read_text(
        encoding="utf-8"
    )

    for token in (
        "schedule:",
        "validate-offline",
        "validate-installed",
        "monitor",
        "dependency-risk-monitor.json",
    ):
        require(
            token in text,
            (
                "dependency risk monitor "
                f"workflow missing {token}"
            ),
        )


def validate_offline(
    repo_root: Path,
) -> dict[str, Any]:
    register_path = (
        repo_root / REGISTER_RELATIVE
    )

    require(
        register_path.is_file(),
        "dependency risk register missing",
    )

    register = read_json(
        register_path
    )

    require(
        isinstance(register, dict),
        (
            "dependency risk register "
            "root invalid"
        ),
    )

    validate_register_schema(
        register
    )

    lock_document = read_json(
        repo_root
        / MOBILE_RELATIVE
        / "package-lock.json"
    )

    require(
        isinstance(
            lock_document,
            dict,
        ),
        "package-lock root invalid",
    )

    for record in register[
        "records"
    ]:
        validate_lock_path(
            record,
            lock_document,
        )

    validate_reachability_boundary(
        repo_root
    )

    validate_workflow_binding(
        repo_root
    )

    return {
        "status": "pass",
        "mode": "offline",
        "records": len(
            register["records"]
        ),
        "reviewed_commit": (
            register[
                "reviewed_commit"
            ]
        ),
    }


def npm_json(
    mobile_root: Path,
    arguments: list[str],
) -> Any:
    process = subprocess.run(
        ["npm", *arguments],
        cwd=mobile_root,
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    require(
        process.returncode == 0,
        (
            "npm command failed: "
            + " ".join(
                ["npm", *arguments]
            )
            + "\n"
            + process.stderr
        ),
    )

    try:
        return json.loads(
            process.stdout
        )
    except json.JSONDecodeError as error:
        raise DependencyRiskError(
            (
                "npm command returned "
                "invalid JSON: "
                + " ".join(
                    ["npm", *arguments]
                )
            )
        ) from error


def npm_paths(
    mobile_root: Path,
    target: str,
) -> list[list[str]]:
    document = npm_json(
        mobile_root,
        [
            "ls",
            target,
            "--all",
            "--json",
        ],
    )

    require(
        isinstance(document, dict),
        f"npm ls {target} root invalid",
    )

    root_name = document.get("name")
    root_version = document.get(
        "version"
    )

    require(
        isinstance(root_name, str)
        and isinstance(
            root_version,
            str,
        ),
        (
            f"npm ls {target} "
            "root identity invalid"
        ),
    )

    found: set[
        tuple[str, ...]
    ] = set()

    def walk(
        node: dict[str, Any],
        trail: tuple[str, ...],
    ) -> None:
        dependencies = (
            node.get("dependencies")
            or {}
        )

        if not isinstance(
            dependencies,
            dict,
        ):
            return

        for name, child in sorted(
            dependencies.items()
        ):
            if not isinstance(
                child,
                dict,
            ):
                continue

            version = child.get(
                "version"
            )

            if not isinstance(
                version,
                str,
            ):
                continue

            next_trail = (
                *trail,
                f"{name}@{version}",
            )

            if name == target:
                found.add(
                    next_trail
                )

            walk(
                child,
                next_trail,
            )

    walk(
        document,
        (
            f"{root_name}@{root_version}",
        ),
    )

    require(
        bool(found),
        (
            f"npm ls found no path "
            f"for {target}"
        ),
    )

    return [
        list(item)
        for item in sorted(found)
    ]


def registered_label_path(
    record: dict[str, Any],
) -> list[str]:
    return [
        (
            f"{node['name']}"
            f"@{node['version']}"
        )
        for node in record[
            "dependency_path"
        ]
    ]


def collect_identities(
    value: Any,
) -> set[
    tuple[str, str, str]
]:
    result: set[
        tuple[str, str, str]
    ] = set()

    def walk(item: Any) -> None:
        if isinstance(item, dict):
            name = item.get("name")
            version = item.get(
                "version"
            )
            location = item.get(
                "location"
            )

            if (
                isinstance(name, str)
                and isinstance(
                    version,
                    str,
                )
                and isinstance(
                    location,
                    str,
                )
            ):
                result.add(
                    (
                        name,
                        version,
                        location,
                    )
                )

            for child in item.values():
                walk(child)

        elif isinstance(item, list):
            for child in item:
                walk(child)

    walk(value)

    return result


def read_text_tree(
    root: Path,
) -> str:
    chunks: list[str] = []

    for path in sorted(
        item
        for item in root.rglob("*")
        if item.is_file()
    ):
        try:
            chunks.append(
                path.read_text(
                    encoding="utf-8"
                )
            )
        except (
            UnicodeDecodeError,
            OSError,
        ):
            continue

    return "\n".join(chunks)


def validate_installed(
    repo_root: Path,
) -> dict[str, Any]:
    offline = validate_offline(
        repo_root
    )

    register = read_json(
        repo_root / REGISTER_RELATIVE
    )

    mobile_root = (
        repo_root / MOBILE_RELATIVE
    )

    require(
        (
            mobile_root
            / "node_modules"
        ).is_dir(),
        (
            "validate-installed requires "
            "apps/mobile/node_modules"
        ),
    )

    records_by_package: dict[
        str,
        list[dict[str, Any]],
    ] = {}

    for record in register[
        "records"
    ]:
        records_by_package.setdefault(
            record["package"],
            [],
        ).append(record)

    observed_paths: dict[
        str,
        list[list[str]],
    ] = {}

    for package in (
        "image-size",
        "uuid",
    ):
        records = records_by_package[
            package
        ]

        expected_path = (
            registered_label_path(
                records[0]
            )
        )

        for record in records[1:]:
            require(
                registered_label_path(
                    record
                )
                == expected_path,
                (
                    f"{package} risk records "
                    "disagree on dependency path"
                ),
            )

        observed = npm_paths(
            mobile_root,
            package,
        )

        require(
            observed == [
                expected_path
            ],
            (
                f"{package} npm "
                "dependency path drift\n"
                f"expected={[expected_path]}\n"
                f"observed={observed}"
            ),
        )

        observed_paths[
            package
        ] = observed

    image_explain = npm_json(
        mobile_root,
        [
            "explain",
            "image-size",
            "--json",
        ],
    )

    uuid_explain = npm_json(
        mobile_root,
        [
            "explain",
            "uuid",
            "--json",
        ],
    )

    image_identities = (
        collect_identities(
            image_explain
        )
    )

    uuid_identities = (
        collect_identities(
            uuid_explain
        )
    )

    require(
        (
            "image-size",
            "1.2.1",
            "node_modules/image-size",
        )
        in image_identities,
        (
            "npm explain image-size "
            "target drift"
        ),
    )

    require(
        (
            "metro",
            "0.84.4",
            "node_modules/metro",
        )
        in image_identities,
        (
            "npm explain image-size "
            "owner drift"
        ),
    )

    require(
        (
            "uuid",
            "7.0.3",
            "node_modules/uuid",
        )
        in uuid_identities,
        "npm explain uuid target drift",
    )

    require(
        (
            "xcode",
            "3.0.1",
            "node_modules/xcode",
        )
        in uuid_identities,
        "npm explain uuid owner drift",
    )

    metro_assets = (
        mobile_root
        / "node_modules"
        / "metro"
        / "src"
        / "Assets.js"
    )

    require(
        metro_assets.is_file(),
        "Metro Assets.js missing",
    )

    metro_text = (
        metro_assets.read_text(
            encoding="utf-8"
        )
    )

    require(
        "image-size" in metro_text
        and "readFile" in metro_text,
        (
            "Metro image-size "
            "build-asset surface drift"
        ),
    )

    xcode_root = (
        mobile_root
        / "node_modules"
        / "xcode"
    )

    require(
        xcode_root.is_dir(),
        (
            "installed xcode "
            "package missing"
        ),
    )

    xcode_text = read_text_tree(
        xcode_root
    )

    v4_count = len(
        re.findall(
            r"uuid\.v4\s*\(",
            xcode_text,
        )
    )

    affected_count = len(
        re.findall(
            r"uuid\.v[356]\s*\(",
            xcode_text,
        )
    )

    require(
        v4_count == 1,
        (
            "xcode uuid.v4 "
            "call-surface drift: "
            f"{v4_count}"
        ),
    )

    require(
        affected_count == 0,
        (
            "xcode now calls affected "
            "uuid v3/v5/v6 APIs: "
            f"{affected_count}"
        ),
    )

    return {
        **offline,
        "mode": "installed",
        "image_size_path_count": len(
            observed_paths[
                "image-size"
            ]
        ),
        "uuid_path_count": len(
            observed_paths[
                "uuid"
            ]
        ),
        "xcode_uuid_v4_calls": (
            v4_count
        ),
        "xcode_uuid_v3_v5_v6_calls": (
            affected_count
        ),
    }


def normalize_patch(
    value: Any,
) -> str | None:
    if value is None:
        return None

    if isinstance(value, str):
        return value

    if isinstance(value, dict):
        identifier = value.get(
            "identifier"
        )

        require(
            identifier is None
            or isinstance(
                identifier,
                str,
            ),
            (
                "first_patched_version "
                "identifier invalid"
            ),
        )

        return identifier

    raise DependencyRiskError(
        (
            "first_patched_version "
            "shape invalid"
        )
    )


def http_json(
    url: str,
) -> Any:
    headers = {
        "Accept": (
            "application/vnd.github+json"
        ),
        "User-Agent": (
            "Nutrition-App-dependency-risk"
        ),
    }

    token = os.environ.get(
        "GH_TOKEN"
    )

    if token:
        headers["Authorization"] = (
            f"Bearer {token}"
        )

    request = urllib.request.Request(
        url,
        headers=headers,
    )

    try:
        with urllib.request.urlopen(
            request,
            timeout=30,
        ) as response:
            return json.load(response)
    except Exception as error:
        raise DependencyRiskError(
            (
                "remote advisory "
                f"query failed: {url}"
            )
        ) from error


def advisory_snapshot(
    advisory_id: str,
    package: str,
) -> dict[str, Any]:
    document = http_json(
        (
            "https://api.github.com/"
            "advisories/"
            + advisory_id
        )
    )

    require(
        isinstance(document, dict),
        (
            f"{advisory_id} "
            "response invalid"
        ),
    )

    require(
        document.get("ghsa_id")
        == advisory_id,
        (
            f"{advisory_id} "
            "identity drift"
        ),
    )

    vulnerabilities: list[
        dict[str, Any]
    ] = []

    for item in (
        document.get(
            "vulnerabilities"
        )
        or []
    ):
        if not isinstance(item, dict):
            continue

        package_info = item.get(
            "package"
        )

        if not isinstance(
            package_info,
            dict,
        ):
            continue

        if (
            package_info.get(
                "ecosystem"
            )
            != "npm"
            or package_info.get(
                "name"
            )
            != package
        ):
            continue

        vulnerabilities.append(
            {
                "range": item.get(
                    "vulnerable_version_range"
                ),
                "first_patched_version": normalize_patch(
                    item.get(
                        "first_patched_version"
                    )
                ),
            }
        )

    require(
        bool(vulnerabilities),
        (
            f"{advisory_id} npm "
            "vulnerability entry missing"
        ),
    )

    return {
        "ghsa_id": advisory_id,
        "severity": document.get(
            "severity"
        ),
        "withdrawn_at": document.get(
            "withdrawn_at"
        ),
        "vulnerabilities": sorted(
            vulnerabilities,
            key=lambda item: (
                str(item["range"]),
                str(
                    item[
                        "first_patched_version"
                    ]
                ),
            ),
        ),
    }


def npm_view(
    package: str,
    field: str,
) -> Any:
    process = subprocess.run(
        [
            "npm",
            "view",
            package,
            field,
            "--json",
        ],
        check=False,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )

    require(
        process.returncode == 0,
        (
            "npm view failed for "
            f"{package} {field}\n"
            + process.stderr
        ),
    )

    try:
        return json.loads(
            process.stdout
        )
    except json.JSONDecodeError as error:
        raise DependencyRiskError(
            (
                "npm view returned "
                "invalid JSON for "
                f"{package} {field}"
            )
        ) from error


def capture_remote_snapshot(
) -> dict[str, Any]:
    metro_dependencies = npm_view(
        "metro",
        "dependencies",
    )

    xcode_dependencies = npm_view(
        "xcode",
        "dependencies",
    )

    expo_plugins_dependencies = npm_view(
        "@expo/config-plugins",
        "dependencies",
    )

    require(
        isinstance(
            metro_dependencies,
            dict,
        ),
        (
            "Metro dependency "
            "metadata invalid"
        ),
    )

    require(
        isinstance(
            xcode_dependencies,
            dict,
        ),
        (
            "xcode dependency "
            "metadata invalid"
        ),
    )

    require(
        isinstance(
            expo_plugins_dependencies,
            dict,
        ),
        (
            "@expo/config-plugins "
            "dependency metadata invalid"
        ),
    )

    return {
        "advisories": {
            advisory_id: advisory_snapshot(
                advisory_id,
                package,
            )
            for _,
            (
                package,
                advisory_id,
                _severity,
            )
            in sorted(
                TRACKED_ALERTS.items()
            )
        },
        "npm_registry": {
            "image_size_latest": (
                npm_view(
                    "image-size",
                    "version",
                )
            ),
            "metro_latest": npm_view(
                "metro",
                "version",
            ),
            "metro_image_size_range": (
                metro_dependencies.get(
                    "image-size"
                )
            ),
            "xcode_latest": npm_view(
                "xcode",
                "version",
            ),
            "xcode_uuid_range": (
                xcode_dependencies.get(
                    "uuid"
                )
            ),
            "expo_config_plugins_latest": (
                npm_view(
                    "@expo/config-plugins",
                    "version",
                )
            ),
            "expo_config_plugins_xcode_range": (
                expo_plugins_dependencies.get(
                    "xcode"
                )
            ),
        },
    }


def material_remote_facts(
    snapshot: dict[str, Any],
) -> dict[str, Any]:
    registry = snapshot[
        "npm_registry"
    ]

    return {
        "advisories": snapshot[
            "advisories"
        ],
        "image_size_latest": (
            registry[
                "image_size_latest"
            ]
        ),
        "metro_image_size_range": (
            registry[
                "metro_image_size_range"
            ]
        ),
        "xcode_latest": (
            registry["xcode_latest"]
        ),
        "xcode_uuid_range": (
            registry[
                "xcode_uuid_range"
            ]
        ),
        "expo_config_plugins_xcode_range": (
            registry[
                "expo_config_plugins_xcode_range"
            ]
        ),
    }


def material_changes(
    expected: dict[str, Any],
    observed: dict[str, Any],
) -> list[dict[str, Any]]:
    expected_material = (
        material_remote_facts(
            expected
        )
    )

    observed_material = (
        material_remote_facts(
            observed
        )
    )

    changes: list[
        dict[str, Any]
    ] = []

    for key in sorted(
        expected_material
    ):
        if (
            expected_material[key]
            != observed_material[key]
        ):
            changes.append(
                {
                    "fact": key,
                    "expected": copy.deepcopy(
                        expected_material[
                            key
                        ]
                    ),
                    "observed": copy.deepcopy(
                        observed_material[
                            key
                        ]
                    ),
                }
            )

    return changes


def monitor(
    repo_root: Path,
) -> tuple[int, dict[str, Any]]:
    validate_offline(
        repo_root
    )

    register = read_json(
        repo_root / REGISTER_RELATIVE
    )

    expected = register[
        "monitor_baseline"
    ][
        "remote_snapshot"
    ]

    observed = (
        capture_remote_snapshot()
    )

    changes = material_changes(
        expected,
        observed,
    )

    result = {
        "status": (
            "reevaluation_required"
            if changes
            else "unchanged"
        ),
        "source_issue": 166,
        "reviewed_commit": register[
            "reviewed_commit"
        ],
        "changes": changes,
        "current_snapshot": observed,
    }

    summary_path = os.environ.get(
        "GITHUB_STEP_SUMMARY"
    )

    if summary_path:
        lines = [
            "## Dependency risk monitor",
            "",
            (
                "Status: "
                + result["status"]
            ),
            "",
        ]

        if changes:
            lines.append(
                (
                    "Tracked dependency or "
                    "advisory assumptions "
                    "changed. AUDIT-08 "
                    "requires reevaluation."
                )
            )

            lines.append("")

            lines.extend(
                "- " + change["fact"]
                for change in changes
            )
        else:
            lines.append(
                (
                    "No material tracked "
                    "dependency or advisory "
                    "assumption changed."
                )
            )

        with Path(summary_path).open(
            "a",
            encoding="utf-8",
        ) as handle:
            handle.write(
                "\n".join(lines)
                + "\n"
            )

    return (
        2 if changes else 0,
        result,
    )


def build_parser(
) -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Validate and monitor the "
            "repository-owned dependency "
            "risk register."
        )
    )

    parser.add_argument(
        "--repo-root",
        type=Path,
        default=DEFAULT_ROOT,
    )

    subparsers = parser.add_subparsers(
        dest="command",
        required=True,
    )

    subparsers.add_parser(
        "validate-offline"
    )

    subparsers.add_parser(
        "validate-installed"
    )

    monitor_parser = (
        subparsers.add_parser(
            "monitor"
        )
    )

    monitor_parser.add_argument(
        "--output",
        type=Path,
    )

    return parser


def main() -> int:
    args = build_parser().parse_args()

    repo_root = (
        args.repo_root.resolve()
    )

    try:
        if (
            args.command
            == "validate-offline"
        ):
            result = validate_offline(
                repo_root
            )

            print(
                json.dumps(
                    result,
                    sort_keys=True,
                )
            )

            return 0

        if (
            args.command
            == "validate-installed"
        ):
            result = validate_installed(
                repo_root
            )

            print(
                json.dumps(
                    result,
                    sort_keys=True,
                )
            )

            return 0

        if args.command == "monitor":
            exit_code, result = monitor(
                repo_root
            )

            if args.output is not None:
                write_json(
                    args.output,
                    result,
                )

            print(
                json.dumps(
                    result,
                    sort_keys=True,
                )
            )

            return exit_code

        raise DependencyRiskError(
            "unsupported command"
        )

    except DependencyRiskError as error:
        print(
            f"dependency-risk: {error}",
            file=sys.stderr,
        )

        return 1


if __name__ == "__main__":
    raise SystemExit(main())
