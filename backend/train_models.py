import os
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.cluster import KMeans
from sklearn.ensemble import RandomForestClassifier, RandomForestRegressor
from sklearn.impute import SimpleImputer
from sklearn.metrics import accuracy_score, classification_report, mean_absolute_error, mean_squared_error
from sklearn.model_selection import train_test_split
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler, LabelEncoder

ROOT = Path(__file__).resolve().parent.parent
CSV_PATH = Path(os.getenv("CSV_PATH", str(ROOT / "data" / "factorymind_sensor_data.csv")))
MODEL_DIR = Path(__file__).resolve().parent / "models"
MODEL_DIR.mkdir(exist_ok=True)

if not CSV_PATH.exists():
    raise SystemExit(
        f"Dataset not found: {CSV_PATH}\n"
        "Copy factorymind_sensor_data.csv into the project's data/ folder or set CSV_PATH."
    )

df = pd.read_csv(CSV_PATH)
required = {"timestamp", "parameter", "value", "alarm_status"}
missing = required - set(df.columns)
if missing:
    raise SystemExit(f"CSV missing required columns: {sorted(missing)}")

df["timestamp"] = pd.to_datetime(df["timestamp"], errors="coerce", utc=True)
df["value"] = pd.to_numeric(df["value"], errors="coerce")
df = df.dropna(subset=["timestamp", "parameter", "value"]).sort_values("timestamp")

# One row per timestamp/plant line; one column per sensor parameter.
index_cols = ["timestamp"]
if "plant_line" in df.columns:
    index_cols.append("plant_line")
wide = df.pivot_table(index=index_cols, columns="parameter", values="value", aggfunc="last").reset_index()
wide.columns.name = None

# Build one alarm label per snapshot. Use the most severe/non-normal label if present.
alarm_order = {"NORMAL": 0, "WARNING": 1}
def choose_alarm(series):
    vals = [str(x) for x in series.dropna().unique()]
    if not vals:
        return "UNKNOWN"
    return sorted(vals, key=lambda x: (alarm_order.get(x, 2), x))[-1]

label_df = df.groupby(index_cols, dropna=False)["alarm_status"].apply(choose_alarm).reset_index()
data = wide.merge(label_df, on=index_cols, how="left")
feature_cols = [c for c in wide.columns if c not in index_cols and pd.api.types.is_numeric_dtype(wide[c])]
if not feature_cols:
    raise SystemExit("No numeric sensor parameters found after pivoting.")

# Classifier: time-ordered split, exclude target labels from features.
X = data[feature_cols].replace([np.inf, -np.inf], np.nan)
y = data["alarm_status"].fillna("UNKNOWN").astype(str)
if y.nunique() >= 2 and len(data) >= 10:
    split = max(1, int(len(data) * 0.8))
    if split >= len(data):
        split = len(data) - 1
    X_train, X_test = X.iloc[:split], X.iloc[split:]
    y_train, y_test = y.iloc[:split], y.iloc[split:]
    # Some classes may appear only in test. Train on known classes only and report coverage.
    train_mask = y_train.isin(y_train.unique())
    clf = Pipeline([
        ("imputer", SimpleImputer(strategy="median")),
        ("model", RandomForestClassifier(n_estimators=160, class_weight="balanced", random_state=42))
    ])
    clf.fit(X_train, y_train)
    preds = clf.predict(X_test)
    print("\n=== CLASSIFICATION ===")
    print(f"Time-ordered holdout accuracy: {accuracy_score(y_test, preds):.3f}")
    print(classification_report(y_test, preds, zero_division=0))
    joblib.dump({"model": clf, "features": feature_cols}, MODEL_DIR / "classifier.joblib")
else:
    print("Classification skipped: dataset needs at least two alarm classes and 10 snapshots.")

# Clustering: numeric sensor patterns only; standardize and save reusable pipeline.
cluster_pipeline = Pipeline([
    ("imputer", SimpleImputer(strategy="median")),
    ("scaler", StandardScaler()),
    ("kmeans", KMeans(n_clusters=min(4, max(2, len(data) // 5)), n_init=10, random_state=42))
])
cluster_pipeline.fit(X)
joblib.dump({"pipeline": cluster_pipeline, "features": feature_cols}, MODEL_DIR / "clusterer.joblib")
print("\n=== SEGMENTATION ===")
print(f"Saved K-Means segmentation pipeline using {len(feature_cols)} numeric sensor features.")
print("Cluster labels are patterns, not fault severity labels.")

# Forecast baseline: train a regressor to estimate the next value for raw milk temperature.
target = "raw_milk_temperature"
if target in data.columns and len(data) >= 12:
    series = pd.to_numeric(data[target], errors="coerce")
    # Lag features from the target series only; no future leakage.
    lag_df = pd.DataFrame({
        "lag_1": series.shift(1),
        "lag_2": series.shift(2),
        "lag_3": series.shift(3),
        "target_next": series,
    }).dropna()
    if len(lag_df) >= 8:
        split = max(1, int(len(lag_df) * 0.8))
        split = min(split, len(lag_df)-1)
        reg = Pipeline([
            ("imputer", SimpleImputer(strategy="median")),
            ("model", RandomForestRegressor(n_estimators=120, random_state=42))
        ])
        reg.fit(lag_df[["lag_1", "lag_2", "lag_3"]].iloc[:split], lag_df["target_next"].iloc[:split])
        test_pred = reg.predict(lag_df[["lag_1", "lag_2", "lag_3"]].iloc[split:])
        y_test = lag_df["target_next"].iloc[split:]
        print("\n=== FORECASTING (raw milk temperature baseline) ===")
        print(f"Holdout MAE: {mean_absolute_error(y_test, test_pred):.4f} °C")
        print(f"Holdout RMSE: {np.sqrt(mean_squared_error(y_test, test_pred)):.4f} °C")
        # Save metadata; live endpoint uses a simple rolling baseline until lag inference is wired.
        joblib.dump({"model": reg, "target": target, "features": ["lag_1", "lag_2", "lag_3"]}, MODEL_DIR / "forecast.joblib")
    else:
        print("Forecasting skipped: not enough valid lagged observations.")
else:
    print("Forecasting skipped: raw_milk_temperature column missing or too few snapshots.")

print(f"\nModels saved under: {MODEL_DIR}")
