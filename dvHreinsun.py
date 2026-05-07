from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

import pandas as pd
from google import genai
from google.genai import types


MODEL_ID = "gemini-3-flash-preview"
BATCH_SIZE = 50
SLEEP_SECONDS = 0.1
MAX_RETRIES = 3
OUTPUT_COLUMN = "hreinsad_flokkun"
CLASS_ORDER = ["Innlent", "Erlent", "Sport", "Annað"]
VALID_CLASSES = set(CLASS_ORDER)
CLASS_NORMALIZATION = {
    "innlent": "Innlent",
    "erlent": "Erlent",
    "sport": "Sport",
    "annað": "Annað",
    "annad": "Annað",
}


def load_dv_data(input_path: Path) -> pd.DataFrame:
    """Load DV data and keep only rows we can classify."""
    df = pd.read_csv(input_path, encoding="utf-8-sig")

    required_columns = ["fyrirsogn"]
    for column in required_columns:
        if column not in df.columns:
            raise ValueError(f"{input_path.name} vantar '{column}' dálk.")

    df["fyrirsogn"] = (
        df["fyrirsogn"]
        .fillna("")
        .astype(str)
        .str.replace(r"\s+", " ", regex=True)
        .str.strip()
    )
    df["lysing"] = (
        df.get("lysing", "")
        .fillna("")
        .astype(str)
        .str.replace(r"\s+", " ", regex=True)
        .str.strip()
    )
    df["flokkur"] = df.get("flokkur", "").fillna("").astype(str).str.strip()
    df["flokkar"] = df.get("flokkar", "").fillna("").astype(str).str.strip()
    df["slod"] = df.get("slod", "").fillna("").astype(str).str.strip()

    df = df[df["fyrirsogn"] != ""].reset_index(drop=True)
    return df


def extract_url_segment(url: str) -> str:
    """Return the first path segment after the domain."""
    parts = str(url).split("/")
    return parts[3] if len(parts) > 3 else ""


def build_batch_payload(batch_df: pd.DataFrame) -> list[dict]:
    """Build compact structured records for one Gemini batch."""
    records: list[dict] = []
    for _, row in batch_df.iterrows():
        records.append(
            {
                "id": int(row["id"]) if "id" in batch_df.columns and pd.notna(row["id"]) else None,
                "fyrirsogn": row["fyrirsogn"],
                "lysing": row["lysing"],
                "flokkur": row["flokkur"],
                "flokkar": row["flokkar"],
                "url_segment": extract_url_segment(row["slod"]),
            }
        )
    return records


def build_prompt(records: list[dict]) -> str:
    """Build a strong Gemini prompt for DV section cleanup."""
    records_json = json.dumps(records, ensure_ascii=False)
    return (
        "You are classifying Icelandic DV news items into exactly one of four classes: "
        "Innlent, Erlent, Sport, eða Annað. "
        "Use the headline first, but also use description, category fields, and URL segment if helpful. "
        "Classify as Sport for sports coverage and 433/sport content. "
        "Classify as Innlent for Icelandic domestic news, politics, courts, police, samfélagsmál, and local issues. "
        "Classify as Erlent for foreign or international news where the main subject is outside Iceland. "
        "Classify as Annað for opinion, culture, lifestyle, entertainment, sponsored content, columns, or anything that is not clearly the other three. "
        "Return strictly a JSON array of strings, one label per item, using only these exact values: "
        '["Innlent", "Erlent", "Sport", "Annað"]. '
        "The order must match the input exactly. "
        f"Items: {records_json}"
    )


def clean_json_response(raw_text: str) -> str:
    """Remove code fences if Gemini wraps the JSON."""
    cleaned_text = raw_text.strip()
    cleaned_text = re.sub(r"^```(?:json)?\s*", "", cleaned_text, flags=re.IGNORECASE)
    cleaned_text = re.sub(r"\s*```$", "", cleaned_text)
    return cleaned_text.strip()


def normalize_labels(labels: list[str]) -> list[str]:
    """Normalize Gemini labels into the exact four allowed classes."""
    normalized: list[str] = []
    for label in labels:
        normalized_label = CLASS_NORMALIZATION.get(
            str(label).strip().lower(),
            str(label).strip(),
        )
        if normalized_label not in VALID_CLASSES:
            normalized_label = "Annað"
        normalized.append(normalized_label)
    return normalized


def classify_batch(client: genai.Client, batch_df: pd.DataFrame) -> list[str]:
    """Send one batch to Gemini and return cleaned section labels."""
    records = build_batch_payload(batch_df)
    prompt = build_prompt(records)

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            response = client.models.generate_content(
                model=MODEL_ID,
                contents=prompt,
                config=types.GenerateContentConfig(
                    temperature=0,
                    response_mime_type="application/json",
                    response_schema=list[str],
                    thinking_config=types.ThinkingConfig(
                        thinking_level="minimal" if "preview" in MODEL_ID else "low"
                    ),
                ),
            )

            raw_text = (response.text or "").strip()
            if not raw_text:
                raise ValueError("Gemini skilaði tómu svari.")

            json_text = clean_json_response(raw_text)
            labels = json.loads(json_text)

            if not isinstance(labels, list):
                raise ValueError("Gemini svaraði ekki með JSON lista.")

            if len(labels) != len(batch_df):
                raise ValueError(
                    f"Gemini skilaði {len(labels)} labels fyrir batch af stærð {len(batch_df)}."
                )

            return normalize_labels(labels)

        except Exception as exc:
            print(f"Batch villa (tilraun {attempt}/{MAX_RETRIES}): {exc}")
            if attempt < MAX_RETRIES:
                time.sleep(SLEEP_SECONDS)

    return ["Annað"] * len(batch_df)


def run() -> None:
    """Main DV cleanup runner."""
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("VILLA: Þú verður að gera 'export GEMINI_API_KEY=...' í terminal")
        return

    input_path = Path("gogn/dv_gogn.csv")
    output_path = Path("gogn/dv_hreinsad.csv")

    print("--- 1. Hleð DV gögnum ---")
    df = load_dv_data(input_path)
    total = len(df)
    print(f"Fann {total:,} DV færslur til að flokka.")

    client = genai.Client(api_key=api_key)
    labels: list[str] = []

    print(f"--- 2. Keyri flokkun með {MODEL_ID} ---")
    for start in range(0, total, BATCH_SIZE):
        end = min(start + BATCH_SIZE, total)
        batch_df = df.iloc[start:end].copy()
        batch_labels = classify_batch(client, batch_df)
        labels.extend(batch_labels)

        print(f"Processed {len(labels):,}/{total:,} DV færslur...")

        if len(labels) < total:
            time.sleep(SLEEP_SECONDS)

    df[OUTPUT_COLUMN] = labels

    print("--- 3. Vista niðurstöðu ---")
    df.to_csv(output_path, index=False, encoding="utf-8-sig")

    counts = (
        df[OUTPUT_COLUMN]
        .value_counts()
        .reindex(CLASS_ORDER, fill_value=0)
    )

    print(f"Niðurstöður vistaðar í {output_path}")
    print("\nFjöldi eftir flokki:")
    print(counts.to_string())


if __name__ == "__main__":
    run()
