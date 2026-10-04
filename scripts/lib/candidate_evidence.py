"""Historical path retained for C/R/T provenance, not current evidence dispatch.

The old implementation is archived under lib.legacy_ri. Public task evidence and
execution commands are retired. Only immutable recovery readers are exported here.
"""
from lib.legacy_ri.candidate_evidence import EvidenceError, digest, frozen_contract

__all__ = ["EvidenceError", "digest", "frozen_contract"]
