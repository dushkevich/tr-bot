"""
Tests for forecasting/calibration.py (Platt Scaling)
"""
import pytest
from unittest.mock import patch


class TestPlattCalibrator:
    def test_fit_requires_minimum_samples(self):
        from forecasting.calibration import PlattCalibrator
        cal = PlattCalibrator()
        # Only 5 samples — below cold_start_min_samples=20
        cal.fit([0.7, 0.6, 0.8, 0.5, 0.9], [1, 0, 1, 0, 1])
        assert not cal.is_warm(), "Should not be warm with < 20 samples"

    def test_fit_succeeds_with_sufficient_samples(self, sample_calibration_data):
        from forecasting.calibration import PlattCalibrator
        cal = PlattCalibrator()
        preds, outcomes = zip(*sample_calibration_data)
        cal.fit(list(preds), list(outcomes))
        assert cal.is_warm()
        assert cal._model is not None

    def test_calibrate_passthrough_when_not_fitted(self):
        from forecasting.calibration import PlattCalibrator
        cal = PlattCalibrator()
        # Should return raw value unchanged (cold start pass-through)
        raw = 0.73
        result = cal.calibrate(raw)
        assert result == pytest.approx(raw, abs=0.01)

    def test_calibrate_returns_valid_range(self, sample_calibration_data):
        from forecasting.calibration import PlattCalibrator
        cal = PlattCalibrator()
        preds, outcomes = zip(*sample_calibration_data)
        cal.fit(list(preds), list(outcomes))
        for p in [0.1, 0.3, 0.5, 0.7, 0.9]:
            calibrated = cal.calibrate(p)
            assert 0.01 <= calibrated <= 0.99, f"Calibrated {p} → {calibrated} out of range"

    def test_brier_score_random_baseline(self):
        from forecasting.calibration import PlattCalibrator
        cal = PlattCalibrator()
        # All predictions = 0.5 → Brier score should equal 0.25 (random)
        preds = [0.5] * 100
        outcomes = [1 if i % 2 == 0 else 0 for i in range(100)]
        brier = cal.brier_score(preds, outcomes)
        assert brier == pytest.approx(0.25, abs=0.01)

    def test_brier_score_perfect_predictions(self):
        from forecasting.calibration import PlattCalibrator
        cal = PlattCalibrator()
        preds = [0.99, 0.01, 0.99, 0.01]
        outcomes = [1, 0, 1, 0]
        brier = cal.brier_score(preds, outcomes)
        assert brier < 0.01  # Near-perfect

    def test_brier_score_empty_returns_baseline(self):
        from forecasting.calibration import PlattCalibrator
        cal = PlattCalibrator()
        brier = cal.brier_score([], [])
        assert brier == pytest.approx(0.25)

    def test_save_and_load(self, tmp_path, sample_calibration_data):
        from forecasting.calibration import PlattCalibrator
        cal = PlattCalibrator()
        preds, outcomes = zip(*sample_calibration_data)
        cal.fit(list(preds), list(outcomes))

        path = tmp_path / "test_calibrator.pkl"
        cal.save(path)

        # Load into fresh calibrator
        cal2 = PlattCalibrator()
        success = cal2.load(path)
        assert success
        assert cal2.is_warm()

        # Should produce same output
        for p in [0.3, 0.6, 0.8]:
            assert cal.calibrate(p) == pytest.approx(cal2.calibrate(p), abs=0.001)

    def test_load_missing_file_returns_false(self, tmp_path):
        from forecasting.calibration import PlattCalibrator
        cal = PlattCalibrator()
        result = cal.load(tmp_path / "nonexistent.pkl")
        assert result is False
        assert not cal.is_warm()

    def test_needs_retraining_when_no_fit(self):
        from forecasting.calibration import PlattCalibrator
        cal = PlattCalibrator()
        assert cal.needs_retraining() is True

    def test_reliability_diagram_data(self, sample_calibration_data):
        from forecasting.calibration import PlattCalibrator
        cal = PlattCalibrator()
        preds, outcomes = zip(*sample_calibration_data)
        result = cal.reliability_diagram_data(list(preds), list(outcomes))
        assert isinstance(result, list)
        for point in result:
            assert "midpoint" in point
            assert "observed_freq" in point
            assert "count" in point
            assert 0 <= point["midpoint"] <= 1
            assert 0 <= point["observed_freq"] <= 1
            assert point["count"] >= 1

    def test_reliability_diagram_empty_input(self):
        from forecasting.calibration import PlattCalibrator
        cal = PlattCalibrator()
        result = cal.reliability_diagram_data([], [])
        assert result == []
