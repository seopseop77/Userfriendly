"""Two-stage decision logic (ADR-0030 §D2).

Stub for CP2. CP5 wires the pipeline:

- Stage 1: compute ``max_similarity`` over the org's ``scope_chunks``.
  Threshold rule (``THRESHOLD ± AMBIGUOUS_BAND / 2``) decides
  ``stage1_in`` / ``stage1_out`` / route-to-stage-2.
- Stage 2 (on ambiguous band only): call :mod:`.judge` with the
  constructed message input plus top-K most-similar chunks. Verdict
  becomes ``stage2_in`` / ``stage2_out``.
- Output: a ``ScopeAlertRow`` (defined in :mod:`.storage`) ready for
  insertion by :mod:`.plugin`.
"""

from __future__ import annotations
