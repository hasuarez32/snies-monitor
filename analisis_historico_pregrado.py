
"""
analisis_historico_pregrado.py
-------------------------------
Carga todos los snapshots históricos de SNIES Pregrado, construye una serie
de tiempo por División Uninorte y guarda tres gráficos en Novedades_SNIES/.

Si los archivos de gráficos ya existen, se eliminan antes de regenerarlos.

Diseñado para ejecución automática (sin intervención humana):
  python analisis_historico_pregrado.py

Dependencias: pandas openpyxl matplotlib
"""

import os
import re
import glob
import warnings
import pandas as pd
import matplotlib
matplotlib.use("Agg")           # backend no-interactivo: obligatorio en automatización
import matplotlib.pyplot as plt
import matplotlib.dates as mdates
import matplotlib.ticker as ticker
from datetime import datetime

warnings.filterwarnings("ignore")

# ── Rutas (relativas al directorio de este script) ────────────────────────────
BASE     = os.path.dirname(os.path.abspath(__file__))
SNAP_DIR = os.path.join(BASE, "Programas")
CAT_FILE = os.path.join(BASE, "Categorización divisiones SNIES .xlsx")
OUT_DIR  = os.path.join(BASE, "Novedades_SNIES")

# ── Paleta de colores por división ────────────────────────────────────────────
COLORS = {
    "Ingenierías":                                    "#1f77b4",
    "Escuela de Negocios":                            "#ff7f0e",
    "Humanidades y Cs. Sociales":                     "#2ca02c",
    "Instituto de Estudios en Educación":             "#d62728",
    "Ciencias de la Salud":                           "#9467bd",
    "Derecho, C. Política y Rel. Internacionales":    "#e377c2",
    "Ciencias Básicas":                               "#7f7f7f",
    "Escuela de Arquitectura, Urbanismo y Diseño":    "#bcbd22",
    "Música":                                         "#17becf",
    "Instituto de Idiomas":                           "#aec7e8",
    "Otro":                                           "#8c564b",
    "Sin clasificar":                                 "#dddddd",
}


# ── Carga de datos ────────────────────────────────────────────────────────────

def load_categorizacion() -> pd.DataFrame:
    return (
        pd.read_excel(CAT_FILE, sheet_name="Hoja3")[
            ["CINE_F_2013_AC_CAMPO_DETALLADO", "DIVISIÓN UNINORTE"]
        ]
        .drop_duplicates()
    )


def _parse_date(filepath: str) -> datetime | None:
    m = re.search(r"(\d{2}-\d{2}-\d{2})\.xlsx$", os.path.basename(filepath))
    return datetime.strptime(m.group(1), "%d-%m-%y") if m else None


def build_time_series(cat: pd.DataFrame) -> pd.DataFrame:
    """
    Devuelve un DataFrame pivotado:
        index   → fecha del snapshot
        columns → DIVISIÓN UNINORTE
        values  → número de programas activos
    """
    files = glob.glob(os.path.join(SNAP_DIR, "Programas *.xlsx"))
    dated = sorted(
        [(d, f) for f in files if (d := _parse_date(f))],
        key=lambda x: x[0],
    )
    if not dated:
        raise FileNotFoundError(f"No se encontraron archivos 'Programas DD-MM-YY.xlsx' en {SNAP_DIR}")

    records = []
    for date, filepath in dated:
        df = pd.read_excel(filepath).iloc[:-2]          # quita 2 filas de pie de página
        df = df.merge(cat, on="CINE_F_2013_AC_CAMPO_DETALLADO", how="left")
        df["DIVISIÓN UNINORTE"] = df["DIVISIÓN UNINORTE"].fillna("Sin clasificar")
        counts = df.groupby("DIVISIÓN UNINORTE").size().reset_index(name="programas")
        counts["fecha"] = date
        records.append(counts)

    ts = pd.concat(records, ignore_index=True)
    return ts.pivot_table(
        index="fecha", columns="DIVISIÓN UNINORTE", values="programas", aggfunc="sum"
    ).fillna(0)


# ── Gráficos ──────────────────────────────────────────────────────────────────

def _fmt_xaxis(ax):
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))
    ax.xaxis.set_major_locator(mdates.MonthLocator(interval=2))
    plt.xticks(rotation=45, ha="right")


def chart_evolucion(pivot: pd.DataFrame, out_path: str) -> None:
    """Línea de tiempo: programas activos por división."""
    fig, ax = plt.subplots(figsize=(14, 7))
    for div in pivot.columns:
        ax.plot(
            pivot.index, pivot[div],
            label=div,
            color=COLORS.get(div, "#333333"),
            linewidth=1.8,
            marker="o", markersize=2,
        )
    _fmt_xaxis(ax)
    ax.set_title(
        "Evolución histórica de programas activos por División Uninorte (Pregrado)",
        fontsize=13, fontweight="bold",
    )
    ax.set_xlabel("Fecha")
    ax.set_ylabel("Número de programas activos")
    ax.legend(loc="upper left", fontsize=8, framealpha=0.8)
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


def chart_variacion_neta(pivot: pd.DataFrame, out_path: str) -> None:
    """Barras horizontales: cambio absoluto entre primera y última fecha."""
    net = (pivot.iloc[-1] - pivot.iloc[0]).sort_values()
    first_date = pivot.index[0].strftime("%d/%m/%Y")
    last_date  = pivot.index[-1].strftime("%d/%m/%Y")
    bar_colors = ["#d62728" if v < 0 else "#2ca02c" for v in net.values]

    fig, ax = plt.subplots(figsize=(10, 6))
    bars = ax.barh(net.index, net.values, color=bar_colors)
    ax.bar_label(bars, fmt="%+.0f", padding=4, fontsize=9)
    ax.axvline(0, color="black", linewidth=0.8)
    ax.set_title(
        f"Variación neta de programas por División\n({first_date}  →  {last_date})",
        fontsize=12, fontweight="bold",
    )
    ax.set_xlabel("Programas ganados / perdidos")
    ax.grid(axis="x", alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


def chart_crecimiento_pct(pivot: pd.DataFrame, out_path: str) -> None:
    """Crecimiento porcentual acumulado desde la primera fecha (excluye Otro y Sin clasificar)."""
    exclude = {"Sin clasificar", "Otro"}
    cols = [c for c in pivot.columns if c not in exclude]
    base = pivot[cols].iloc[0].replace(0, float("nan"))   # evita división por cero
    pct  = (pivot[cols] / base - 1) * 100

    fig, ax = plt.subplots(figsize=(14, 6))
    for div in pct.columns:
        ax.plot(
            pct.index, pct[div],
            label=div,
            color=COLORS.get(div, "#333333"),
            linewidth=1.8,
        )
    ax.axhline(0, color="black", linewidth=0.8, linestyle="--", alpha=0.5)
    _fmt_xaxis(ax)
    ax.set_title(
        "Crecimiento porcentual acumulado de programas activos por División\n"
        "(base = primera fecha disponible)",
        fontsize=12, fontweight="bold",
    )
    ax.set_xlabel("Fecha")
    ax.set_ylabel("Variación acumulada (%)")
    ax.yaxis.set_major_formatter(ticker.PercentFormatter())
    ax.legend(loc="upper left", fontsize=8, framealpha=0.8)
    ax.grid(axis="y", alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    today_str = datetime.today().strftime("%d/%m/%Y")
    print(f"[{today_str}] Iniciando análisis histórico pregrado...")

    cat   = load_categorizacion()
    pivot = build_time_series(cat)
    print(
        f"  Snapshots cargados: {len(pivot)}"
        f"  |  Periodo: {pivot.index[0].date()} -> {pivot.index[-1].date()}"
    )

    chart1 = os.path.join(OUT_DIR, "historico_evolucion_divisiones.png")
    chart2 = os.path.join(OUT_DIR, "historico_variacion_neta.png")
    chart3 = os.path.join(OUT_DIR, "historico_crecimiento_pct.png")

    for path in (chart1, chart2, chart3):
        if os.path.exists(path):
            os.remove(path)

    chart_evolucion(pivot,       chart1)
    chart_variacion_neta(pivot,  chart2)
    chart_crecimiento_pct(pivot, chart3)
    print("  Gráficos generados.")
    print("  Listo.")


if __name__ == "__main__":
    main()
