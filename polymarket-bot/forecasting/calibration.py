"""
Platt Scaling calibration.
Fits LogisticRegression on (raw_probability, outcome) pairs to correct LLM forecast attenuation.
"""
from __future__ import annotations

import logging
import pickle
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np

from config.settings import settings

logger = logging.getLogger(__name__)

_COLD_START_WARNED = False


class PlattCalibrator:
    """
    Platt Scaling: learns the mapping from LLM's raw probability → calibrated probability
    via logistic regression on historical predictions vs. actual outcomes.

    Cold-start: if fewer than COLD_START_MIN_SAMPLES resolved markets exist,
    pass raw model output through with a warning.
    """

    def __init__(self) -> None:
        self._cfg = settings.calibration
        self._model = None  # sklearn LogisticRegression
        self._fitted = False
        self._fitted_at: datetime | None = None

    # ------------------------------------------------------------------
    # Fit / train
    # ------------------------------------------------------------------

    def fit(self, predictions: list[float], outcomes: list[int]) -> None:
        """
        Train the Platt Scaling model.
        predictions: raw LLM probabilities in [0, 1]
        outcomes: 1 = YES resolved, 0 = NO resolved
        """
        if len(predictions) < self._cfg.cold_start_min_samples:
            logger.warning(
                "Cannot fit calibrator: only %d samples (need %d). Using pass-through.",
                len(predictions), self._cfg.cold_start_min_samples,
            )
            return

        from sklearn.linear_model import LogisticRegression

        X = np.array(predictions).reshape(-1, 1)
        y = np.array(outcomes)

        model = LogisticRegression(C=1.0, solver="lbfgs", max_iter=1000)
        model.fit(X, y)

        self._model = model
        self._fitted = True
        self._fitted_at = datetime.now(timezone.utc)

        score = self.brier_score(predictions, outcomes)
        logger.info(
            "Platt calibrator fitted on %d samples. Brier score: %.4f", len(predictions), score
        )

    def calibrate(self, raw: float) -> float:
        """
        Transform raw LLM probability into a calibrated probability.
        Falls through (returns raw) if not yet fitted.
        """
        global _COLD_START_WARNED
        raw = max(0.01, min(0.99, raw))

        if not self._fitted or self._model is None:
            if not _COLD_START_WARNED:
                logger.warning(
                    "Calibrator in WARM-UP state (< %d samples). "
                    "Using raw model output — this will be systematically uncalibrated.",
                    self._cfg.cold_start_min_samples,
                )
                _COLD_START_WARNED = True
            return raw

        X = np.array([[raw]])
        calibrated = float(self._model.predict_proba(X)[0][1])
        return max(0.01, min(0.99, calibrated))

    # ------------------------------------------------------------------
    # Evaluation
    # ------------------------------------------------------------------

    def brier_score(self, predictions: list[float], outcomes: list[int]) -> float:
        """
        Compute Brier score. Lower is better. Random = 0.25, Perfect = 0.0.
        """
        if not predictions or not outcomes or len(predictions) != len(outcomes):
            return 0.25  # Return random-baseline if no data

        preds = np.array(predictions, dtype=float)
        outs = np.array(outcomes, dtype=float)
        return float(np.mean((preds - outs) ** 2))

    def is_warm(self) -> bool:
        """Returns True if the calibrator has enough data to be used."""
        return self._fitted

    def needs_retraining(self) -> bool:
        """Check if PLATT_SCALING_RETRAIN_DAYS have passed since last fit."""
        if not self._fitted_at:
            return True
        threshold = timedelta(days=self._cfg.retrain_days)
        return datetime.now(timezone.utc) - self._fitted_at > threshold

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def save(self, path: str | Path | None = None) -> None:
        path = Path(path or self._cfg.model_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        state = {
            "model": self._model,
            "fitted": self._fitted,
            "fitted_at": self._fitted_at,
        }
        with open(path, "wb") as f:
            pickle.dump(state, f)
        logger.info("Calibrator saved to %s", path)

    def load(self, path: str | Path | None = None) -> bool:
        path = Path(path or self._cfg.model_path)
        if not path.exists():
            logger.info("No calibrator file at %s — starting fresh", path)
            return False
        try:
            with open(path, "rb") as f:
                state = pickle.load(f)
            self._model = state["model"]
            self._fitted = state["fitted"]
            self._fitted_at = state.get("fitted_at")
            logger.info("Calibrator loaded from %s (fitted at %s)", path, self._fitted_at)
            return True
        except Exception as exc:
            logger.warning("Could not load calibrator: %s", exc)
            return False

    # ------------------------------------------------------------------
    # Reliability diagram data (for dashboard)
    # ------------------------------------------------------------------

    def reliability_diagram_data(
        self, predictions: list[float], outcomes: list[int], n_bins: int = 10
    ) -> list[dict[str, Any]]:
        """
        Bucket predictions into n_bins and compute observed frequency per bucket.
        Returns list of {midpoint, observed_freq, count} for the dashboard scatter plot.
        """
        if not predictions:
            return []

        bins = np.linspace(0, 1, n_bins + 1)
        preds = np.array(predictions)
        outs = np.array(outcomes, dtype=float)

        result = []
        for i in range(n_bins):
            lo, hi = bins[i], bins[i + 1]
            mask = (preds >= lo) & (preds < hi)
            count = int(mask.sum())
            if count == 0:
                continue
            midpoint = (lo + hi) / 2
            observed_freq = float(outs[mask].mean())
            result.append({
                "midpoint": round(midpoint, 2),
                "observed_freq": round(observed_freq, 3),
                "count": count,
            })

        return result
