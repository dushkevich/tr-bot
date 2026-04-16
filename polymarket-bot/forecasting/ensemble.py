"""
Ensemble combiner for multi-model estimates.
Default Phase 1: single model, pass-through.
Phase 2+: trimmed mean (drops highest and lowest, averages remainder).
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def ensemble_estimates(estimates: list[float]) -> float:
    """
    Combine multiple probability estimates into a single ensemble estimate.
    - 1 estimate: pass through
    - 2 estimates: simple average
    - 3+ estimates: trimmed mean (drop min and max, average remainder)

    All estimates must be in [0, 1].
    """
    if not estimates:
        raise ValueError("Cannot ensemble an empty list of estimates")

    estimates = [max(0.01, min(0.99, e)) for e in estimates]

    if len(estimates) == 1:
        return estimates[0]

    if len(estimates) == 2:
        result = sum(estimates) / 2
        logger.debug("Ensemble (mean of 2): %.3f", result)
        return result

    # Trimmed mean: remove min and max, average the rest
    sorted_ests = sorted(estimates)
    trimmed = sorted_ests[1:-1]
    result = sum(trimmed) / len(trimmed)
    logger.debug(
        "Ensemble (trimmed mean, n=%d, dropped %.3f and %.3f): %.3f",
        len(estimates), sorted_ests[0], sorted_ests[-1], result,
    )
    return result
