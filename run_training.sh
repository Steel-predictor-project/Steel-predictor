#!/usr/bin/env bash
# One-command reproduction of the Steel Property Predictor model.
# Installs dependencies and re-runs the v2 training pipeline, regenerating
# model weights, the metrics summary, and all predictions from the
# processed dataset in data/processed/.
set -euo pipefail

python -m pip install -r requirements.txt
python scripts/train_model_v2.py

echo
echo "Done. Outputs:"
echo "  models/model_weights.json      (serialized model for inference)"
echo "  models/model_summary.json      (metrics + methodology)"
echo "  data/processed/all_predictions.csv"
