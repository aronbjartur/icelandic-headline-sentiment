# icelandic-headline-sentiment

Lokaverkefni í `TÖL025M - Inngangur að máltækni`.

Verkefnið skoðar lyndisgreiningu á íslenskum fréttafyrirsögnum frá DV, Vísi og RÚV.

Niðurstöður og myndir má finna í:

- `sentiment_comparison.ipynb`

Helstu skrár í verkefninu eru:

- `dv.py`
- `visir.py`
- `ruv.py`
- `sentiment_preprocess.py`
- `icebert_sentiment.py`
- `dvHreinsun.py`
- `sentiment_comparison.ipynb`

Gögn eru í `gogn/` og samanteknar niðurstöður í:

- `gogn_labeled_master.csv`
- `icebert_labeled_master.csv`

## Keyrsla

Setja fyrst upp pakka:

```bash
pip install -r requirements.txt
```

Ef það virkar ekki má nota virtual environment:

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

Keyra gagnasöfnun:

```bash
python3 dv.py
python3 visir.py
python3 ruv.py
```

Keyra lyndisgreiningu með Gemini:

```bash
export GEMINI_API_KEY="SETJA_LYKIL_HER"
python3 sentiment_preprocess.py
```

Keyra DV flokkun:

```bash
export GEMINI_API_KEY="SETJA_LYKIL_HER"
python3 dvHreinsun.py
```

Keyra samanburð með IceBERT-líkani:

```bash
python3 icebert_sentiment.py
```

Opna svo niðurstöður og myndir í:

```bash
sentiment_comparison.ipynb
```

Ef aðeins á að skoða lokaútkomu verkefnisins þarf ekki að keyra skriptin aftur. Þá nægir að opna:

- `sentiment_comparison.ipynb`
- `gogn_labeled_master.csv`
- `icebert_labeled_master.csv`
