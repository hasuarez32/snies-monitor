"""
analisis_historico_pregrado.py
-------------------------------
Genera gráficos de barras agrupadas Nuevos vs Inactivos por División Uninorte
a partir de los archivos acumulados en data/novedades/.

Ejecución standalone:
  python analisis_historico_pregrado.py

También puede ser importado desde run_snies.py:
  from analisis_historico_pregrado import generar_graficos
"""

import os
import warnings
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

warnings.filterwarnings("ignore")

BASE          = os.path.dirname(os.path.abspath(__file__))
NOVEDADES_DIR = os.path.join(BASE, "data", "novedades")

DIV_COL = "DIVISIÓN UNINORTE"

COLOR_NUEVOS    = "#2ca02c"
COLOR_INACTIVOS = "#d62728"


def _conteo_por_division(path: str) -> pd.Series:
    if not os.path.exists(path):
        return pd.Series(dtype=int)
    df = pd.read_excel(path)
    col = next((c for c in df.columns if "DIVIS" in c.upper() and "UNINORTE" in c.upper()), None)
    if col is None:
        return pd.Series(dtype=int)
    return df[col].value_counts()


def _chart_nuevos_vs_inactivos(conteos: pd.DataFrame, sfx: str, out_path: str) -> None:
    """Barras agrupadas horizontales: Nuevos vs Inactivos por División."""
    n      = len(conteos)
    height = 0.35

    fig, ax = plt.subplots(figsize=(12, max(5, n * 0.7)))

    y = range(n)
    bars_n = ax.barh(
        [i + height / 2 for i in y],
        conteos["Nuevos"],
        height=height,
        color=COLOR_NUEVOS,
        label="Nuevos",
    )
    bars_i = ax.barh(
        [i - height / 2 for i in y],
        conteos["Inactivos"],
        height=height,
        color=COLOR_INACTIVOS,
        label="Inactivos",
    )

    ax.bar_label(bars_n, padding=3, fontsize=8)
    ax.bar_label(bars_i, padding=3, fontsize=8)

    ax.set_yticks(list(y))
    ax.set_yticklabels(conteos.index, fontsize=9)
    ax.set_xlabel("Número de programas")
    ax.set_title(
        f"Nuevos vs Inactivos por División Uninorte — {sfx.capitalize()}\n"
        "(acumulado histórico de detecciones)",
        fontsize=12,
        fontweight="bold",
    )
    ax.legend()
    ax.grid(axis="x", alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_path, dpi=150)
    plt.close(fig)


def generar_graficos() -> list:
    """
    Genera un gráfico por nivel (pregrado / posgrado).
    Devuelve la lista de rutas de los PNG generados.
    """
    os.makedirs(NOVEDADES_DIR, exist_ok=True)
    generados = []

    for sfx in ("pregrado", "posgrado"):
        nuevos_c    = _conteo_por_division(
            os.path.join(NOVEDADES_DIR, f"Nuevos_{sfx}.xlsx")
        ).rename("Nuevos")
        inactivos_c = _conteo_por_division(
            os.path.join(NOVEDADES_DIR, f"Inactivos_{sfx}.xlsx")
        ).rename("Inactivos")

        conteos = (
            pd.concat([nuevos_c, inactivos_c], axis=1)
            .fillna(0)
            .astype(int)
            .sort_values("Nuevos", ascending=True)
        )

        if conteos.empty or conteos[["Nuevos", "Inactivos"]].sum().sum() == 0:
            print(f"  [{sfx}] Sin datos suficientes, se omite el gráfico.")
            continue

        out_path = os.path.join(NOVEDADES_DIR, f"grafico_novedades_{sfx}.png")
        if os.path.exists(out_path):
            os.remove(out_path)

        _chart_nuevos_vs_inactivos(conteos, sfx, out_path)
        generados.append(out_path)
        print(f"  [{sfx}] Gráfico guardado: {out_path}")

    return generados


def main() -> None:
    print("Generando gráficos de novedades SNIES...")
    generados = generar_graficos()
    print(f"  {len(generados)} gráfico(s) generado(s). Listo.")


if __name__ == "__main__":
    main()
