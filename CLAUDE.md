# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project does

Monitors changes in Colombian higher-education programs registered in [SNIES](https://hecaa.mineducacion.gov.co/consultaspublicas/programas) for Universidad del Norte (Uninorte). On each run it:

1. Downloads the current active-programs list from the SNIES public portal via Selenium.
2. Compares the new snapshot against the previous one to detect **new**, **inactive**, and **modified** programs.
3. Enriches each program row with the corresponding Uninorte academic division (via `Categorización divisiones SNIES.xlsx`, sheet `Hoja3`, column `DIVISIÓN UNINORTE`).
4. Appends findings to cumulative Excel files and sends an email report via Outlook (`win32com`).

Two separate pipelines exist — one for **pregrado** (undergraduate) and one for **posgrado** (graduate).

## Running the code

The production entry point is the refactored script:

```bash
pip install -r requirements.txt
python scripts/run_snies.py
```

The historical-analysis script runs standalone (requires a `Programas/` directory with snapshots named `Programas DD-MM-YY.xlsx`):

```bash
python analisis_historico_pregrado.py
```

The original notebooks are kept in `notebooks/` as reference only.

## Key data conventions

| Concept | Detail |
|---|---|
| Program identity key | `PROGINSTI` = `CÓDIGO_SNIES_DEL_PROGRAMA` + `-` + `NÚMERO_CRÉDITOS` |
| Snapshot files | `Programas/Programas DD-MM-YY.xlsx` — last 2 rows are SNIES footer noise and must be stripped (`.iloc[:-2]`) |
| Division mapping | Join on `CINE_F_2013_AC_CAMPO_DETALLADO`; unmatched rows become `"Sin clasificar"` |
| Output folder | `Novedades_SNIES/` for charts; `data/novedades/` for cumulative Excel novedades |
| Previous snapshot refs | `data/Programas_pregrado_anterior.xlsx`, `data/Programas_posgrado_anterior.xlsx` |

## Architecture

```
snies-monitor/
├── notebooks/
│   ├── Structuring_SNIES.ipynb   # Pregrado: download → diff → classify → export → email
│   └── sniespos.ipynb            # Posgrado: same flow, older version with hardcoded paths
├── analisis_historico_pregrado.py # Reads all Programas/*.xlsx snapshots, plots 3 trend charts
├── data/
│   ├── Categorización divisiones SNIES.xlsx  # Reference: CINE code → Uninorte division
│   ├── Programas_pregrado_anterior.xlsx      # Previous pregrado snapshot
│   ├── Programas_posgrado_anterior.xlsx      # Previous posgrado snapshot
│   └── novedades/                            # Cumulative Nuevos/Inactivos/Modificados xlsx
└── scripts/                                  # Placeholder scripts (currently empty)
```

The diff logic classifies changes in three categories:
- **Nuevos**: SNIES code present in current snapshot but absent in previous.
- **Inactivos**: SNIES code present in previous but absent in current.
- **Modificados**: SNIES code in both snapshots but `NÚMERO_CRÉDITOS` changed (identified via the `PROGINSTI` composite key).

Modified programs are removed from the Nuevos and Inactivos sets to avoid double-counting.

## Known issues / migration notes

- `sniespos.ipynb` references hardcoded paths under `C:\Users\ecpereira\Universidad del Norte\...` — these need updating to relative paths (as done in `Structuring_SNIES.ipynb`).
- Email sending (`win32com.client`) requires a locally installed Outlook and only works on Windows.
- The Selenium scraper uses Chrome; ChromeDriver must match the installed Chrome version.
