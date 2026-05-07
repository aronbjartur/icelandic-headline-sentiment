from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd
import torch
from transformers import AutoModelForSequenceClassification, AutoTokenizer


MODEL_ID = "AMBJ24/icelandic-sentiment"
SOURCE_ORDER = ["dv", "visir", "ruv"]
LABEL_MAP = {
    "negative": "Negative",
    "neutral": "Neutral",
    "positive": "Positive",
}


def lesa_gogn(path: Path) -> pd.DataFrame:
    df = pd.read_csv(path, encoding="utf-8-sig")
    if "source" not in df.columns or "fyrirsogn" not in df.columns:
        raise ValueError("Vantar source eða fyrirsogn")

    df = df[["source", "fyrirsogn"]].copy()
    df["source"] = df["source"].fillna("").astype(str).str.strip().str.lower()
    df["fyrirsogn"] = (
        df["fyrirsogn"]
        .fillna("")
        .astype(str)
        .str.replace(r"\s+", " ", regex=True)
        .str.strip()
    )
    df = df[df["source"].isin(SOURCE_ORDER)]
    df = df[df["fyrirsogn"] != ""]
    return df.reset_index(drop=True)


def taka_urtak(df: pd.DataFrame, per_source: int | None) -> pd.DataFrame:
    if per_source is None:
        return df.reset_index(drop=True)

    partar = []
    for source in SOURCE_ORDER:
        partur = df[df["source"] == source].head(per_source)
        partar.append(partur)
    return pd.concat(partar, ignore_index=True)


def saekja_likan():
    tokenizer = AutoTokenizer.from_pretrained(MODEL_ID)
    model = AutoModelForSequenceClassification.from_pretrained(MODEL_ID)
    return tokenizer, model


def finna_taeki() -> str:
    if torch.cuda.is_available():
        return "cuda"
    if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def merkja(df: pd.DataFrame, batch_size: int = 32) -> pd.DataFrame:
    tokenizer, model = saekja_likan()
    device = finna_taeki()
    model.to(device)
    model.eval()

    id2label = {int(k): v for k, v in model.config.id2label.items()}
    rows = []
    total = len(df)

    for start in range(0, total, batch_size):
        end = min(start + batch_size, total)
        texts = df.iloc[start:end]["fyrirsogn"].tolist()

        inputs = tokenizer(
            texts,
            return_tensors="pt",
            padding=True,
            truncation=True,
            max_length=128,
        )
        inputs = {key: value.to(device) for key, value in inputs.items()}

        with torch.no_grad():
            logits = model(**inputs).logits
            pred_ids = torch.argmax(logits, dim=-1).tolist()

        for i, pred_id in enumerate(pred_ids):
            raw_label = str(id2label[pred_id]).strip().lower()
            sentiment = LABEL_MAP.get(raw_label, "Neutral")
            row = {
                "source": df.iloc[start + i]["source"],
                "fyrirsogn": df.iloc[start + i]["fyrirsogn"],
                "sentiment": sentiment,
            }
            rows.append(row)

        print(f"Processed {len(rows)}/{total}")

    return pd.DataFrame(rows)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", default="gogn_labeled_master.csv")
    parser.add_argument("--output", default="icebert_labeled_master.csv")
    parser.add_argument("--per-source", type=int)
    parser.add_argument("--batch-size", type=int, default=32)
    args = parser.parse_args()

    if args.per_source is not None and args.per_source < 1:
        raise ValueError("Rangt input")
    if args.batch_size < 1:
        raise ValueError("Rangt input")

    input_path = Path(args.input)
    output_path = Path(args.output)

    print("Les")
    df = lesa_gogn(input_path)
    df = taka_urtak(df, args.per_source)
    print(f"Fjoldi: {len(df)}")

    print("Merki")
    out_df = merkja(df, batch_size=args.batch_size)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    out_df.to_csv(output_path, index=False, encoding="utf-8-sig")
    print(f"Vistað: {output_path}")


if __name__ == "__main__":
    main()
