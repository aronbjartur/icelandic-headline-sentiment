from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

import pandas as pd
from google import genai
from google.genai import types


# --- STILLINGAR ---
# Byggt á opinberu Google GenAI SDK skjölunum.
MODEL_ID = "gemini-3-flash-preview"
BATCH_SIZE = 50
SLEEP_SECONDS = 0.1
MAX_RETRIES = 3

# Við síum aðeins þessa miðla
TARGET_PREFIXES = ("visir", "ruv", "dv")
SENTIMENT_ORDER = ["Positive", "Neutral", "Negative"]
VALID_SENTIMENTS = set(SENTIMENT_ORDER)
SENTIMENT_NORMALIZATION = {
    "positive": "Positive",
    "neutral": "Neutral",
    "negative": "Negative",
}


def load_data(data_dir: Path) -> pd.DataFrame:
    """Hleður og sameinar CSV skrár frá Vísi, RÚV og DV."""
    csv_paths = sorted(
        p for p in data_dir.glob("*.csv") if p.stem.startswith(TARGET_PREFIXES)
    )

    if not csv_paths:
        raise FileNotFoundError(
            f"Engar skrár fundust í {data_dir} sem byrja á {TARGET_PREFIXES}"
        )

    frames: list[pd.DataFrame] = []
    for path in csv_paths:
        # utf-8-sig er nauðsynlegt fyrir íslenskuna
        df = pd.read_csv(path, encoding="utf-8-sig")
        if "fyrirsogn" not in df.columns:
            continue

        # Bætum við hvaða miðill þetta er
        source = path.stem.replace("_gogn", "")

        if "source" not in df.columns:
            df["source"] = source
        else:
            df["source"] = df["source"].fillna(source).astype(str)

        frames.append(df[["fyrirsogn", "source"]].copy())

    if not frames:
        raise ValueError("Engin nothæf gögn fundust með 'fyrirsogn' dálki.")

    return pd.concat(frames, ignore_index=True)


def clean_data(df: pd.DataFrame) -> pd.DataFrame:
    """Hreinsar gögnin fyrir greiningu."""
    cleaned_df = df.copy()

    # Hreinsa tómabil og breyta í streng
    cleaned_df["fyrirsogn"] = (
        cleaned_df["fyrirsogn"]
        .fillna("")
        .astype(str)
        .str.replace(r"\s+", " ", regex=True)
        .str.strip()
    )

    # Fjarlægja tómar línur
    cleaned_df = cleaned_df[cleaned_df["fyrirsogn"] != ""]

    # Fjarlægja tvítökur
    cleaned_df = cleaned_df.drop_duplicates(subset=["fyrirsogn"])

    # Aðeins fyrirsagnir með 3 orð eða fleiri (sía burt rusl)
    cleaned_df = cleaned_df[cleaned_df["fyrirsogn"].str.split().str.len() >= 3]

    return cleaned_df.reset_index(drop=True)


def build_prompt(headlines: list[str]) -> str:
    """Smíðar batch prompt fyrir Gemini."""
    return (
        "You are a linguistic expert. "
        f"Analyze the sentiment of the following {len(headlines)} Icelandic news headlines. "
        "Return the results strictly as a JSON array of strings, "
        "where each string is either 'Positive', 'Negative', or 'Neutral'. "
        "Ensure the order matches the input list exactly. "
        f"Headlines: {json.dumps(headlines, ensure_ascii=False)}"
    )


def clean_json_response(raw_text: str) -> str:
    """Hreinsar ```json``` code fences ef módelið bætir þeim við."""
    cleaned_text = raw_text.strip()
    cleaned_text = re.sub(r"^```(?:json)?\s*", "", cleaned_text, flags=re.IGNORECASE)
    cleaned_text = re.sub(r"\s*```$", "", cleaned_text)
    return cleaned_text.strip()


def normalize_sentiment_labels(labels: list[str]) -> list[str]:
    """Normaliserar labels frá Gemini yfir í okkar þrjú leyfðu gildi."""
    normalized = []
    for label in labels:
        normalized_label = SENTIMENT_NORMALIZATION.get(
            str(label).strip().lower(),
            str(label).strip(),
        )
        if normalized_label not in VALID_SENTIMENTS:
            normalized_label = "Neutral"
        normalized.append(normalized_label)
    return normalized


def analyze_batch(client: genai.Client, headlines: list[str]) -> list[str]:
    """Sendir batch af fyrirsögnum til Gemini 3 Flash og fær JSON svar."""
    prompt = build_prompt(headlines)

    for attempt in range(1, MAX_RETRIES + 1):
        try:
            # Gemini 3 stillingar byggðar á opinberum skjölum.
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
                raise ValueError("Svarið var ekki JSON listi.")

            if len(labels) != len(headlines):
                raise ValueError(
                    f"Fékk {len(labels)} labels fyrir {len(headlines)} fyrirsagnir."
                )

            return normalize_sentiment_labels(labels)

        except Exception as exc:
            print(f"Batch villa (tilraun {attempt}/{MAX_RETRIES}): {exc}")
            if attempt < MAX_RETRIES:
                time.sleep(SLEEP_SECONDS)

    return ["Neutral"] * len(headlines)


def run() -> None:
    """Aðal keyrsla, hentar vel í notebook eða Colab."""
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("VILLA: Þú verður að gera 'export GEMINI_API_KEY=...' í terminal")
        return

    client = genai.Client(api_key=api_key)

    print("--- 1. Undirbý gögn ---")
    data_folder = Path("gogn")
    master_df = load_data(data_folder)
    cleaned_df = clean_data(master_df)

    total = len(cleaned_df)
    print(f"Fann samtals {total:,} hreinar fyrirsagnir.")

    all_results: list[str] = []

    print(f"--- 2. Keyri greiningu með {MODEL_ID} ---")
    for start in range(0, total, BATCH_SIZE):
        end = min(start + BATCH_SIZE, total)
        batch = cleaned_df.iloc[start:end]["fyrirsogn"].tolist()

        labels = analyze_batch(client, batch)
        all_results.extend(labels)

        print(f"Processed {len(all_results):,}/{total:,} headlines...")

        if len(all_results) < total:
            time.sleep(SLEEP_SECONDS)

    cleaned_df["sentiment"] = all_results

    # Tryggjum að outputið hafi allavega þessa dálka fremst.
    cleaned_df = cleaned_df[["source", "fyrirsogn", "sentiment"]]

    output_path = Path("gogn_labeled_master.csv")
    cleaned_df.to_csv(output_path, index=False, encoding="utf-8-sig")

    print("\n--- VERKEFNI LOKIÐ ---")
    print(f"Niðurstöður vistaðar í {output_path}")


if __name__ == "__main__":
    run()
