"""Native command sandbox regression for reviewer-consumed candidate evidence."""
from __future__ import annotations

import os

from test_candidate_evidence import CandidateFixture, evidence


class TestCandidateReviewRuntime(CandidateFixture):
    def test_output_symlink_cannot_write_tested_source(self):
        if os.environ.get("NUTRITION_REQUIRE_EVIDENCE_SANDBOX") != "1":
            self.skipTest("Explicit native sandbox qualification required")
        binding = self.binding()
        binding["requirements"][0]["argv"] = ["{python}", "-c",
            "import os; from pathlib import Path; "
            "link=Path(os.environ['NUTRITION_REVIEW_OUTPUT_DIR'])/'backdoor'; "
            "link.symlink_to(Path.cwd(), target_is_directory=True); "
            "p=link/'app.py'; "
            "\ntry: p.write_text('changed'); raise AssertionError('source write allowed')"
            "\nexcept PermissionError: pass"]
        observed = evidence.run_check(self.repo, binding, "focused", self.root / "via-output")
        self.assertEqual(observed["status"], "passed", observed)
        self.assertEqual(observed["tested_source_before"], observed["tested_source_after"])
        evidence.validate_artifacts(observed)
