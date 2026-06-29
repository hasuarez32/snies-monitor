"""
docs/generar_dashboard.py
Genera docs/index.html y las páginas de detalle (nuevos/inactivos/modificados.html).
Se ejecuta en CI justo después del pipeline de descarga/comparación.

Uso:
    python docs/generar_dashboard.py
"""
import json
import re
import unicodedata
import warnings
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

warnings.filterwarnings("ignore", category=UserWarning, module="openpyxl")

ROOT          = Path(__file__).parent.parent
PROGRAMAS_DIR = ROOT / "Programas"
NOVEDADES_DIR = ROOT / "data" / "novedades"
DOCS_DIR      = Path(__file__).parent

_PROG_RE = re.compile(r"^Programas (\d{2}-\d{2}-\d{2})(?:__\d{6})?\.xlsx$")

# ── Column sets ───────────────────────────────────────────────────────────────

COLS_NOVEDAD = [
    "FECHA_OBTENCION", "CÓDIGO_SNIES_DEL_PROGRAMA", "NOMBRE_DEL_PROGRAMA",
    "NOMBRE_INSTITUCIÓN", "SECTOR", "MODALIDAD", "DEPARTAMENTO_OFERTA_PROGRAMA",
    "DIVISIÓN UNINORTE", "NÚMERO_PERIODOS_DE_DURACIÓN",
    "CINE_F_2013_AC_CAMPO_ESPECÍFIC",
]
COLS_SNAPSHOT = [
    "CÓDIGO_SNIES_DEL_PROGRAMA", "NOMBRE_DEL_PROGRAMA", "NOMBRE_INSTITUCIÓN",
    "SECTOR", "MODALIDAD", "DEPARTAMENTO_OFERTA_PROGRAMA",
    "NÚMERO_PERIODOS_DE_DURACIÓN", "PERIODICIDAD",
]
COLS_MOD = COLS_NOVEDAD + ["QUE_CAMBIO"]

COLS_DETAIL = [
    "FECHA_OBTENCION", "CÓDIGO_SNIES_DEL_PROGRAMA", "NOMBRE_DEL_PROGRAMA",
    "NOMBRE_INSTITUCIÓN", "SECTOR", "MODALIDAD", "DEPARTAMENTO_OFERTA_PROGRAMA",
    "MUNICIPIO_OFERTA_PROGRAMA", "NÚMERO_CRÉDITOS", "COSTO_MATRÍCULA_ESTUD_NUEVOS",
    "PERIODICIDAD", "FECHA_DE_REGISTRO_EN_SNIES", "DIVISIÓN UNINORTE",
    "CINE_F_2013_AC_CAMPO_ESPECÍFIC", "NÚMERO_PERIODOS_DE_DURACIÓN",
]
COLS_MOD_DETAIL = COLS_DETAIL + ["QUE_CAMBIO", "NÚMERO_CRÉDITOS_ANTERIOR"]

# ── Detail page metadata ──────────────────────────────────────────────────────

DETAIL_CFGS = {
    "nuevos": {
        "tipo": "nuevos", "title": "Programas Nuevos", "emoji": "✅",
        "color": "#fcc10e", "colorAlpha": "rgba(252,193,14,0.08)",
        "cols": COLS_DETAIL,
    },
    "inactivos": {
        "tipo": "inactivos", "title": "Programas Inactivos", "emoji": "❌",
        "color": "#ae1e22", "colorAlpha": "rgba(174,30,34,0.08)",
        "cols": COLS_DETAIL,
    },
    "modificados": {
        "tipo": "modificados", "title": "Programas Modificados", "emoji": "⚠️",
        "color": "#bd900b", "colorAlpha": "rgba(189,144,11,0.08)",
        "cols": COLS_MOD_DETAIL,
    },
}

HDR_GRAD = {
    "nuevos":      "linear-gradient(135deg,#15284b,#fcc10e)",
    "inactivos":   "linear-gradient(135deg,#7a1518,#ae1e22)",
    "modificados": "linear-gradient(135deg,#15284b,#bd900b)",
}

EXTRA_LINK = {
    "nuevos": "",
    "inactivos": "",
    "modificados": '<a href="modificados_creditos.html" class="back-btn">📐 Análisis de Créditos →</a>'
                   '<a href="modificados_costos.html" class="back-btn">💰 Análisis de Costos →</a>',
}

XFILTER = {
    "nuevos":
        '<select id="f-modalidad" class="f-sel" onchange="applyFilters()">'
        '<option value="">Todas las modalidades</option></select>',
    "inactivos":
        '<select id="f-modalidad" class="f-sel" onchange="applyFilters()">'
        '<option value="">Todas las modalidades</option></select>',
    "modificados":
        '<select id="f-tipo-cambio" class="f-sel" onchange="applyFilters()">'
        '<option value="">Todos los cambios</option></select>',
}

FDIV_SELECT = {
    "nuevos":
        '<select id="f-cine" class="f-sel" onchange="applyFilters()">'
        '<option value="">Todos los campos CINE</option></select>',
    "inactivos":
        '<select id="f-cine" class="f-sel" onchange="applyFilters()">'
        '<option value="">Todos los campos CINE</option></select>',
    "modificados":
        '<select id="f-division" class="f-sel" onchange="applyFilters()">'
        '<option value="">Todas las divisiones</option></select>',
}

CHARTS_HTML = {
    "nuevos": """
<div class="g2">
  <div class="card"><div class="ct">Por sector</div><div id="ch-sector" style="height:260px"></div></div>
  <div class="card"><div class="ct">Top 10 instituciones</div><div id="ch-instituciones" style="height:260px"></div></div>
</div>
<div class="g2">
  <div class="card"><div class="ct">Por Division Uninorte</div><div id="ch-division" style="height:260px"></div></div>
  <div class="card"><div class="ct">Por modalidad</div><div id="ch-modalidad" style="height:260px"></div></div>
</div>
<div class="card"><div class="ct">Top 15 departamentos de oferta</div><div id="ch-depto" style="height:310px"></div></div>
<div class="card">
  <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:.75rem;flex-wrap:wrap;gap:.5rem">
    <div class="ct" style="margin-bottom:0">Acumulado por campo CINE semestral (fecha de registro SNIES)</div>
    <div style="display:flex;gap:.5rem;align-items:center">
      <input id="cine-search" list="cine-list" placeholder="Buscar campo CINE…"
             style="padding:.35rem .7rem;border:1px solid #cbd5e1;border-radius:.4rem;font-size:.78rem;width:260px;outline:none"
             onkeydown="if(event.key==='Enter')cineAdd()">
      <datalist id="cine-list"></datalist>
      <button onclick="cineAdd()"
              style="padding:.35rem .8rem;background:#2d5b9e;color:#fff;border:none;border-radius:.4rem;font-size:.78rem;cursor:pointer;white-space:nowrap">+ Agregar</button>
    </div>
  </div>
  <div id="cine-tags" style="display:flex;flex-wrap:wrap;gap:.35rem;margin-bottom:.6rem;min-height:1.4rem"></div>
  <div id="ch-timeline" style="height:300px"></div>
</div>
<div class="card"><div class="ct">Distribución por duración (periodos requeridos)</div><div id="ch-periodos" style="height:260px"></div></div>
""",
    "inactivos": """
<div class="g2">
  <div class="card"><div class="ct">Por sector</div><div id="ch-sector" style="height:260px"></div></div>
  <div class="card"><div class="ct">Top 10 instituciones</div><div id="ch-instituciones" style="height:260px"></div></div>
</div>
<div class="g2">
  <div class="card"><div class="ct">Por Division Uninorte</div><div id="ch-division" style="height:260px"></div></div>
  <div class="card"><div class="ct">Por modalidad</div><div id="ch-modalidad" style="height:260px"></div></div>
</div>
<div class="card"><div class="ct">Top 15 departamentos de oferta</div><div id="ch-depto" style="height:310px"></div></div>
<div class="card">
  <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:.75rem;flex-wrap:wrap;gap:.5rem">
    <div class="ct" style="margin-bottom:0">Acumulado por campo CINE semestral (fecha de registro SNIES)</div>
    <div style="display:flex;gap:.5rem;align-items:center">
      <input id="cine-search" list="cine-list" placeholder="Buscar campo CINE…"
             style="padding:.35rem .7rem;border:1px solid #cbd5e1;border-radius:.4rem;font-size:.78rem;width:260px;outline:none"
             onkeydown="if(event.key==='Enter')cineAdd()">
      <datalist id="cine-list"></datalist>
      <button onclick="cineAdd()"
              style="padding:.35rem .8rem;background:#2d5b9e;color:#fff;border:none;border-radius:.4rem;font-size:.78rem;cursor:pointer;white-space:nowrap">+ Agregar</button>
    </div>
  </div>
  <div id="cine-tags" style="display:flex;flex-wrap:wrap;gap:.35rem;margin-bottom:.6rem;min-height:1.4rem"></div>
  <div id="ch-timeline" style="height:300px"></div>
</div>
<div class="card"><div class="ct">Distribución por duración (periodos requeridos)</div><div id="ch-periodos" style="height:260px"></div></div>
""",
    "modificados": """
<div class="card"><div class="ct">Tipo de cambio detectado</div><div id="ch-tipo-cambio" style="height:260px"></div></div>
<div class="g2">
  <div class="card"><div class="ct">Top 10 instituciones modificadas</div><div id="ch-instituciones" style="height:260px"></div></div>
  <div class="card"><div class="ct">Por Division Uninorte</div><div id="ch-division" style="height:260px"></div></div>
</div>
<div class="g2">
  <div class="card"><div class="ct">Creditos: antes vs despues</div><div id="ch-scatter" style="height:300px"></div></div>
  <div class="card"><div class="ct">Por sector</div><div id="ch-sector" style="height:300px"></div></div>
</div>
<div class="card"><div class="ct">Top 15 departamentos afectados</div><div id="ch-depto" style="height:310px"></div></div>
<div class="card"><div class="ct">Modificaciones por periodo de run</div><div id="ch-timeline" style="height:200px"></div></div>
""",
}


# ── helpers ───────────────────────────────────────────────────────────────────

def _read_xl(path, **kw):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return pd.read_excel(path, **kw)


def _distribucion(df, campo, top_n=15):
    if df is None or df.empty or campo not in df.columns:
        return []
    counts = df[campo].value_counts().head(top_n)
    return [{"label": str(k), "value": int(v)} for k, v in counts.items()]


def _to_records(df, cols):
    if df is None or df.empty:
        return []
    if "FECHA_OBTENCION" in df.columns:
        df = df.copy()
        df["_s"] = pd.to_datetime(df["FECHA_OBTENCION"], errors="coerce")
        df = df.sort_values("_s", ascending=False).drop(columns=["_s"])
    cols_ok = [c for c in cols if c in df.columns]
    sub = df[cols_ok].copy()
    for c in sub.columns:
        sub[c] = sub[c].fillna("").astype(str)
    return sub.to_dict("records")


def _count_last_run(df):
    if df is None or df.empty:
        return 0
    if "FECHA_OBTENCION" in df.columns:
        last = df["FECHA_OBTENCION"].max()
        return int((df["FECHA_OBTENCION"] == last).sum())
    return len(df)


def _fill_num(df, base, sources):
    """Rebuild `base` by overlaying `sources` in priority order (sources[0]
    wins over sources[1], etc). The pre-existing `base` column, if any, is
    used only as the LAST-resort fallback: for rows accumulated across
    schema eras it can hold a stale/unrelated value (e.g. leftover from a
    column that misaligned during pd.concat) while the suffixed snapshot
    columns are the ones that actually describe the detected change."""
    chain = list(sources) + ([base] if base in df.columns else [])
    result = pd.Series(np.nan, index=df.index)
    for src in reversed(chain):
        if src not in df.columns:
            continue
        col = pd.to_numeric(df[src], errors="coerce")
        result = result.where(col.isna(), col)
    df[base] = result


def _fill_text(df, base, sources):
    """Same priority-overlay semantics as _fill_num, for text columns
    ('' and 'nan' count as missing too)."""
    chain = list(sources) + ([base] if base in df.columns else [])
    result = pd.Series([np.nan] * len(df), index=df.index, dtype="object")
    for src in reversed(chain):
        if src not in df.columns:
            continue
        col = df[src]
        missing = col.isna() | col.astype(str).str.strip().isin(["", "nan"])
        result = result.where(missing, col)
    df[base] = result


_FECHA_RE_ISO = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _normalizar_fecha_obtencion(df: pd.DataFrame) -> pd.DataFrame:
    """FECHA_OBTENCION quedo mezclada entre 'DD/MM/YYYY' (formato original) y
    'YYYY-MM-DD' (formato que produjo run_snies.py en otra epoca). El JS del
    dashboard solo sabe parsear 'DD/MM/YYYY', asi que se unifica aqui."""
    if df is None or df.empty or "FECHA_OBTENCION" not in df.columns:
        return df
    df = df.copy()
    col = df["FECHA_OBTENCION"].astype(str).str.strip()
    es_iso = col.str.match(_FECHA_RE_ISO)
    fechas_iso = pd.to_datetime(col[es_iso], format="%Y-%m-%d", errors="coerce")
    col.loc[es_iso] = fechas_iso.dt.strftime("%d/%m/%Y")
    df["FECHA_OBTENCION"] = col
    return df


_DEPTO_ALIAS = {
    # variantes de ortografia/puntuacion que han aparecido en distintas
    # descargas del SNIES y que deben tratarse como un solo departamento.
    "Bogotá D.C.": "Bogotá, D.C.",
}


def _normalizar_depto(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty or "DEPARTAMENTO_OFERTA_PROGRAMA" not in df.columns:
        return df
    df = df.copy()
    df["DEPARTAMENTO_OFERTA_PROGRAMA"] = df["DEPARTAMENTO_OFERTA_PROGRAMA"].replace(_DEPTO_ALIAS)
    return df


def _normalizar_modificados(df: pd.DataFrame) -> pd.DataFrame:
    """Rellena columnas base vacías desde variantes _NUEVO para filas acumuladas
    antes de que detectar_novedades renombrara los sufijos del merge."""
    if df is None or df.empty:
        return df
    df = df.copy()
    df = _normalizar_fecha_obtencion(df)
    df = _normalizar_depto(df)

    fallbacks = {
        "NOMBRE_DEL_PROGRAMA":          "NOMBRE_DEL_PROGRAMA_NUEVO",
        "NOMBRE_INSTITUCIÓN":           "NOMBRE_INSTITUCIÓN_NUEVO",
        "SECTOR":                       "SECTOR_NUEVO",
        "MODALIDAD":                    "MODALIDAD_NUEVO",
        "DEPARTAMENTO_OFERTA_PROGRAMA": "DEPARTAMENTO_OFERTA_PROGRAMA_NUEVO",
        "MUNICIPIO_OFERTA_PROGRAMA":    "MUNICIPIO_OFERTA_PROGRAMA_NUEVO",
    }
    for base, nuevo in fallbacks.items():
        if nuevo not in df.columns:
            continue
        if base not in df.columns:
            df[base] = df[nuevo]
        else:
            mask = df[base].isna() | (df[base].astype(str).str.strip() == "")
            df.loc[mask, base] = df.loc[mask, nuevo]

    # Valor "actual" de cada campo vigilado: coalesce desde la variante _NUEVO.
    _fill_text(df, "MODALIDAD", ("MODALIDAD_NUEVO",))
    _fill_text(df, "MUNICIPIO_OFERTA_PROGRAMA", ("MUNICIPIO_OFERTA_PROGRAMA_NUEVO",))
    _fill_num(df, "NÚMERO_CRÉDITOS",
              ("NÚMERO_CRÉDITOS_NUEVO", "NÚMERO_CRÉDITOS_NUEVOS"))
    _fill_num(df, "COSTO_MATRÍCULA_ESTUD_NUEVOS",
              ("COSTO_MATRÍCULA_ESTUD_NUEVOS_NUEVO",))
    _fill_num(df, "NÚMERO_PERIODOS_DE_DURACIÓN",
              ("NÚMERO_PERIODOS_DE_DURACIÓN_NUEVO",))

    # Valor "anterior" de cada campo vigilado: coalesce desde TODAS las variantes
    # de sufijo que ha tenido el pipeline a lo largo del tiempo (_ANTIGUO de una
    # epoca, _ANTERIOR/_ANTERIORES de otra). _fill_num/_fill_text ya no se
    # detienen en la primera fuente que encuentran, asi que cubren ambas.
    _fill_text(df, "MODALIDAD_ANTERIOR", ("MODALIDAD_ANTIGUO", "MODALIDAD_ANTERIOR"))
    _fill_text(df, "MUNICIPIO_OFERTA_PROGRAMA_ANTERIOR",
               ("MUNICIPIO_OFERTA_PROGRAMA_ANTIGUO", "MUNICIPIO_OFERTA_PROGRAMA_ANTERIOR"))
    _fill_num(df, "NÚMERO_CRÉDITOS_ANTERIOR",
              ("NÚMERO_CRÉDITOS_ANTIGUO", "NÚMERO_CRÉDITOS_ANTERIORES", "NÚMERO_CRÉDITOS_ANTERIOR"))
    _fill_num(df, "COSTO_MATRÍCULA_ESTUD_NUEVOS_ANTERIOR",
              ("COSTO_MATRÍCULA_ESTUD_NUEVOS_ANTIGUO", "COSTO_MATRÍCULA_ESTUD_NUEVOS_ANTERIOR"))
    _fill_num(df, "NÚMERO_PERIODOS_DE_DURACIÓN_ANTERIOR",
              ("NÚMERO_PERIODOS_DE_DURACIÓN_ANTIGUO", "NÚMERO_PERIODOS_DE_DURACIÓN_ANTERIOR"))

    vigilar = [
        ("MODALIDAD",                    "MODALIDAD"),
        ("NÚMERO_CRÉDITOS",              "NÚMERO_CRÉDITOS"),
        ("COSTO_MATRÍCULA_ESTUD_NUEVOS", "COSTO_MATRÍCULA_ESTUD_NUEVOS"),
        ("MUNICIPIO_OFERTA_PROGRAMA",    "MUNICIPIO_OFERTA_PROGRAMA"),
    ]
    if "QUE_CAMBIO" not in df.columns:
        df["QUE_CAMBIO"] = ""

    empty = df["QUE_CAMBIO"].isna() | (df["QUE_CAMBIO"].astype(str).str.strip() == "")
    if empty.any():
        def _rebuild(row):
            parts = []
            for label, col in vigilar:
                a_col = f"{col}_ANTERIOR"
                if col in row.index and a_col in row.index:
                    vn, va = str(row[col]).strip(), str(row[a_col]).strip()
                    if vn != va and vn not in ("nan", "") and va not in ("nan", ""):
                        parts.append(f"{label}: {va} -> {vn}")
            return " | ".join(parts) if parts else ""
        df.loc[empty, "QUE_CAMBIO"] = df[empty].apply(_rebuild, axis=1)

    return df


# ── análisis de créditos (pagina dedicada modificados_creditos.html) ──────────

def _clean_json_scalar(v):
    """Convierte escalares numpy/NaN a tipos nativos de Python para json.dumps."""
    if isinstance(v, float) and np.isnan(v):
        return None
    if v is None:
        return None
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    if isinstance(v, np.bool_):
        return bool(v)
    if isinstance(v, np.integer):
        return int(v)
    if isinstance(v, np.floating):
        return float(v)
    return v


def calcular_analisis_creditos(mods_df: pd.DataFrame) -> dict:
    """Exporta, fila por fila, TODO Modificados con flags booleanos de co-cambio
    ya resueltos (cambia_credito/periodo/costo/modalidad/municipio: True/False/None
    si no hay dato comparable). La pagina dedicada hace los agregados (KPIs,
    rankings, histograma, co-cambios, scatter) en JS a partir de este 'universo',
    para que TODO -no solo la tabla- se recalcule cuando el usuario filtra por
    texto, sector o departamento."""
    if mods_df is None or mods_df.empty:
        return {"universo": []}

    df = mods_df.copy()

    def _num_pair(col):
        n = pd.to_numeric(df.get(col), errors="coerce")
        a = pd.to_numeric(df.get(f"{col}_ANTERIOR"), errors="coerce")
        return n, a

    def _flag_num(col):
        n, a = _num_pair(col)
        valido = n.notna() & a.notna()
        out = pd.Series(pd.NA, index=df.index, dtype="boolean")
        out[valido] = (n != a)[valido]
        return out

    def _flag_text(col):
        n, a = df.get(col), df.get(f"{col}_ANTERIOR")
        out = pd.Series(pd.NA, index=df.index, dtype="boolean")
        if n is None or a is None:
            return out
        valido = n.notna() & a.notna() & (n.astype(str).str.strip() != "") & (a.astype(str).str.strip() != "")
        cambia = n.astype(str).str.strip() != a.astype(str).str.strip()
        out[valido] = cambia[valido]
        return out

    cred_n, cred_a = _num_pair("NÚMERO_CRÉDITOS")
    cred_valido = cred_n.notna() & cred_a.notna()
    if not cred_valido.any():
        return {"universo": []}

    out = pd.DataFrame({
        "FECHA_OBTENCION":               df.get("FECHA_OBTENCION"),
        "CÓDIGO_SNIES_DEL_PROGRAMA":     df.get("CÓDIGO_SNIES_DEL_PROGRAMA"),
        "NOMBRE_DEL_PROGRAMA":           df.get("NOMBRE_DEL_PROGRAMA"),
        "NOMBRE_INSTITUCIÓN":            df.get("NOMBRE_INSTITUCIÓN"),
        "SECTOR":                        df.get("SECTOR"),
        "DEPARTAMENTO_OFERTA_PROGRAMA":  df.get("DEPARTAMENTO_OFERTA_PROGRAMA"),
        "DIVISIÓN UNINORTE":             df.get("DIVISIÓN UNINORTE"),
        "CINE_F_2013_AC_CAMPO_ESPECÍFIC": df.get("CINE_F_2013_AC_CAMPO_ESPECÍFIC"),
        "QUE_CAMBIO":                    df.get("QUE_CAMBIO"),
        "_cred_antes":    cred_a,
        "_cred_despues":  cred_n,
        "_delta":         cred_n - cred_a,
        "_cambia_credito": cred_n != cred_a,
        "_cambia_periodo":    _flag_num("NÚMERO_PERIODOS_DE_DURACIÓN"),
        "_cambia_costo":      _flag_num("COSTO_MATRÍCULA_ESTUD_NUEVOS"),
        "_cambia_modalidad":  _flag_text("MODALIDAD"),
        "_cambia_municipio":  _flag_text("MUNICIPIO_OFERTA_PROGRAMA"),
    })

    # El universo de esta pagina son los programas con par antes/despues de
    # creditos verificable (con o sin cambio real: el "sin cambio" es el grupo
    # de control para la tasa base de los otros campos).
    out = out[cred_valido].copy()
    out["QUE_CAMBIO"] = out["QUE_CAMBIO"].fillna("")
    for c in ("_cred_antes", "_cred_despues", "_delta"):
        out[c] = out[c].astype(int)

    records = out.to_dict("records")
    universo = [{k: _clean_json_scalar(v) for k, v in r.items()} for r in records]

    return {"universo": universo}


def calcular_analisis_costos(mods_df: pd.DataFrame) -> dict:
    """Mismo patron que calcular_analisis_creditos pero para costo de matricula.
    Se usa % de cambio (no el delta en pesos) como metrica principal porque el
    costo varia en ordenes de magnitud distintos entre programas (de ~200 mil a
    ~30 millones), asi que un delta absoluto no es comparable entre programas
    mientras que el % si lo es."""
    if mods_df is None or mods_df.empty:
        return {"universo": []}

    df = mods_df.copy()

    def _num_pair(col):
        n = pd.to_numeric(df.get(col), errors="coerce")
        a = pd.to_numeric(df.get(f"{col}_ANTERIOR"), errors="coerce")
        return n, a

    def _flag_num(col):
        n, a = _num_pair(col)
        valido = n.notna() & a.notna()
        out = pd.Series(pd.NA, index=df.index, dtype="boolean")
        out[valido] = (n != a)[valido]
        return out

    def _flag_text(col):
        n, a = df.get(col), df.get(f"{col}_ANTERIOR")
        out = pd.Series(pd.NA, index=df.index, dtype="boolean")
        if n is None or a is None:
            return out
        valido = n.notna() & a.notna() & (n.astype(str).str.strip() != "") & (a.astype(str).str.strip() != "")
        cambia = n.astype(str).str.strip() != a.astype(str).str.strip()
        out[valido] = cambia[valido]
        return out

    costo_n, costo_a = _num_pair("COSTO_MATRÍCULA_ESTUD_NUEVOS")
    costo_valido = costo_n.notna() & costo_a.notna() & (costo_a > 0)
    if not costo_valido.any():
        return {"universo": []}

    out = pd.DataFrame({
        "FECHA_OBTENCION":               df.get("FECHA_OBTENCION"),
        "CÓDIGO_SNIES_DEL_PROGRAMA":     df.get("CÓDIGO_SNIES_DEL_PROGRAMA"),
        "NOMBRE_DEL_PROGRAMA":           df.get("NOMBRE_DEL_PROGRAMA"),
        "NOMBRE_INSTITUCIÓN":            df.get("NOMBRE_INSTITUCIÓN"),
        "SECTOR":                        df.get("SECTOR"),
        "DEPARTAMENTO_OFERTA_PROGRAMA":  df.get("DEPARTAMENTO_OFERTA_PROGRAMA"),
        "DIVISIÓN UNINORTE":             df.get("DIVISIÓN UNINORTE"),
        "CINE_F_2013_AC_CAMPO_ESPECÍFIC": df.get("CINE_F_2013_AC_CAMPO_ESPECÍFIC"),
        "QUE_CAMBIO":                    df.get("QUE_CAMBIO"),
        "_costo_antes":    costo_a,
        "_costo_despues":  costo_n,
        "_delta":          costo_n - costo_a,
        "_delta_pct":      (costo_n - costo_a) / costo_a * 100,
        "_cambia_costo":   costo_n != costo_a,
        "_cambia_credito":    _flag_num("NÚMERO_CRÉDITOS"),
        "_cambia_periodo":    _flag_num("NÚMERO_PERIODOS_DE_DURACIÓN"),
        "_cambia_modalidad":  _flag_text("MODALIDAD"),
        "_cambia_municipio":  _flag_text("MUNICIPIO_OFERTA_PROGRAMA"),
    })

    # El universo de esta pagina son los programas con par antes/despues de
    # costo de matricula verificable (con o sin cambio real: el "sin cambio"
    # es el grupo de control para la tasa base de los otros campos).
    out = out[costo_valido].copy()
    out["QUE_CAMBIO"] = out["QUE_CAMBIO"].fillna("")
    for c in ("_costo_antes", "_costo_despues", "_delta"):
        out[c] = out[c].astype(int)
    out["_delta_pct"] = out["_delta_pct"].round(1)

    records = out.to_dict("records")
    universo = [{k: _clean_json_scalar(v) for k, v in r.items()} for r in records]

    return {"universo": universo}


# ── mapa coroplético ──────────────────────────────────────────────────────────

_DEPTO_MAP = {
    "Bogotá, D.C.": "SANTAFE DE BOGOTA D.C",
    "Archipiélago de San Andrés, Providencia y Santa Catalina":
        "ARCHIPIELAGO DE SAN ANDRES PROVIDENCIA Y SANTA CATALINA",
    "Nariño": "NARIÑO",
}

def _snies_to_geo(name: str) -> str:
    if name in _DEPTO_MAP:
        return _DEPTO_MAP[name]
    return (
        unicodedata.normalize("NFD", name)
        .encode("ascii", "ignore")
        .decode("ascii")
        .upper()
    )

def _datos_mapa(df: pd.DataFrame) -> list:
    col = "DEPARTAMENTO_OFERTA_PROGRAMA"
    if df is None or df.empty or col not in df.columns:
        return []
    counts = df[col].value_counts()
    total = int(counts.sum())
    return [
        {
            "depto": _snies_to_geo(str(depto)),
            "total": int(cnt),
            "pct":   round(100 * int(cnt) / total, 1) if total else 0,
        }
        for depto, cnt in counts.items()
    ]


# ── data loading ──────────────────────────────────────────────────────────────

def leer_historico():
    puntos = []
    for f in PROGRAMAS_DIR.glob("Programas *.xlsx"):
        m = _PROG_RE.match(f.name)
        if not m:
            continue
        try:
            fecha = datetime.strptime(m.group(1), "%d-%m-%y").date()
        except ValueError:
            continue
        try:
            df = _read_xl(f, sheet_name="Programas",
                          usecols=["CÓDIGO_SNIES_DEL_PROGRAMA"])
            if len(df) > 2:
                df = df.iloc[:-2]
            df = df.dropna(subset=["CÓDIGO_SNIES_DEL_PROGRAMA"])
            puntos.append({"fecha": fecha.isoformat(), "total": len(df)})
        except Exception as e:
            print(f"  saltando {f.name}: {e}")
    puntos.sort(key=lambda x: x["fecha"])
    print(f"  historico: {len(puntos)} snapshots")
    return puntos


def leer_novedades(nombre):
    path = NOVEDADES_DIR / nombre
    if not path.exists():
        print(f"  {nombre}: no existe aun")
        return pd.DataFrame()
    try:
        df = _read_xl(path)
        print(f"  {nombre}: {len(df)} filas")
        return df
    except Exception as e:
        print(f"  error leyendo {nombre}: {e}")
        return pd.DataFrame()


def leer_snapshot_actual(historico):
    if not historico:
        return pd.DataFrame()
    ultima_fecha = historico[-1]["fecha"]
    for f in PROGRAMAS_DIR.glob("Programas *.xlsx"):
        m = _PROG_RE.match(f.name)
        if not m:
            continue
        try:
            if datetime.strptime(m.group(1), "%d-%m-%y").date().isoformat() == ultima_fecha:
                df = _read_xl(f, sheet_name="Programas")
                return df.iloc[:-2] if len(df) > 2 else df
        except Exception:
            continue
    return pd.DataFrame()


# ── main ─────────────────────────────────────────────────────────────────────

def main():
    print("Generando dashboard SNIES...")

    historico    = leer_historico()
    nuevos_df    = _normalizar_depto(_normalizar_fecha_obtencion(leer_novedades("Nuevos_pregrado.xlsx")))
    inactivos_df = _normalizar_depto(_normalizar_fecha_obtencion(leer_novedades("Inactivos_pregrado.xlsx")))
    mods_df      = leer_novedades("Modificados_pregrado.xlsx")
    snapshot_df  = leer_snapshot_actual(historico)

    mods_df = _normalizar_modificados(mods_df)

    kpis = {
        "total_activos":    historico[-1]["total"] if historico else 0,
        "nuevos_ultimo":    _count_last_run(nuevos_df),
        "inactivos_ultimo": _count_last_run(inactivos_df),
        "mods_ultimo":      _count_last_run(mods_df),
        "nuevos_total":     len(nuevos_df),
        "inactivos_total":  len(inactivos_df),
        "mods_total":       len(mods_df),
    }

    col_per  = next((c for c in snapshot_df.columns if "PERIODO" in c.upper() and "DURACI" in c.upper()), None)
    col_peri = next((c for c in snapshot_df.columns if c.upper() == "PERIODICIDAD"), None)
    if col_per and not snapshot_df.empty:
        df_p = snapshot_df[[col_per] + ([col_peri] if col_peri else [])].copy()
        df_p[col_per] = pd.to_numeric(df_p[col_per], errors="coerce")
        df_p = df_p.dropna(subset=[col_per])
        df_p[col_per] = df_p[col_per].apply(lambda x: int(round(x)))
        if col_peri:
            df_p[col_peri] = df_p[col_peri].fillna("Sin definir")
            pivot = df_p.groupby([col_per, col_peri]).size().unstack(fill_value=0)
            all_labels = sorted(pivot.index.tolist())
            all_peris  = pivot.sum().sort_values(ascending=False).index.tolist()
            por_periodos_stacked = {
                "labels": all_labels,
                "series": [
                    {"name": p, "values": [int(pivot.at[l, p]) if p in pivot.columns and l in pivot.index else 0
                                           for l in all_labels]}
                    for p in all_peris if pivot[p].sum() > 0
                ],
            }
        else:
            cnts = df_p[col_per].value_counts().sort_index()
            all_labels = sorted(cnts.index.tolist())
            por_periodos_stacked = {"labels": all_labels,
                                    "series": [{"name": "Sin datos", "values": [int(cnts.get(l, 0)) for l in all_labels]}]}
    else:
        por_periodos_stacked = {"labels": [], "series": []}

    data = {
        "ultima_actualizacion": historico[-1]["fecha"] if historico else "N/A",
        "historico":     historico,
        "kpis":          kpis,
        "por_sector":     _distribucion(snapshot_df, "SECTOR"),
        "por_depto":      _distribucion(snapshot_df, "DEPARTAMENTO_OFERTA_PROGRAMA"),
        "por_modalidad":  _distribucion(snapshot_df, "MODALIDAD"),
        "por_periodos_stacked": por_periodos_stacked,
        "por_depto_mapa": _datos_mapa(snapshot_df),
        "snapshot":       _to_records(snapshot_df, COLS_SNAPSHOT),
        "nuevos":        _to_records(nuevos_df,    COLS_NOVEDAD),
        "inactivos":     _to_records(inactivos_df, COLS_NOVEDAD),
        "modificados":   _to_records(mods_df,      COLS_MOD),
        "n_nuevos":      len(nuevos_df),
        "n_inactivos":   len(inactivos_df),
        "n_modificados": len(mods_df),
    }

    DOCS_DIR.mkdir(exist_ok=True)

    json_path = DOCS_DIR / "dashboard_data.json"
    json_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"  JSON: {json_path}")

    html_path = DOCS_DIR / "index.html"
    html_path.write_text(generar_html(data), encoding="utf-8")
    print(f"  HTML: {html_path}")

    for tipo, df_type, cols in [
        ("nuevos",     nuevos_df,    COLS_DETAIL),
        ("inactivos",  inactivos_df, COLS_DETAIL),
        ("modificados", mods_df,     COLS_MOD_DETAIL),
    ]:
        rows_js = json.dumps(
            _to_records(df_type, cols), ensure_ascii=False
        ).replace("</", "<\\/")
        cfg_js = json.dumps(
            DETAIL_CFGS[tipo], ensure_ascii=False
        ).replace("</", "<\\/")
        html = (
            DETAIL_TEMPLATE
            .replace("__DATA__",    rows_js)
            .replace("__CONFIG__",  cfg_js)
            .replace("__CHARTS__",  CHARTS_HTML[tipo])
            .replace("__XFILTER__",      XFILTER[tipo])
            .replace("__FDIV_SELECT__",  FDIV_SELECT[tipo])
            .replace("__TITLE__",        DETAIL_CFGS[tipo]["title"])
            .replace("__EMOJI__",   DETAIL_CFGS[tipo]["emoji"])
            .replace("__HDRGRD__",  HDR_GRAD[tipo])
            .replace("__EXTRA_LINK__", EXTRA_LINK[tipo])
        )
        p = DOCS_DIR / f"{tipo}.html"
        p.write_text(html, encoding="utf-8")
        print(f"  HTML: {p}")

    creditos_data = calcular_analisis_creditos(mods_df)
    creditos_js = json.dumps(creditos_data, ensure_ascii=False).replace("</", "<\\/")
    creditos_html = CREDITOS_TEMPLATE.replace("__DATA__", creditos_js)
    creditos_path = DOCS_DIR / "modificados_creditos.html"
    creditos_path.write_text(creditos_html, encoding="utf-8")
    print(f"  HTML: {creditos_path}")

    costos_data = calcular_analisis_costos(mods_df)
    costos_js = json.dumps(costos_data, ensure_ascii=False).replace("</", "<\\/")
    costos_html = COSTOS_TEMPLATE.replace("__DATA__", costos_js)
    costos_path = DOCS_DIR / "modificados_costos.html"
    costos_path.write_text(costos_html, encoding="utf-8")
    print(f"  HTML: {costos_path}")

    print("Dashboard generado OK")


def generar_html(data: dict) -> str:
    data_js = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    return HTML_TEMPLATE.replace("__DATA__", data_js)


# ── index.html template ───────────────────────────────────────────────────────

HTML_TEMPLATE = r"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>SNIES Monitor · Uninorte</title>
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js" charset="utf-8"></script>
<style>
:root {
  --bg:#f1f5f9; --surface:#fff; --hdr1:#15284b; --hdr2:#2d5b9e;
  --text:#0f172a; --muted:#64748b; --border:#e2e8f0;
  --blue:#2d5b9e; --green:#fcc10e; --red:#ae1e22; --amber:#bd900b;
  --radius:0.75rem;
}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Segoe UI',system-ui,sans-serif;background:var(--bg);color:var(--text);font-size:14px}
header{background:linear-gradient(135deg,var(--hdr1),var(--hdr2));color:#fff;
  padding:1.25rem 2rem;display:flex;justify-content:space-between;align-items:center}
header h1{font-size:1.35rem;font-weight:700;letter-spacing:-.01em}
header .sub{font-size:.8rem;opacity:.75;margin-top:.2rem}
.badge-update{background:rgba(255,255,255,.15);border:1px solid rgba(255,255,255,.3);
  padding:.5rem 1rem;border-radius:2rem;font-size:.75rem;text-align:right;white-space:nowrap}
.badge-update strong{display:block;font-size:.9rem}
main{max-width:1380px;margin:0 auto;padding:1.5rem 2rem}
section{margin-bottom:1.5rem}
.kpi-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:1rem}
.kpi{background:var(--surface);border-radius:var(--radius);padding:1.25rem 1.5rem;
  box-shadow:0 1px 3px rgba(0,0,0,.07);border-left:4px solid var(--blue)}
.kpi.g{border-left-color:var(--green)}.kpi.r{border-left-color:var(--red)}.kpi.a{border-left-color:var(--amber)}
.kpi.link{cursor:pointer;transition:transform .15s,box-shadow .15s}
.kpi.link:hover{transform:translateY(-3px);box-shadow:0 6px 16px rgba(0,0,0,.13)}
.kpi-label{font-size:.7rem;text-transform:uppercase;letter-spacing:.05em;color:var(--muted);margin-bottom:.4rem}
.kpi-val{font-size:2rem;font-weight:700;line-height:1}
.kpi-sub{font-size:.72rem;color:var(--muted);margin-top:.35rem}
.kpi-hint{font-size:.65rem;color:var(--blue);margin-top:.3rem;opacity:.8}
.card{background:var(--surface);border-radius:var(--radius);padding:1.25rem;
  box-shadow:0 1px 3px rgba(0,0,0,.07)}
.card-title{font-size:.7rem;font-weight:600;text-transform:uppercase;
  letter-spacing:.06em;color:var(--muted);margin-bottom:.9rem}
.chart-2col{display:grid;grid-template-columns:1fr 2fr;gap:1rem}
.tab-nav{display:flex;border-bottom:1px solid var(--border);padding:0 1.5rem;background:var(--surface);
  border-radius:var(--radius) var(--radius) 0 0}
.tab-btn{padding:.85rem 1.25rem;border:none;background:none;cursor:pointer;font-size:.8rem;
  font-weight:500;color:var(--muted);border-bottom:2px solid transparent;transition:.15s}
.tab-btn.on{color:var(--blue);border-bottom-color:var(--blue)}
.tab-btn .n{font-size:.68rem;background:var(--bg);padding:.1rem .4rem;border-radius:1rem;margin-left:.35rem}
.tab-btn.on .n{background:var(--blue);color:#fff}
.tab-pane{display:none;padding:1.25rem 1.5rem;background:var(--surface);
  border-radius:0 0 var(--radius) var(--radius)}
.tab-pane.on{display:block}
.search{width:100%;max-width:380px;padding:.55rem .9rem;border:1px solid var(--border);
  border-radius:.5rem;font-size:.8rem;margin-bottom:1rem;outline:none}
.search:focus{border-color:var(--blue)}
.f-row{display:flex;gap:.45rem;flex-wrap:wrap;align-items:center;margin-bottom:.9rem}
.f-input{flex:1;min-width:170px;max-width:300px;padding:.5rem .8rem;border:1px solid var(--border);
  border-radius:.4rem;font-size:.8rem;outline:none}
.f-input:focus{border-color:var(--blue)}
.f-sel{padding:.45rem .6rem;border:1px solid var(--border);border-radius:.4rem;
  font-size:.77rem;background:var(--surface);outline:none;cursor:pointer;max-width:175px}
.f-sel:focus{border-color:var(--blue)}
.f-btn{padding:.45rem .85rem;border:1px solid var(--border);border-radius:.4rem;
  font-size:.77rem;background:var(--surface);cursor:pointer;color:var(--muted);white-space:nowrap}
.f-btn:hover{background:var(--bg)}
.ac-wrap{position:relative;flex:1;min-width:170px;max-width:300px}
.ac-menu{position:absolute;top:calc(100% + 2px);left:0;right:0;z-index:300;
  background:var(--surface);border:1px solid var(--border);border-radius:.4rem;
  box-shadow:0 8px 20px rgba(0,0,0,.14);max-height:260px;overflow-y:auto;display:none}
.ac-menu.show{display:block}
.ac-item{padding:.45rem .75rem;font-size:.78rem;cursor:pointer;color:var(--text)}
.ac-item:hover{background:var(--bg)}
.ac-empty{padding:.45rem .75rem;font-size:.78rem;color:var(--muted)}
.tbl-wrap{max-height:420px;overflow-y:auto;border:1px solid var(--border);border-radius:.5rem}
table{width:100%;border-collapse:collapse;font-size:.78rem}
th{background:var(--bg);padding:.65rem .9rem;text-align:left;font-size:.68rem;
  text-transform:uppercase;letter-spacing:.05em;color:var(--muted);cursor:pointer;
  user-select:none;position:sticky;top:0;z-index:1;white-space:nowrap}
th:hover{background:#e2e8f0}
td{padding:.65rem .9rem;border-bottom:1px solid var(--border);vertical-align:top;
  max-width:260px;word-break:break-word}
tr:last-child td{border-bottom:none}
tr:hover td{background:#f8fafc}
.empty{text-align:center;color:var(--muted);padding:2.5rem}
@media(max-width:900px){
  .kpi-grid{grid-template-columns:repeat(2,1fr)}
  .chart-2col{grid-template-columns:1fr}
  main{padding:1rem}
  header{flex-direction:column;gap:.75rem;text-align:center}
}
</style>
</head>
<body>
<header>
  <div>
    <h1>📊 SNIES Monitor · Uninorte</h1>
    <div class="sub">Programas universitarios de pregrado — Colombia</div>
  </div>
  <div class="badge-update">
    <span style="opacity:.7;font-size:.68rem">Última actualización</span>
    <strong id="fecha-update">–</strong>
  </div>
</header>
<main>
  <section class="kpi-grid">
    <div class="kpi">
      <div class="kpi-label">Programas activos</div>
      <div class="kpi-val" id="k-total">–</div>
      <div class="kpi-sub">universitarios hoy</div>
    </div>
    <div class="kpi g link" onclick="location.href='nuevos.html'" title="Ver detalle">
      <div class="kpi-label">Nuevos (último run)</div>
      <div class="kpi-val" id="k-nue">–</div>
      <div class="kpi-sub" id="k-nue-sub">acumulado: –</div>
      <div class="kpi-hint">Ver detalle →</div>
    </div>
    <div class="kpi r link" onclick="location.href='inactivos.html'" title="Ver detalle">
      <div class="kpi-label">Inactivos (último run)</div>
      <div class="kpi-val" id="k-ina">–</div>
      <div class="kpi-sub" id="k-ina-sub">acumulado: –</div>
      <div class="kpi-hint">Ver detalle →</div>
    </div>
    <div class="kpi a link" onclick="location.href='modificados.html'" title="Ver detalle">
      <div class="kpi-label">Modificados (último run)</div>
      <div class="kpi-val" id="k-mod">–</div>
      <div class="kpi-sub" id="k-mod-sub">acumulado: –</div>
      <div class="kpi-hint">Ver detalle →</div>
    </div>
  </section>

  <section class="chart-2col">
    <div class="card">
      <div class="card-title">Por sector</div>
      <div id="ch-sector" style="height:260px"></div>
    </div>
    <div class="card">
      <div class="card-title">Top 15 departamentos de oferta</div>
      <div id="ch-depto" style="height:260px"></div>
    </div>
  </section>

  <section class="card">
    <div class="card-title">Programas activos por departamento</div>
    <div id="ch-mapa" style="height:520px"></div>
  </section>

  <section class="card">
    <div class="card-title">Distribución de programas activos por duración (periodos requeridos) — clic para filtrar</div>
    <div id="ch-periodos" style="height:260px"></div>
    <div id="periodos-selector" style="display:flex;flex-wrap:wrap;gap:.35rem;margin-top:.6rem"></div>
  </section>

  <div id="periodos-chip" style="display:none;align-items:center;gap:.6rem;
      padding:.55rem 1.5rem;background:#eaf1f8;border:1px solid #c7d7ea;
      border-radius:.5rem;margin-bottom:.75rem">
    <span style="font-size:.78rem;color:#15284b">Filtrado por duración:
      <strong id="periodos-chip-val"></strong></span>
    <button onclick="clearPeriodosFilter()"
      style="background:none;border:none;cursor:pointer;color:#2d5b9e;font-size:.82rem;padding:0">
      ✕ Limpiar filtro</button>
  </div>

  <section id="snap-section" style="display:none">
    <div class="card">
      <div style="display:flex;align-items:center;justify-content:space-between;margin-bottom:.75rem;flex-wrap:wrap;gap:.5rem">
        <div class="card-title" style="margin-bottom:0">Programas activos — <span id="snap-title"></span></div>
      </div>
      <div class="f-row">
        <input class="f-input" id="snap-search" placeholder="Buscar por nombre, código SNIES…" oninput="filterSnap()">
        <div class="ac-wrap">
          <input class="f-input" id="snap-institucion" style="width:100%" placeholder="Buscar institución…" oninput="filterSnap()">
          <div class="ac-menu" id="snap-institucion-menu"></div>
        </div>
        <select id="snap-sector" class="f-sel" onchange="filterSnap()"><option value="">Todos los sectores</option></select>
        <select id="snap-depto" class="f-sel" onchange="filterSnap()"><option value="">Todos los departamentos</option></select>
        <select id="snap-modalidad" class="f-sel" onchange="filterSnap()"><option value="">Todas las modalidades</option></select>
        <button class="f-btn" onclick="resetSnapFilters()">✕ Limpiar</button>
      </div>
      <div class="tbl-wrap" id="snap-tbl"></div>
    </div>
  </section>

  <section>
    <div class="tab-nav">
      <button class="tab-btn on" onclick="tab('nue',this)">
        Nuevos <span class="n" id="bn-nue">0</span>
      </button>
      <button class="tab-btn" onclick="tab('ina',this)">
        Inactivos <span class="n" id="bn-ina">0</span>
      </button>
      <button class="tab-btn" onclick="tab('mod',this)">
        Modificados <span class="n" id="bn-mod">0</span>
      </button>
    </div>
    <div id="tp-nue" class="tab-pane on">
      <div class="f-row">
        <input class="f-input" id="q-nue" placeholder="Buscar por nombre, código SNIES…" oninput="filter('nue')">
        <div class="ac-wrap">
          <input class="f-input" id="ins-nue" style="width:100%" placeholder="Buscar institución…" oninput="filter('nue')">
          <div class="ac-menu" id="ins-nue-menu"></div>
        </div>
        <select id="se-nue" class="f-sel" onchange="filter('nue')"><option value="">Todos los sectores</option></select>
        <select id="de-nue" class="f-sel" onchange="filter('nue')"><option value="">Todos los departamentos</option></select>
        <select id="di-nue" class="f-sel" onchange="filter('nue')"><option value="">Todas las divisiones</option></select>
        <select id="mo-nue" class="f-sel" onchange="filter('nue')"><option value="">Todas las modalidades</option></select>
        <select id="fe-nue" class="f-sel" onchange="filter('nue')"><option value="">Todas las fechas</option></select>
        <select id="ci-nue" class="f-sel" onchange="filter('nue')"><option value="">Todos los campos CINE</option></select>
        <button class="f-btn" onclick="resetTblFilters('nue')">✕ Limpiar</button>
      </div>
      <div class="tbl-wrap" id="tw-nue"></div>
    </div>
    <div id="tp-ina" class="tab-pane">
      <div class="f-row">
        <input class="f-input" id="q-ina" placeholder="Buscar por nombre, código SNIES…" oninput="filter('ina')">
        <div class="ac-wrap">
          <input class="f-input" id="ins-ina" style="width:100%" placeholder="Buscar institución…" oninput="filter('ina')">
          <div class="ac-menu" id="ins-ina-menu"></div>
        </div>
        <select id="se-ina" class="f-sel" onchange="filter('ina')"><option value="">Todos los sectores</option></select>
        <select id="de-ina" class="f-sel" onchange="filter('ina')"><option value="">Todos los departamentos</option></select>
        <select id="di-ina" class="f-sel" onchange="filter('ina')"><option value="">Todas las divisiones</option></select>
        <select id="mo-ina" class="f-sel" onchange="filter('ina')"><option value="">Todas las modalidades</option></select>
        <select id="fe-ina" class="f-sel" onchange="filter('ina')"><option value="">Todas las fechas</option></select>
        <select id="ci-ina" class="f-sel" onchange="filter('ina')"><option value="">Todos los campos CINE</option></select>
        <button class="f-btn" onclick="resetTblFilters('ina')">✕ Limpiar</button>
      </div>
      <div class="tbl-wrap" id="tw-ina"></div>
    </div>
    <div id="tp-mod" class="tab-pane">
      <div class="f-row">
        <input class="f-input" id="q-mod" placeholder="Buscar por nombre, código SNIES…" oninput="filter('mod')">
        <div class="ac-wrap">
          <input class="f-input" id="ins-mod" style="width:100%" placeholder="Buscar institución…" oninput="filter('mod')">
          <div class="ac-menu" id="ins-mod-menu"></div>
        </div>
        <select id="se-mod" class="f-sel" onchange="filter('mod')"><option value="">Todos los sectores</option></select>
        <select id="de-mod" class="f-sel" onchange="filter('mod')"><option value="">Todos los departamentos</option></select>
        <select id="di-mod" class="f-sel" onchange="filter('mod')"><option value="">Todas las divisiones</option></select>
        <select id="fe-mod" class="f-sel" onchange="filter('mod')"><option value="">Todas las fechas</option></select>
        <select id="tc-mod" class="f-sel" onchange="filter('mod')"><option value="">Todos los cambios</option></select>
        <button class="f-btn" onclick="resetTblFilters('mod')">✕ Limpiar</button>
      </div>
      <div class="tbl-wrap" id="tw-mod"></div>
    </div>
  </section>
</main>

<script>
const D = __DATA__;
const fmt = n => (n ?? 0).toLocaleString('es-CO');
const _norm = s => String(s==null?'':s).normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLowerCase();
function _rowMatches(r, tokens) {
  if (!tokens.length) return true;
  const hay = _norm(Object.values(r).join(' '));
  return tokens.every(t => hay.includes(t));
}
function gv(id) { const el = document.getElementById(id); return el ? el.value : ''; }
const parseFecha = s => { try { const [d,m,y]=s.split('/'); return new Date(+y,+m-1,+d); } catch(e){return new Date(0);} };
function uniq(arr) { return [...new Set(arr.filter(v => v && String(v).trim() !== ''))].sort(); }
function addOpts(id, vals) {
  const el = document.getElementById(id); if (!el) return;
  vals.forEach(v => { const o = document.createElement('option'); o.value = o.textContent = v; el.appendChild(o); });
}
function initAutocomplete(inputId, menuId, options, onChange) {
  const inp = document.getElementById(inputId), menu = document.getElementById(menuId);
  if (!inp || !menu) return;
  function render() {
    const q = _norm(inp.value).trim();
    const matches = (q ? options.filter(o => _norm(o).includes(q)) : options).slice(0, 50);
    menu.innerHTML = matches.length
      ? matches.map(o => '<div class="ac-item">' + o.replace(/&/g,'&amp;').replace(/</g,'&lt;') + '</div>').join('')
      : '<div class="ac-empty">Sin coincidencias</div>';
    menu.classList.add('show');
  }
  inp.addEventListener('focus', render);
  inp.addEventListener('input', () => { render(); onChange(); });
  menu.addEventListener('mousedown', e => {
    const it = e.target.closest('.ac-item'); if (!it) return;
    e.preventDefault();
    inp.value = it.textContent;
    menu.classList.remove('show');
    onChange();
  });
  document.addEventListener('click', e => {
    if (e.target !== inp && !menu.contains(e.target)) menu.classList.remove('show');
  });
}
document.getElementById('fecha-update').textContent = D.ultima_actualizacion;
document.getElementById('k-total').textContent = fmt(D.kpis.total_activos);
document.getElementById('k-nue').textContent   = fmt(D.kpis.nuevos_ultimo);
document.getElementById('k-ina').textContent   = fmt(D.kpis.inactivos_ultimo);
document.getElementById('k-mod').textContent   = fmt(D.kpis.mods_ultimo);
document.getElementById('k-nue-sub').textContent = 'acumulado: ' + fmt(D.kpis.nuevos_total);
document.getElementById('k-ina-sub').textContent = 'acumulado: ' + fmt(D.kpis.inactivos_total);
document.getElementById('k-mod-sub').textContent = 'acumulado: ' + fmt(D.kpis.mods_total);


(function() {
  const d = D.por_sector;
  if (!d.length) return;
  Plotly.newPlot('ch-sector', [{
    labels: d.map(x => x.label), values: d.map(x => x.value),
    type:'pie', hole:0.45,
    marker:{colors:['#2d5b9e','#fcc10e','#bd900b','#ae1e22','#6e91b9','#214174']},
    textinfo:'label+percent',
    hovertemplate:'%{label}<br><b>%{value:,}</b><extra></extra>'
  }], {
    margin:{t:10,r:10,b:10,l:10}, showlegend:false,
    plot_bgcolor:'white', paper_bgcolor:'white'
  }, {responsive:true, displayModeBar:false});
})();

(function() {
  const d = [...D.por_depto].reverse();
  if (!d.length) return;
  Plotly.newPlot('ch-depto', [{
    y: d.map(x => x.label), x: d.map(x => x.value),
    type:'bar', orientation:'h',
    marker:{color:'#2d5b9e', opacity:0.82},
    hovertemplate:'%{y}<br><b>%{x:,}</b><extra></extra>'
  }], {
    margin:{t:10,r:20,b:40,l:170},
    xaxis:{showgrid:true, gridcolor:'#e2e8f0', tickfont:{size:11}},
    yaxis:{tickfont:{size:11}},
    plot_bgcolor:'white', paper_bgcolor:'white', bargap:0.3
  }, {responsive:true, displayModeBar:false});
})();

(function() {
  const d = D.por_depto_mapa;
  if (!d || !d.length) return;
  const GEO_URL = 'https://gist.githubusercontent.com/john-guerra/43c7656821069d00dcbc/raw/be6a6e239cd5b5b803c6e7c2ec405b793a9064dd/Colombia.geo.json';
  fetch(GEO_URL)
    .then(r => r.json())
    .then(geo => {
      Plotly.newPlot('ch-mapa', [{
        type: 'choropleth',
        geojson: geo,
        featureidkey: 'properties.NOMBRE_DPT',
        locations: d.map(x => x.depto),
        z: d.map(x => x.total),
        text: d.map(x => x.depto + '<br>' + x.total.toLocaleString('es-CO') + ' programas (' + x.pct + '%)'),
        hovertemplate: '%{text}<extra></extra>',
        colorscale: [[0,'#feecb7'],[0.35,'#fcc10e'],[0.7,'#2d5b9e'],[1,'#15284b']],
        showscale: true,
        colorbar: {thickness: 14, len: 0.6, title: {text: 'Programas', side: 'right', font: {size: 11}}},
        marker: {line: {color: 'white', width: 0.5}}
      }], {
        geo: {
          fitbounds: 'locations',
          showframe: false,
          showcoastlines: false,
          showland: true, landcolor: '#f1f5f9',
          showocean: true, oceancolor: '#e4ecf6',
          showlakes: false,
          projection: {type: 'mercator'}
        },
        margin: {t:0, r:0, b:0, l:0},
        paper_bgcolor: 'white'
      }, {responsive: true, displayModeBar: false});
    })
    .catch(() => {
      document.getElementById('ch-mapa').innerHTML =
        '<div style="display:flex;align-items:center;justify-content:center;height:100%;color:#64748b;font-size:.82rem">No se pudo cargar el mapa</div>';
    });
})();

(function() {
  const ds = D.por_periodos_stacked;
  if (!ds || !ds.labels || !ds.labels.length) return;
  const PCOLORS = ['#2d5b9e','#fcc10e','#bd900b','#ae1e22','#6e91b9',
                   '#214174','#d56f18','#948e56','#15284b','#7a1518'];
  const traces = ds.series.map((s, i) => ({
    x: ds.labels, y: s.values, name: s.name, type: 'bar',
    marker: {color: PCOLORS[i % PCOLORS.length], opacity: 0.85},
    hovertemplate: s.name + '<br>%{x} periodos — <b>%{y:,}</b> programas<extra></extra>'
  }));
  Plotly.newPlot('ch-periodos', traces, {
    barmode: 'stack',
    margin: {t:10, r:20, b:90, l:70},
    xaxis: {title: 'Periodos', tickmode: 'array',
            tickvals: ds.labels, tickfont: {size:11}},
    yaxis: {title: 'N. Programas', showgrid: true,
            gridcolor: '#e2e8f0', tickfont: {size:11}},
    plot_bgcolor: 'white', paper_bgcolor: 'white', bargap: 0.25,
    legend: {orientation: 'h', y: -0.28, font: {size: 11}, entrywidth: 120, entrywidthmode: 'pixels'},
    hovermode: 'x unified'
  }, {responsive: true, displayModeBar: false}).then(gd => {
    gd.on('plotly_click', function(ev) { setPeriodosFilter(ev.points[0].x); });
  });

  // Chips — compute total per label across all series
  const totals = {};
  ds.labels.forEach((l, i) => {
    totals[l] = ds.series.reduce((acc, ser) => acc + (ser.values[i] || 0), 0);
  });
  const sel = document.getElementById('periodos-selector');
  if (sel) {
    sel.innerHTML = ds.labels.map(l =>
      '<button id="pchip-'+l+'" onclick="setPeriodosFilter('+l+')" '+
      'style="padding:.22rem .65rem;background:#f1f5f9;border:1px solid #e2e8f0;'+
      'border-radius:2rem;font-size:.72rem;cursor:pointer;transition:all .15s;white-space:nowrap">'+
      l+' sem&nbsp;<span style="opacity:.6">('+totals[l].toLocaleString('es-CO')+')</span></button>'
    ).join('');
  }
})();

let periodosFiltro = null;
const _snapAll = D.snapshot || [];

const _SNAP_COLS = ['CÓDIGO_SNIES_DEL_PROGRAMA','NOMBRE_DEL_PROGRAMA','NOMBRE_INSTITUCIÓN',
                    'SECTOR','MODALIDAD','DEPARTAMENTO_OFERTA_PROGRAMA','PERIODICIDAD'];
const _SNAP_HEAD = {
  'CÓDIGO_SNIES_DEL_PROGRAMA':'Cód. SNIES', 'NOMBRE_DEL_PROGRAMA':'Programa',
  'NOMBRE_INSTITUCIÓN':'Institución', 'SECTOR':'Sector', 'MODALIDAD':'Modalidad',
  'DEPARTAMENTO_OFERTA_PROGRAMA':'Departamento', 'PERIODICIDAD':'Periodicidad'
};

function _buildSnapTbl(data) {
  const cols = _SNAP_COLS.filter(c => !data.length || c in data[0]);
  let h = '<table><thead><tr>';
  cols.forEach(c => { h += '<th>' + (_SNAP_HEAD[c]||c) + '</th>'; });
  h += '</tr></thead><tbody>';
  if (!data.length) {
    h += '<tr><td colspan="'+cols.length+'" class="empty">Sin registros</td></tr>';
  } else {
    data.forEach(r => { h += '<tr>' + cols.map(c => '<td>'+(r[c]||'')+'</td>').join('') + '</tr>'; });
  }
  return h + '</tbody></table>';
}

addOpts('snap-sector',    uniq(_snapAll.map(r => r['SECTOR'])));
addOpts('snap-depto',     uniq(_snapAll.map(r => r['DEPARTAMENTO_OFERTA_PROGRAMA'])));
addOpts('snap-modalidad', uniq(_snapAll.map(r => r['MODALIDAD'])));

function filterSnap() {
  const qTokens = _norm(gv('snap-search')).split(/\s+/).filter(Boolean);
  const insTokens = _norm(gv('snap-institucion')).split(/\s+/).filter(Boolean);
  const se = gv('snap-sector'), de = gv('snap-depto'), mo = gv('snap-modalidad');
  const res = _snapAll.filter(r => {
    const v = r['NÚMERO_PERIODOS_DE_DURACIÓN'];
    if (!(v !== undefined && v !== '' && Math.round(parseFloat(String(v))) === periodosFiltro)) return false;
    if (!_rowMatches(r, qTokens)) return false;
    if (insTokens.length) {
      const hayIns = _norm(r['NOMBRE_INSTITUCIÓN']);
      if (!insTokens.every(t => hayIns.includes(t))) return false;
    }
    if (se && r['SECTOR'] !== se) return false;
    if (de && r['DEPARTAMENTO_OFERTA_PROGRAMA'] !== de) return false;
    if (mo && r['MODALIDAD'] !== mo) return false;
    return true;
  });
  document.getElementById('snap-tbl').innerHTML = _buildSnapTbl(res);
}

function resetSnapFilters() {
  ['snap-search','snap-institucion','snap-sector','snap-depto','snap-modalidad'].forEach(id => {
    const el = document.getElementById(id); if (el) el.value = '';
  });
  filterSnap();
}

function _updateChipStyles() {
  document.querySelectorAll('[id^="pchip-"]').forEach(btn => {
    const active = btn.id === 'pchip-' + periodosFiltro;
    btn.style.background    = active ? '#2d5b9e' : '#f1f5f9';
    btn.style.color         = active ? '#fff'    : '';
    btn.style.borderColor   = active ? '#2d5b9e' : '#e2e8f0';
    btn.style.fontWeight    = active ? '600'     : '';
  });
}

function setPeriodosFilter(val) {
  if (periodosFiltro === val) { clearPeriodosFilter(); return; }
  periodosFiltro = val;
  const matching = _snapAll.filter(r => {
    const v = r['NÚMERO_PERIODOS_DE_DURACIÓN'];
    return v !== undefined && v !== '' && Math.round(parseFloat(String(v))) === val;
  });
  const label = val + ' periodos — ' + matching.length.toLocaleString('es-CO') + ' programas activos';
  document.getElementById('periodos-chip').style.display = 'flex';
  document.getElementById('periodos-chip-val').textContent = label;
  document.getElementById('snap-title').textContent = label;
  ['snap-search','snap-institucion','snap-sector','snap-depto','snap-modalidad'].forEach(id => {
    const el = document.getElementById(id); if (el) el.value = '';
  });
  filterSnap();
  document.getElementById('snap-section').style.display = 'block';
  _updateChipStyles();
  document.getElementById('snap-section').scrollIntoView({behavior:'smooth'});
}

function clearPeriodosFilter() {
  periodosFiltro = null;
  document.getElementById('periodos-chip').style.display = 'none';
  document.getElementById('snap-section').style.display = 'none';
  _updateChipStyles();
}

const COLS = {
  nue: ['FECHA_OBTENCION','CÓDIGO_SNIES_DEL_PROGRAMA','NOMBRE_DEL_PROGRAMA',
        'NOMBRE_INSTITUCIÓN','MODALIDAD','DEPARTAMENTO_OFERTA_PROGRAMA','DIVISIÓN UNINORTE'],
  ina: ['FECHA_OBTENCION','CÓDIGO_SNIES_DEL_PROGRAMA','NOMBRE_DEL_PROGRAMA',
        'NOMBRE_INSTITUCIÓN','MODALIDAD','DEPARTAMENTO_OFERTA_PROGRAMA','DIVISIÓN UNINORTE'],
  mod: ['FECHA_OBTENCION','CÓDIGO_SNIES_DEL_PROGRAMA','NOMBRE_DEL_PROGRAMA',
        'NOMBRE_INSTITUCIÓN','QUE_CAMBIO']
};
const HEAD = {
  FECHA_OBTENCION:'Fecha', 'CÓDIGO_SNIES_DEL_PROGRAMA':'Cód.',
  NOMBRE_DEL_PROGRAMA:'Programa', 'NOMBRE_INSTITUCIÓN':'Institución',
  SECTOR:'Sector', MODALIDAD:'Modalidad',
  DEPARTAMENTO_OFERTA_PROGRAMA:'Dpto.', 'DIVISIÓN UNINORTE':'División',
  QUE_CAMBIO:'¿Qué cambió?'
};
const rows = {nue: D.nuevos, ina: D.inactivos, mod: D.modificados};
let filteredRows = {nue: rows.nue, ina: rows.ina, mod: rows.mod};
let sortDir = {};

const FILTROS_TIPO = {
  nue: ['se','de','di','mo','fe','ci'],
  ina: ['se','de','di','mo','fe','ci'],
  mod: ['se','de','di','fe','tc'],
};

const INSTITUCIONES_TODAS = uniq([
  ..._snapAll.map(r => r['NOMBRE_INSTITUCIÓN']),
  ...rows.nue.map(r => r['NOMBRE_INSTITUCIÓN']),
  ...rows.ina.map(r => r['NOMBRE_INSTITUCIÓN']),
  ...rows.mod.map(r => r['NOMBRE_INSTITUCIÓN']),
]);
initAutocomplete('snap-institucion', 'snap-institucion-menu', INSTITUCIONES_TODAS, filterSnap);
initAutocomplete('ins-nue', 'ins-nue-menu', INSTITUCIONES_TODAS, () => filter('nue'));
initAutocomplete('ins-ina', 'ins-ina-menu', INSTITUCIONES_TODAS, () => filter('ina'));
initAutocomplete('ins-mod', 'ins-mod-menu', INSTITUCIONES_TODAS, () => filter('mod'));

['nue','ina'].forEach(t => {
  addOpts('se-'+t, uniq(rows[t].map(r => r['SECTOR'])));
  addOpts('de-'+t, uniq(rows[t].map(r => r['DEPARTAMENTO_OFERTA_PROGRAMA'])));
  addOpts('di-'+t, uniq(rows[t].map(r => r['DIVISIÓN UNINORTE'])));
  addOpts('mo-'+t, uniq(rows[t].map(r => r['MODALIDAD'])));
  addOpts('fe-'+t, uniq(rows[t].map(r => r['FECHA_OBTENCION'])).sort((a,b) => parseFecha(b)-parseFecha(a)));
  addOpts('ci-'+t, uniq(rows[t].map(r => (r['CINE_F_2013_AC_CAMPO_ESPECÍFIC']||'').trim())));
});
addOpts('se-mod', uniq(rows.mod.map(r => r['SECTOR'])));
addOpts('de-mod', uniq(rows.mod.map(r => r['DEPARTAMENTO_OFERTA_PROGRAMA'])));
addOpts('di-mod', uniq(rows.mod.map(r => r['DIVISIÓN UNINORTE'])));
addOpts('fe-mod', uniq(rows.mod.map(r => r['FECHA_OBTENCION'])).sort((a,b) => parseFecha(b)-parseFecha(a)));
{
  const cs = new Set();
  rows.mod.forEach(r => { (r['QUE_CAMBIO']||'').split(' | ').forEach(p => { const f=p.split(':')[0].trim(); if(f&&f!=='nan'&&f!=='') cs.add(f); }); });
  addOpts('tc-mod', [...cs].sort());
}

function buildTbl(type, data) {
  const cols = COLS[type].filter(c => !data.length || c in data[0]);
  let h = '<table><thead><tr>';
  cols.forEach(c => {
    h += '<th onclick="sortTbl(\'' + type + '\',\'' + c + '\')">' + (HEAD[c]||c) + ' <span style="opacity:.4">↕</span></th>';
  });
  h += '</tr></thead><tbody>';
  if (!data.length) {
    h += '<tr><td colspan="' + cols.length + '" class="empty">Sin registros</td></tr>';
  } else {
    data.forEach(r => {
      h += '<tr>' + cols.map(c => '<td>' + (r[c]||'') + '</td>').join('') + '</tr>';
    });
  }
  return h + '</tbody></table>';
}

function render(type, data) {
  document.getElementById('tw-' + type).innerHTML = buildTbl(type, data);
}

['nue','ina','mod'].forEach(t => {
  render(t, rows[t]);
  document.getElementById('bn-' + t).textContent = rows[t].length;
});

function tab(id, btn) {
  document.querySelectorAll('.tab-pane').forEach(el => el.classList.remove('on'));
  document.querySelectorAll('.tab-btn').forEach(el => el.classList.remove('on'));
  document.getElementById('tp-' + id).classList.add('on');
  btn.classList.add('on');
}

function filter(type) {
  const qTokens = _norm(gv('q-'+type)).split(/\s+/).filter(Boolean);
  const insTokens = _norm(gv('ins-'+type)).split(/\s+/).filter(Boolean);
  const se = gv('se-'+type), de = gv('de-'+type), di = gv('di-'+type);
  const mo = gv('mo-'+type), fe = gv('fe-'+type), ci = gv('ci-'+type), tc = gv('tc-'+type);

  const res = rows[type].filter(r => {
    if (!_rowMatches(r, qTokens)) return false;
    if (insTokens.length) {
      const hayIns = _norm(r['NOMBRE_INSTITUCIÓN']);
      if (!insTokens.every(t => hayIns.includes(t))) return false;
    }
    if (se && r['SECTOR'] !== se) return false;
    if (de && r['DEPARTAMENTO_OFERTA_PROGRAMA'] !== de) return false;
    if (di && r['DIVISIÓN UNINORTE'] !== di) return false;
    if (mo && r['MODALIDAD'] !== mo) return false;
    if (fe && r['FECHA_OBTENCION'] !== fe) return false;
    if (ci && (r['CINE_F_2013_AC_CAMPO_ESPECÍFIC']||'').trim() !== ci) return false;
    if (tc && !(r['QUE_CAMBIO']||'').includes(tc)) return false;
    return true;
  });
  filteredRows[type] = res;
  render(type, res);
}

function resetTblFilters(type) {
  (FILTROS_TIPO[type]||[]).forEach(p => { const el = document.getElementById(p+'-'+type); if (el) el.value=''; });
  ['q-'+type, 'ins-'+type].forEach(id => { const el = document.getElementById(id); if (el) el.value=''; });
  filter(type);
}

function sortTbl(type, col) {
  const key = type + col;
  sortDir[key] = !sortDir[key];
  filteredRows[type] = [...filteredRows[type]].sort((a, b) => {
    const va = a[col] || '', vb = b[col] || '';
    return sortDir[key] ? va.localeCompare(vb, 'es') : vb.localeCompare(va, 'es');
  });
  render(type, filteredRows[type]);
}
</script>
</body>
</html>
"""

# ── detail page template ──────────────────────────────────────────────────────

DETAIL_TEMPLATE = r"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITLE__ · SNIES Monitor</title>
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js" charset="utf-8"></script>
<style>
:root{
  --bg:#f1f5f9;--surface:#fff;--text:#0f172a;--muted:#64748b;
  --border:#e2e8f0;--blue:#2d5b9e;--radius:0.75rem;
}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Segoe UI',system-ui,sans-serif;background:var(--bg);color:var(--text);font-size:14px}
header{color:#fff;padding:1.2rem 2rem;display:flex;justify-content:space-between;align-items:center;gap:1rem}
header h1{font-size:1.25rem;font-weight:700}
header .sub{font-size:.77rem;opacity:.75;margin-top:.2rem}
.back-btn{display:inline-flex;align-items:center;gap:.3rem;background:rgba(255,255,255,.2);
  border:1px solid rgba(255,255,255,.35);color:#fff;text-decoration:none;padding:.38rem .85rem;
  border-radius:.4rem;font-size:.8rem;font-weight:500;white-space:nowrap;transition:background .15s}
.back-btn:hover{background:rgba(255,255,255,.32)}
.badge-update{background:rgba(255,255,255,.15);border:1px solid rgba(255,255,255,.3);
  padding:.45rem .9rem;border-radius:2rem;font-size:.74rem;text-align:right;white-space:nowrap}
.badge-update strong{display:block;font-size:.88rem}
/* filter bar */
.filter-bar{position:sticky;top:0;z-index:100;background:var(--surface);
  border-bottom:1px solid var(--border);padding:.6rem 2rem;
  display:flex;gap:.45rem;flex-wrap:wrap;align-items:center;
  box-shadow:0 2px 8px rgba(0,0,0,.06)}
.f-input{flex:1;min-width:200px;padding:.4rem .75rem;border:1px solid var(--border);
  border-radius:.4rem;font-size:.8rem;outline:none}
.f-input:focus{border-color:var(--blue)}
.f-sel{padding:.4rem .6rem;border:1px solid var(--border);border-radius:.4rem;
  font-size:.77rem;background:var(--surface);outline:none;cursor:pointer;max-width:175px}
.f-sel:focus{border-color:var(--blue)}
.f-btn{padding:.4rem .85rem;border:1px solid var(--border);border-radius:.4rem;
  font-size:.77rem;background:var(--surface);cursor:pointer;color:var(--muted);white-space:nowrap}
.f-btn:hover{background:var(--bg)}
.f-count{margin-left:auto;font-size:.82rem;font-weight:600;color:var(--blue);white-space:nowrap}
.ac-wrap{position:relative;flex:0 1 240px}
.ac-menu{position:absolute;top:calc(100% + 2px);left:0;right:0;z-index:300;
  background:var(--surface);border:1px solid var(--border);border-radius:.4rem;
  box-shadow:0 8px 20px rgba(0,0,0,.14);max-height:260px;overflow-y:auto;display:none}
.ac-menu.show{display:block}
.ac-item{padding:.45rem .75rem;font-size:.78rem;cursor:pointer;color:var(--text)}
.ac-item:hover{background:var(--bg)}
.ac-empty{padding:.45rem .75rem;font-size:.78rem;color:var(--muted)}
/* layout */
main{max-width:1380px;margin:0 auto;padding:1.4rem 2rem}
.card{background:var(--surface);border-radius:var(--radius);padding:1.2rem;
  box-shadow:0 1px 3px rgba(0,0,0,.07);margin-bottom:1rem}
.ct{font-size:.68rem;font-weight:600;text-transform:uppercase;letter-spacing:.06em;
  color:var(--muted);margin-bottom:.85rem}
.g2{display:grid;grid-template-columns:1fr 1fr;gap:1rem;margin-bottom:1rem}
/* table */
.tbl-card{padding:0}
.tbl-card .ct{padding:1.1rem 1.2rem .5rem}
.tbl-wrap{max-height:520px;overflow-y:auto;border-top:1px solid var(--border)}
table{width:100%;border-collapse:collapse;font-size:.77rem}
th{background:var(--bg);padding:.6rem .85rem;text-align:left;font-size:.67rem;
  text-transform:uppercase;letter-spacing:.05em;color:var(--muted);cursor:pointer;
  user-select:none;position:sticky;top:0;z-index:1;white-space:nowrap}
th:hover{background:#e2e8f0}
td{padding:.6rem .85rem;border-bottom:1px solid var(--border);vertical-align:top;
  max-width:270px;word-break:break-word}
tr:last-child td{border-bottom:none}
tr:hover td{background:#f8fafc}
.empty{text-align:center;color:var(--muted);padding:2.5rem}
@media(max-width:900px){
  .g2{grid-template-columns:1fr}
  main{padding:1rem}
  header{flex-direction:column;gap:.6rem;text-align:center}
  .filter-bar{padding:.6rem 1rem}
  .f-count{margin-left:0}
}
</style>
</head>
<body>
<header style="background:__HDRGRD__">
  <div style="display:flex;align-items:center;gap:.9rem">
    <a href="index.html" class="back-btn">← Dashboard</a>
    <div>
      <h1>__EMOJI__ __TITLE__</h1>
      <div class="sub">Programas universitarios de pregrado · Colombia</div>
    </div>
  </div>
  __EXTRA_LINK__
  <div class="badge-update">
    <span style="opacity:.7;font-size:.67rem">Total acumulado</span>
    <strong id="badge-total">–</strong>
  </div>
</header>

<div class="filter-bar">
  <input id="f-q" class="f-input" placeholder="Buscar por nombre, institución, código SNIES, departamento…" oninput="applyFilters()">
  <select id="f-sector"   class="f-sel" onchange="applyFilters()"><option value="">Todos los sectores</option></select>
  <select id="f-depto"    class="f-sel" onchange="applyFilters()"><option value="">Todos los departamentos</option></select>
  <div class="ac-wrap">
    <input id="f-institucion" class="f-sel" placeholder="Buscar institucion..." style="cursor:text;width:100%" oninput="applyFilters()">
    <div class="ac-menu" id="f-institucion-menu"></div>
  </div>
  __FDIV_SELECT__
  __XFILTER__
  <select id="f-fecha"    class="f-sel" onchange="applyFilters()"><option value="">Todas las fechas</option></select>
  <button class="f-btn" onclick="resetFilters()">✕ Limpiar</button>
  <span class="f-count" id="f-count">–</span>
</div>

<main>
  <section>__CHARTS__</section>

  <div id="per-det-chip" style="display:none;align-items:center;gap:.6rem;
      padding:.5rem 1.25rem;background:#eaf1f8;border:1px solid #c7d7ea;
      border-radius:.5rem;margin-bottom:.75rem">
    <span style="font-size:.78rem;color:#15284b">Filtrado por duración:
      <strong id="per-det-val"></strong></span>
    <button onclick="clearPeriodosDetalleFilter()"
      style="background:none;border:none;cursor:pointer;color:#2d5b9e;font-size:.82rem;padding:0">
      ✕ Limpiar filtro</button>
  </div>

  <div id="cine-det-chip" style="display:none;align-items:center;gap:.6rem;
      padding:.5rem 1.25rem;background:#fef6dc;border:1px solid #fce6a6;
      border-radius:.5rem;margin-bottom:.75rem">
    <span style="font-size:.78rem;color:#7a5d06">Filtrado por CINE:
      <strong id="cine-det-val"></strong></span>
    <button onclick="clearCineFiltro()"
      style="background:none;border:none;cursor:pointer;color:#bd900b;font-size:.82rem;padding:0">
      ✕ Limpiar filtro</button>
  </div>

  <section class="card tbl-card">
    <div class="ct">Registros</div>
    <div class="tbl-wrap" id="tbl-wrap"></div>
  </section>
</main>

<script>
const ROWS = __DATA__;
const CFG  = __CONFIG__;

const PC = {responsive:true, displayModeBar:false};
const fmt = n => (n ?? 0).toLocaleString('es-CO');
const _norm = s => String(s==null?'':s).normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLowerCase();
function _rowMatches(r, tokens) {
  if (!tokens.length) return true;
  const hay = _norm(Object.values(r).join(' '));
  return tokens.every(t => hay.includes(t));
}
const C   = CFG.color;
const CA  = CFG.colorAlpha;

let filtered = [...ROWS];
let sortDir  = {};

document.getElementById('badge-total').textContent = fmt(ROWS.length);

// ── Dropdowns ──────────────────────────────────────────────────────────────
function uniq(arr) {
  return [...new Set(arr.filter(v => v && String(v).trim() !== ''))].sort();
}
function addOpts(id, vals) {
  const el = document.getElementById(id);
  if (!el) return;
  vals.forEach(v => { const o = document.createElement('option'); o.value = o.textContent = v; el.appendChild(o); });
}
function initAutocomplete(inputId, menuId, options, onChange) {
  const inp = document.getElementById(inputId), menu = document.getElementById(menuId);
  if (!inp || !menu) return;
  function render() {
    const q = _norm(inp.value).trim();
    const matches = (q ? options.filter(o => _norm(o).includes(q)) : options).slice(0, 50);
    menu.innerHTML = matches.length
      ? matches.map(o => '<div class="ac-item">' + o.replace(/&/g,'&amp;').replace(/</g,'&lt;') + '</div>').join('')
      : '<div class="ac-empty">Sin coincidencias</div>';
    menu.classList.add('show');
  }
  inp.addEventListener('focus', render);
  inp.addEventListener('input', () => { render(); onChange(); });
  menu.addEventListener('mousedown', e => {
    const it = e.target.closest('.ac-item'); if (!it) return;
    e.preventDefault();
    inp.value = it.textContent;
    menu.classList.remove('show');
    onChange();
  });
  document.addEventListener('click', e => {
    if (e.target !== inp && !menu.contains(e.target)) menu.classList.remove('show');
  });
}

addOpts('f-sector',   uniq(ROWS.map(r => r['SECTOR'])));
addOpts('f-depto',    uniq(ROWS.map(r => r['DEPARTAMENTO_OFERTA_PROGRAMA'])));
addOpts('f-division', uniq(ROWS.map(r => r['DIVISIÓN UNINORTE'])));
initAutocomplete('f-institucion', 'f-institucion-menu', uniq(ROWS.map(r => r['NOMBRE_INSTITUCIÓN'])), applyFilters);

// Sort fechas newest-first (DD/MM/YYYY)
const parseFecha = s => { try { const [d,m,y]=s.split('/'); return new Date(+y,+m-1,+d); } catch(e){return new Date(0);} };
const sortedFechas = uniq(ROWS.map(r => r['FECHA_OBTENCION'])).sort((a,b) => parseFecha(b)-parseFecha(a));
addOpts('f-fecha', sortedFechas);

if (CFG.tipo === 'modificados') {
  const cs = new Set();
  ROWS.forEach(r => { (r['QUE_CAMBIO']||'').split(' | ').forEach(p => { const f=p.split(':')[0].trim(); if(f&&f!=='nan'&&f!=='') cs.add(f); }); });
  addOpts('f-tipo-cambio', [...cs].sort());
} else {
  addOpts('f-modalidad', uniq(ROWS.map(r => r['MODALIDAD'])));
  addOpts('f-cine', uniq(ROWS.map(r => (r['CINE_F_2013_AC_CAMPO_ESPECÍFIC']||'').trim())));
}

// ── Filters ────────────────────────────────────────────────────────────────
function gv(id) { const el=document.getElementById(id); return el?el.value:''; }

function applyFilters() {
  const qTokens = _norm(gv('f-q')).split(/\s+/).filter(Boolean);
  const se = gv('f-sector'), de = gv('f-depto'), di = gv('f-division');
  const mo = gv('f-modalidad'), fe = gv('f-fecha'), tc = gv('f-tipo-cambio');
  const ci = gv('f-cine');
  const insTokens = _norm(gv('f-institucion')).split(/\s+/).filter(Boolean);

  filtered = ROWS.filter(r => {
    if (!_rowMatches(r, qTokens)) return false;
    if (se && r['SECTOR'] !== se) return false;
    if (de && r['DEPARTAMENTO_OFERTA_PROGRAMA'] !== de) return false;
    if (di && r['DIVISIÓN UNINORTE'] !== di) return false;
    if (mo && r['MODALIDAD'] !== mo) return false;
    if (fe && r['FECHA_OBTENCION'] !== fe) return false;
    if (tc && !(r['QUE_CAMBIO']||'').includes(tc)) return false;
    if (ci && (r['CINE_F_2013_AC_CAMPO_ESPECÍFIC']||'').trim() !== ci) return false;
    if (insTokens.length) {
      const hayIns = _norm(r['NOMBRE_INSTITUCIÓN']);
      if (!insTokens.every(t => hayIns.includes(t))) return false;
    }
    return true;
  });
  renderAll(filtered);
}

function resetFilters() {
  ['f-q','f-sector','f-depto','f-institucion','f-division','f-modalidad','f-fecha','f-tipo-cambio','f-cine'].forEach(id => {
    const el = document.getElementById(id); if (el) el.value = '';
  });
  _periodosDet=null;
  applyFilters();
}

// ── Distribution helpers ───────────────────────────────────────────────────
function countBy(rows, field, n) {
  const c={};
  rows.forEach(r => { const v=(r[field]||'Sin datos').toString().trim()||'Sin datos'; c[v]=(c[v]||0)+1; });
  return Object.entries(c).sort((a,b)=>b[1]-a[1]).slice(0,n||12);
}
// ── Shared date helper ─────────────────────────────────────────────────────
function getSem(s) {
  if(!s||!s.trim()) return null;
  let y,m;
  const iso=s.match(/^(\d{4})-(\d{2})/);
  if(iso){y=+iso[1];m=+iso[2];}
  else{const dmy=s.match(/^(\d{2})\/(\d{2})\/(\d{4})/);if(dmy){y=+dmy[3];m=+dmy[2];}}
  if(!y||y<2014||y>2035) return null;
  return y+'-'+(m<=6?'1':'2');
}

// ── Charts ─────────────────────────────────────────────────────────────────
function _emptyChart(el, msg) {
  Plotly.purge(el);
  el.innerHTML='<div style="display:flex;align-items:center;justify-content:center;height:100%;color:#64748b;font-size:.82rem">'+(msg||'Sin datos para los filtros aplicados')+'</div>';
}

function plotDonut(id, rows, field) {
  const el=document.getElementById(id); if(!el) return;
  const d=countBy(rows,field,20); if(!d.length){ _emptyChart(el); return; }
  Plotly.react(id,[{labels:d.map(e=>e[0]),values:d.map(e=>e[1]),type:'pie',hole:.45,
    marker:{colors:['#2d5b9e','#fcc10e','#bd900b','#ae1e22','#6e91b9','#214174','#d56f18']},
    textinfo:'label+percent',hovertemplate:'%{label}<br><b>%{value:,}</b><extra></extra>'}],
    {margin:{t:10,r:10,b:35,l:10},showlegend:true,legend:{orientation:'h',y:-0.12,font:{size:10}},
    plot_bgcolor:'white',paper_bgcolor:'white'},PC);
}

function plotHBar(id, rows, field, color, n, maxLen) {
  const el=document.getElementById(id); if(!el) return;
  const d=[...countBy(rows,field,n||10)].reverse(); if(!d.length){ _emptyChart(el); return; }
  const trunc=s=>maxLen&&s.length>maxLen?s.slice(0,maxLen)+'…':s;
  const labels=d.map(e=>trunc(e[0]));
  const full=d.map(e=>e[0]);
  const lMargin=maxLen?Math.min(maxLen*6.5,200):210;
  Plotly.react(id,[{y:labels,x:d.map(e=>e[1]),customdata:full,type:'bar',orientation:'h',
    marker:{color,opacity:.85},
    hovertemplate:'%{customdata}<br><b>%{x:,}</b><extra></extra>'}],
    {margin:{t:10,r:20,b:30,l:lMargin},
    xaxis:{showgrid:true,gridcolor:'#e2e8f0',tickfont:{size:10}},
    yaxis:{tickfont:{size:10},automargin:false},
    plot_bgcolor:'white',paper_bgcolor:'white',bargap:.3},PC);
}

function plotVBar(id, rows, field, color) {
  const el=document.getElementById(id); if(!el) return;
  const d=countBy(rows,field,10); if(!d.length){ _emptyChart(el); return; }
  Plotly.react(id,[{x:d.map(e=>e[0]),y:d.map(e=>e[1]),type:'bar',
    marker:{color,opacity:.85},hovertemplate:'%{x}<br><b>%{y:,}</b><extra></extra>'}],
    {margin:{t:10,r:10,b:80,l:45},
    xaxis:{tickfont:{size:10},tickangle:-30},
    yaxis:{showgrid:true,gridcolor:'#e2e8f0'},
    plot_bgcolor:'white',paper_bgcolor:'white',bargap:.35},PC);
}

function plotTimeline(id, rows) {
  const el=document.getElementById(id); if(!el) return;
  const bySem={};
  rows.forEach(r=>{const s=getSem(r['FECHA_OBTENCION']); if(s) bySem[s]=(bySem[s]||0)+1;});
  const sems=Object.keys(bySem).sort();
  if(!sems.length){ _emptyChart(el, 'Sin datos de fecha de run'); return; }
  const x=sems, y=sems.map(s=>bySem[s]);
  Plotly.react(id,[{x,y,type:'scatter',mode:'lines+markers',
    line:{color:C,width:2.5},marker:{color:C,size:7},
    fill:'tozeroy',fillcolor:CA,
    hovertemplate:'%{x}<br><b>%{y:,}</b><extra></extra>'}],
    {margin:{t:10,r:20,b:40,l:50},
    xaxis:{showgrid:false,tickfont:{size:11},type:'category'},
    yaxis:{showgrid:true,gridcolor:'#e2e8f0',rangemode:'tozero'},
    plot_bgcolor:'white',paper_bgcolor:'white',hovermode:'x unified'},PC);
}

function plotAcumuladoModalidad(id, rows) {
  const el=document.getElementById(id); if(!el) return;
  if(!rows.length){ _emptyChart(el); return; }

  const semSet=new Set();
  rows.forEach(r=>{const s=getSem(r['FECHA_DE_REGISTRO_EN_SNIES']);if(s)semSet.add(s);});
  const sems=[...semSet].sort(); // "YYYY-1" < "YYYY-2" sorts correctly as strings

  if(!sems.length){
    _emptyChart(el, 'Sin datos de fecha de registro en SNIES');
    return;
  }

  const mods=[...new Set(rows.map(r=>r['MODALIDAD']).filter(v=>v&&v.trim()))].sort();
  const COLORS=['#2d5b9e','#fcc10e','#bd900b','#ae1e22','#6e91b9','#214174','#d56f18'];

  const traces=mods.map((mod,i)=>{
    const bySem={};
    rows.filter(r=>r['MODALIDAD']===mod).forEach(r=>{
      const s=getSem(r['FECHA_DE_REGISTRO_EN_SNIES']); if(s)bySem[s]=(bySem[s]||0)+1;
    });
    let cum=0; const x=[],y=[];
    sems.forEach(s=>{cum+=(bySem[s]||0);x.push(s);y.push(cum);});
    if(cum===0) return null;
    return{x,y,name:mod,type:'scatter',mode:'lines+markers',
      line:{color:COLORS[i%COLORS.length],width:2.5},
      marker:{color:COLORS[i%COLORS.length],size:6},
      hovertemplate:mod+'<br><b>%{x}</b><br>%{y:,} acumulados<extra></extra>'};
  }).filter(Boolean);

  if(!traces.length){ _emptyChart(el); return; }
  Plotly.react(id,traces,{
    margin:{t:10,r:20,b:65,l:55},
    xaxis:{showgrid:false,tickfont:{size:11},tickangle:-30,type:'category'},
    yaxis:{showgrid:true,gridcolor:'#e2e8f0',rangemode:'tozero',tickfont:{size:11}},
    plot_bgcolor:'white',paper_bgcolor:'white',
    hovermode:'x unified',
    legend:{orientation:'h',y:-0.28,font:{size:11}}
  },PC);
}

// ── CINE cumulative chart (nuevos page only) ───────────────────────────────
const CINE_COLORS=['#2d5b9e','#fcc10e','#bd900b','#ae1e22','#6e91b9',
                   '#214174','#d56f18','#948e56','#15284b','#7a1518'];
const CINE_COL='CINE_F_2013_AC_CAMPO_ESPECÍFIC';
let _cineInit=false, _cineAll=[], _cineActive=[];

function initCINE() {
  const counts={};
  ROWS.forEach(r=>{
    const v=(r[CINE_COL]||'').trim()||'Sin clasificar';
    counts[v]=(counts[v]||0)+1;
  });
  _cineAll=Object.keys(counts).sort((a,b)=>counts[b]-counts[a]);
  _cineActive=[..._cineAll.slice(0,8)];
  const dl=document.getElementById('cine-list');
  if(dl){
    dl.innerHTML='';
    _cineAll.forEach(c=>{const o=document.createElement('option');o.value=c;dl.appendChild(o);});
  }
  _cineInit=true;
}

function renderCineChart(rows) {
  const el=document.getElementById('ch-timeline'); if(!el) return;
  const semSet=new Set();
  rows.forEach(r=>{const s=getSem(r['FECHA_DE_REGISTRO_EN_SNIES']);if(s)semSet.add(s);});
  const allSems=[...semSet].sort();
  const sems=allSems.filter(s=>s>='2023-2');

  const tagsEl=document.getElementById('cine-tags');
  if(tagsEl){
    tagsEl.innerHTML=_cineActive.map((cine,i)=>{
      const col=CINE_COLORS[i%CINE_COLORS.length];
      const safe=cine.replace(/\\/g,'\\\\').replace(/'/g,"\\'");
      return '<span title="Clic para filtrar tabla" onclick="setCineFiltro(\''+safe+'\')" style="display:inline-flex;align-items:center;gap:.3rem;'+
        'background:'+col+'22;border:1px solid '+col+'66;border-radius:2rem;'+
        'padding:.18rem .55rem;font-size:.72rem;color:'+col+';font-weight:500;cursor:pointer">'+
        cine+
        '<button onclick="event.stopPropagation();cineRemove(\''+safe+'\')" '+
        'style="background:none;border:none;cursor:pointer;color:'+col+';'+
        'font-size:.9rem;padding:0 0 0 .2rem;line-height:1;opacity:.75">\xd7</button></span>';
    }).join('');
  }

  if(!sems.length){
    _emptyChart(el, 'Sin datos de fecha de registro');
    return;
  }

  const traces=_cineActive.map((cine,i)=>{
    const isUnclass=cine==='Sin clasificar';
    const bySem={};
    rows.filter(r=>{const v=(r[CINE_COL]||'').trim();return isUnclass?!v:v===cine;})
        .forEach(r=>{const s=getSem(r['FECHA_DE_REGISTRO_EN_SNIES']);if(s)bySem[s]=(bySem[s]||0)+1;});
    let cum=0;const x=[],y=[];
    allSems.forEach(s=>{cum+=(bySem[s]||0);if(s>='2023-2'){x.push(s);y.push(cum);}});
    if(cum===0) return null;
    const col=CINE_COLORS[i%CINE_COLORS.length];
    return{x,y,name:cine,type:'scatter',mode:'lines+markers',
      line:{color:col,width:2.5},marker:{color:col,size:6},
      hovertemplate:cine+'<br><b>%{x}</b><br>%{y:,} acumulados<extra></extra>'};
  }).filter(Boolean);

  if(!traces.length){ _emptyChart(el, 'Sin datos de fecha de registro'); return; }
  Plotly.react('ch-timeline',traces,{
    margin:{t:10,r:20,b:65,l:55},
    xaxis:{showgrid:false,tickfont:{size:11},tickangle:-30,type:'category'},
    yaxis:{showgrid:true,gridcolor:'#e2e8f0',rangemode:'tozero',tickfont:{size:11}},
    plot_bgcolor:'white',paper_bgcolor:'white',
    hovermode:'x unified',
    legend:{orientation:'h',y:-0.28,font:{size:11}}
  },PC).then(gd=>{
    gd.removeAllListeners('plotly_click');
    gd.removeAllListeners('plotly_legendclick');
    gd.on('plotly_click',ev=>{if(ev.points&&ev.points.length)setCineFiltro(ev.points[0].data.name);});
    gd.on('plotly_legendclick',data=>{setCineFiltro(gd.data[data.curveNumber].name);return false;});
  });
}

function plotAcumuladoCINE(id, rows) {
  if(!_cineInit) initCINE();
  renderCineChart(rows);
}

function cineAdd() {
  const inp=document.getElementById('cine-search'); if(!inp) return;
  const val=inp.value.trim();
  if(!val||_cineActive.includes(val)||!_cineAll.includes(val)){inp.value='';return;}
  _cineActive.push(val);
  inp.value='';
  renderCineChart(filtered);
}

function cineRemove(cine) {
  _cineActive=_cineActive.filter(c=>c!==cine);
  renderCineChart(filtered);
}

function plotPeriodos(id, rows) {
  const el=document.getElementById(id); if(!el) return;
  const COL='NÚMERO_PERIODOS_DE_DURACIÓN', PCOL='PERIODICIDAD';
  const PCOLORS=['#2d5b9e','#fcc10e','#bd900b','#ae1e22','#6e91b9',
                 '#214174','#d56f18','#948e56','#15284b','#7a1518'];
  const pivot={}, periSet=new Set();
  rows.forEach(r=>{
    const v=r[COL]; if(!v||String(v).trim()==='') return;
    const k=Math.round(parseFloat(v)); if(isNaN(k)) return;
    const p=(r[PCOL]||'Sin definir').trim()||'Sin definir';
    if(!pivot[k]) pivot[k]={};
    pivot[k][p]=(pivot[k][p]||0)+1;
    periSet.add(p);
  });
  const labels=Object.keys(pivot).map(Number).sort((a,b)=>a-b);
  if(!labels.length){ _emptyChart(el); return; }
  const peris=[...periSet].sort((a,b)=>{
    const ta=labels.reduce((s,l)=>s+(pivot[l][a]||0),0);
    const tb=labels.reduce((s,l)=>s+(pivot[l][b]||0),0);
    return tb-ta;
  });
  const traces=peris.map((p,i)=>({
    x:labels, y:labels.map(l=>pivot[l][p]||0), name:p, type:'bar',
    marker:{color:PCOLORS[i%PCOLORS.length],opacity:.85},
    hovertemplate:p+'<br>%{x} periodos — <b>%{y:,}</b> programas<extra></extra>'
  }));
  Plotly.react(id, traces, {
    barmode:'stack',
    margin:{t:10,r:20,b:90,l:60},
    xaxis:{title:'Periodos',tickmode:'array',tickvals:labels,tickfont:{size:11}},
    yaxis:{title:'N. Programas',showgrid:true,gridcolor:'#e2e8f0',tickfont:{size:11}},
    plot_bgcolor:'white',paper_bgcolor:'white',bargap:.25,
    legend:{orientation:'h',y:-0.28,font:{size:11},entrywidth:120,entrywidthmode:'pixels'},
    hovermode:'x unified'
  }, PC).then(gd=>{
    gd.removeAllListeners('plotly_click');
    gd.on('plotly_click', ev=>setPeriodosDetalleFilter(ev.points[0].x));
  });
}

let _periodosDet=null;

function _applySubFilters(rows) {
  let r=rows;
  if(_periodosDet!==null){
    const COL='NÚMERO_PERIODOS_DE_DURACIÓN';
    r=r.filter(x=>{const v=x[COL];return v&&Math.round(parseFloat(String(v)))===_periodosDet;});
  }
  return r;
}

function setPeriodosDetalleFilter(val) {
  if(_periodosDet===val){clearPeriodosDetalleFilter();return;}
  _periodosDet=val;
  applyFilters();
  document.getElementById('tbl-wrap').scrollIntoView({behavior:'smooth'});
}

function clearPeriodosDetalleFilter() {
  _periodosDet=null;
  applyFilters();
}

function setCineFiltro(cine) {
  const el=document.getElementById('f-cine'); if(!el) return;
  if(el.value===cine){clearCineFiltro();return;}
  el.value=cine;
  applyFilters();
  document.getElementById('tbl-wrap').scrollIntoView({behavior:'smooth'});
}

function clearCineFiltro() {
  const el=document.getElementById('f-cine'); if(el) el.value='';
  applyFilters();
}

function plotTipoCambio(id, rows) {
  const el=document.getElementById(id); if(!el) return;
  const c={};
  rows.forEach(r => { (r['QUE_CAMBIO']||'').split(' | ').forEach(p => { const f=p.split(':')[0].trim(); if(f&&f!=='nan'&&f!=='') c[f]=(c[f]||0)+1; }); });
  const d=Object.entries(c).sort((a,b)=>b[1]-a[1]); if(!d.length){ _emptyChart(el); return; }
  Plotly.react(id,[{x:d.map(e=>e[0]),y:d.map(e=>e[1]),type:'bar',
    marker:{color:'#bd900b',opacity:.85},
    hovertemplate:'%{x}<br><b>%{y:,}</b> cambios<extra></extra>'}],
    {margin:{t:10,r:20,b:80,l:50},
    xaxis:{tickfont:{size:11},tickangle:-20},
    yaxis:{showgrid:true,gridcolor:'#e2e8f0'},
    plot_bgcolor:'white',paper_bgcolor:'white',bargap:.4},PC);
}

function plotScatter(id, rows) {
  const el=document.getElementById(id); if(!el) return;
  const pts=rows.map(r=>({
    x:parseFloat(r['NÚMERO_CRÉDITOS_ANTERIOR']),
    y:parseFloat(r['NÚMERO_CRÉDITOS']),
    t:r['NOMBRE_DEL_PROGRAMA']||''
  })).filter(p=>!isNaN(p.x)&&!isNaN(p.y)&&p.x!==p.y);
  if(!pts.length){ _emptyChart(el, 'Sin datos de creditos para comparar'); return; }
  const vals=pts.flatMap(p=>[p.x,p.y]);
  const mn=Math.min(...vals), mx=Math.max(...vals);
  Plotly.react(id,[
    {x:pts.map(p=>p.x),y:pts.map(p=>p.y),text:pts.map(p=>p.t),
     mode:'markers',type:'scatter',
     marker:{color:'#bd900b',size:8,opacity:.7},
     hovertemplate:'<b>%{text}</b><br>Antes: %{x} creditos<br>Despues: %{y} creditos<extra></extra>'},
    {x:[mn,mx],y:[mn,mx],mode:'lines',
     line:{color:'#9fb0c9',width:1,dash:'dot'},hoverinfo:'skip',showlegend:false}
  ],{margin:{t:10,r:20,b:50,l:60},
    xaxis:{title:'Creditos anteriores',showgrid:true,gridcolor:'#e2e8f0'},
    yaxis:{title:'Creditos actuales',showgrid:true,gridcolor:'#e2e8f0'},
    plot_bgcolor:'white',paper_bgcolor:'white'},PC);
}

// ── Table ──────────────────────────────────────────────────────────────────
const COL_HEAD = {
  'FECHA_OBTENCION':'Fecha','CÓDIGO_SNIES_DEL_PROGRAMA':'Cód. SNIES',
  'NOMBRE_DEL_PROGRAMA':'Programa','NOMBRE_INSTITUCIÓN':'Institución',
  'SECTOR':'Sector','MODALIDAD':'Modalidad',
  'DEPARTAMENTO_OFERTA_PROGRAMA':'Departamento','MUNICIPIO_OFERTA_PROGRAMA':'Municipio',
  'NÚMERO_CRÉDITOS':'Créditos','COSTO_MATRÍCULA_ESTUD_NUEVOS':'Costo matrícula',
  'PERIODICIDAD':'Periodicidad','DIVISIÓN UNINORTE':'División Uninorte',
  'QUE_CAMBIO':'¿Qué cambió?','NÚMERO_CRÉDITOS_ANTERIOR':'Créd. anteriores'
};
const TBL_COLS = CFG.cols;

function buildTbl(rows) {
  const cols = TBL_COLS.filter(c => !rows.length || c in rows[0]);
  let h = '<table><thead><tr>';
  cols.forEach(c => {
    h += '<th onclick="sortTbl(\'' + c.replace(/'/g,"\\'") + '\')">'+(COL_HEAD[c]||c)+' <span style="opacity:.4">↕</span></th>';
  });
  h += '</tr></thead><tbody>';
  if (!rows.length) {
    h += '<tr><td colspan="'+cols.length+'" class="empty">Sin registros para los filtros seleccionados</td></tr>';
  } else {
    rows.forEach(r => {
      h += '<tr>' + cols.map(c => '<td>'+(r[c]||'')+'</td>').join('') + '</tr>';
    });
  }
  return h + '</tbody></table>';
}

function renderTbl(rows) {
  document.getElementById('tbl-wrap').innerHTML = buildTbl(rows);
}

function sortTbl(col) {
  sortDir[col] = !sortDir[col];
  filtered = [...filtered].sort((a,b) => {
    const va=a[col]||'', vb=b[col]||'';
    const cmp = String(va).localeCompare(String(vb),'es',{numeric:true});
    return sortDir[col] ? cmp : -cmp;
  });
  renderTbl(_applySubFilters(filtered));
}

// ── Render all ─────────────────────────────────────────────────────────────
function renderAll(rows) {
  const subRows=_applySubFilters(rows);
  const cpd=document.getElementById('per-det-chip');
  const ccd=document.getElementById('cine-det-chip');
  if(cpd){
    cpd.style.display=_periodosDet!==null?'flex':'none';
    if(_periodosDet!==null) document.getElementById('per-det-val').textContent=
      _periodosDet+' periodos — '+subRows.length.toLocaleString('es-CO')+' programas';
  }
  const cineFiltroVal=gv('f-cine');
  if(ccd){
    ccd.style.display=cineFiltroVal?'flex':'none';
    if(cineFiltroVal) document.getElementById('cine-det-val').textContent=
      cineFiltroVal+' — '+subRows.length.toLocaleString('es-CO')+' programas';
  }
  document.getElementById('f-count').textContent = fmt(subRows.length) + ' programas';

  plotDonut('ch-sector', rows, 'SECTOR');
  plotHBar('ch-instituciones', rows, 'NOMBRE_INSTITUCIÓN', C, 10, 32);
  plotHBar('ch-division',      rows, 'DIVISIÓN UNINORTE',  C, 12);
  plotHBar('ch-depto',         rows, 'DEPARTAMENTO_OFERTA_PROGRAMA', '#214174', 15);

  if (CFG.tipo === 'modificados') {
    plotTipoCambio('ch-tipo-cambio', rows);
    plotScatter('ch-scatter', rows);
    plotTimeline('ch-timeline', rows);
  } else if (CFG.tipo === 'nuevos' || CFG.tipo === 'inactivos') {
    plotVBar('ch-modalidad', rows, 'MODALIDAD', C);
    plotAcumuladoCINE('ch-timeline', rows);
    plotPeriodos('ch-periodos', rows);
  } else {
    plotVBar('ch-modalidad', rows, 'MODALIDAD', C);
    plotAcumuladoModalidad('ch-timeline', rows);
  }

  renderTbl(subRows);
}

// ── Init ───────────────────────────────────────────────────────────────────
applyFilters();
</script>
</body>
</html>
"""

# ── pagina dedicada: analisis de creditos ─────────────────────────────────────

CREDITOS_TEMPLATE = r"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Analisis de Creditos . SNIES Monitor</title>
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js" charset="utf-8"></script>
<style>
:root{
  --bg:#f1f5f9;--surface:#fff;--text:#0f172a;--muted:#64748b;
  --border:#e2e8f0;--blue:#2d5b9e;--green:#1a9e6b;--red:#ae1e22;--amber:#bd900b;
  --radius:0.75rem;
}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Segoe UI',system-ui,sans-serif;background:var(--bg);color:var(--text);font-size:14px}
header{background:linear-gradient(135deg,#15284b,#bd900b);color:#fff;
  padding:1.2rem 2rem;display:flex;justify-content:space-between;align-items:center;gap:1rem;flex-wrap:wrap}
header h1{font-size:1.25rem;font-weight:700}
header .sub{font-size:.77rem;opacity:.75;margin-top:.2rem}
.back-btn{display:inline-flex;align-items:center;gap:.3rem;background:rgba(255,255,255,.2);
  border:1px solid rgba(255,255,255,.35);color:#fff;text-decoration:none;padding:.38rem .85rem;
  border-radius:.4rem;font-size:.8rem;font-weight:500;white-space:nowrap;transition:background .15s}
.back-btn:hover{background:rgba(255,255,255,.32)}
.filter-bar{position:sticky;top:0;z-index:100;background:var(--surface);
  border-bottom:1px solid var(--border);padding:.6rem 2rem;
  display:flex;gap:.45rem;flex-wrap:wrap;align-items:center;
  box-shadow:0 2px 8px rgba(0,0,0,.06)}
.f-input{flex:1;min-width:200px;padding:.5rem .8rem;border:1px solid var(--border);
  border-radius:.4rem;font-size:.8rem;outline:none}
.f-input:focus{border-color:var(--blue)}
.f-sel{padding:.4rem .6rem;border:1px solid var(--border);border-radius:.4rem;
  font-size:.77rem;background:var(--surface);outline:none;cursor:pointer;max-width:200px}
.f-btn{padding:.4rem .85rem;border:1px solid var(--border);border-radius:.4rem;
  font-size:.77rem;background:var(--surface);cursor:pointer;color:var(--muted);white-space:nowrap}
.f-btn:hover{background:var(--bg)}
.f-count{margin-left:auto;font-size:.82rem;font-weight:600;color:var(--blue);white-space:nowrap}
.ac-wrap{position:relative;flex:0 1 240px}
.ac-menu{position:absolute;top:calc(100% + 2px);left:0;right:0;z-index:300;
  background:var(--surface);border:1px solid var(--border);border-radius:.4rem;
  box-shadow:0 8px 20px rgba(0,0,0,.14);max-height:260px;overflow-y:auto;display:none}
.ac-menu.show{display:block}
.ac-item{padding:.45rem .75rem;font-size:.78rem;cursor:pointer;color:var(--text)}
.ac-item:hover{background:var(--bg)}
.ac-empty{padding:.45rem .75rem;font-size:.78rem;color:var(--muted)}
main{max-width:1380px;margin:0 auto;padding:1.5rem 2rem}
section{margin-bottom:1.25rem}
.kpi-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:1rem}
.kpi{background:var(--surface);border-radius:var(--radius);padding:1.1rem 1.4rem;
  box-shadow:0 1px 3px rgba(0,0,0,.07);border-left:4px solid var(--blue)}
.kpi.r{border-left-color:var(--red)}.kpi.g{border-left-color:var(--green)}.kpi.a{border-left-color:var(--amber)}
.kpi-label{font-size:.68rem;text-transform:uppercase;letter-spacing:.05em;color:var(--muted);margin-bottom:.4rem}
.kpi-val{font-size:1.8rem;font-weight:700;line-height:1}
.kpi-sub{font-size:.7rem;color:var(--muted);margin-top:.35rem}
.card{background:var(--surface);border-radius:var(--radius);padding:1.2rem;
  box-shadow:0 1px 3px rgba(0,0,0,.07);margin-bottom:1rem}
.ct{font-size:.68rem;font-weight:600;text-transform:uppercase;letter-spacing:.06em;
  color:var(--muted);margin-bottom:.85rem}
.ct-note{font-size:.74rem;color:var(--muted);margin-top:-.5rem;margin-bottom:.75rem;line-height:1.4}
.g2{display:grid;grid-template-columns:1fr 1fr;gap:1rem}
.tbl-wrap{max-height:480px;overflow-y:auto;border:1px solid var(--border);border-radius:.5rem}
table{width:100%;border-collapse:collapse;font-size:.77rem}
th{background:var(--bg);padding:.6rem .85rem;text-align:left;font-size:.67rem;
  text-transform:uppercase;letter-spacing:.05em;color:var(--muted);cursor:pointer;
  user-select:none;position:sticky;top:0;z-index:1;white-space:nowrap}
th:hover{background:#e2e8f0}
td{padding:.6rem .85rem;border-bottom:1px solid var(--border);vertical-align:top;
  max-width:270px;word-break:break-word}
tr:last-child td{border-bottom:none}
tr:hover td{background:#f8fafc}
.delta-up{color:var(--green);font-weight:600}
.delta-down{color:var(--red);font-weight:600}
.empty{text-align:center;color:var(--muted);padding:2.5rem}
@media(max-width:900px){
  .kpi-grid{grid-template-columns:repeat(2,1fr)}
  .g2{grid-template-columns:1fr}
  main{padding:1rem}
  header{flex-direction:column;text-align:center}
  .f-count{margin-left:0}
}
</style>
</head>
<body>
<header>
  <div style="display:flex;align-items:center;gap:.9rem">
    <a href="modificados.html" class="back-btn">← Modificados</a>
    <div>
      <h1>📐 Analisis de Creditos</h1>
      <div class="sub">Que cambia cuando un programa modifica su numero de creditos</div>
    </div>
  </div>
  <a href="modificados_costos.html" class="back-btn">💰 Analisis de Costos →</a>
</header>

<div class="filter-bar">
  <input id="f-q" class="f-input" placeholder="Buscar por nombre, institucion, departamento... (filtra TODA la pagina)" oninput="applyFilters()">
  <select id="f-sector" class="f-sel" onchange="applyFilters()"><option value="">Todos los sectores</option></select>
  <select id="f-depto"  class="f-sel" onchange="applyFilters()"><option value="">Todos los departamentos</option></select>
  <div class="ac-wrap">
    <input id="f-institucion" class="f-sel" placeholder="Buscar institucion..." style="cursor:text;width:100%" oninput="applyFilters()">
    <div class="ac-menu" id="f-institucion-menu"></div>
  </div>
  <button class="f-btn" onclick="resetFilters()">✕ Limpiar</button>
  <span class="f-count" id="f-count">–</span>
</div>

<main>
  <section class="kpi-grid">
    <div class="kpi">
      <div class="kpi-label">Cambios de creditos detectados</div>
      <div class="kpi-val" id="k-total">–</div>
      <div class="kpi-sub">programas con creditos antes/despues distintos</div>
    </div>
    <div class="kpi g">
      <div class="kpi-label">delta promedio . Oficial</div>
      <div class="kpi-val" id="k-oficial">–</div>
      <div class="kpi-sub" id="k-oficial-sub">creditos por cambio</div>
    </div>
    <div class="kpi r">
      <div class="kpi-label">delta promedio . Privado</div>
      <div class="kpi-val" id="k-privado">–</div>
      <div class="kpi-sub" id="k-privado-sub">creditos por cambio</div>
    </div>
    <div class="kpi a">
      <div class="kpi-label">Tambien cambia la duracion</div>
      <div class="kpi-val" id="k-cocambio">–</div>
      <div class="kpi-sub" id="k-cocambio-sub">vs. tasa general</div>
    </div>
  </section>
  <div class="ct-note" style="margin:-.5rem 0 1rem">
    "delta promedio" = cambio promedio en numero de creditos (creditos despues - creditos antes) entre los programas
    modificados de ese grupo. <strong>Negativo</strong> significa que, en promedio, le quitan creditos al programa;
    <strong>positivo</strong>, que le agregan.
  </div>

  <section class="g2">
    <div class="card">
      <div class="ct">Sube vs. baja, por sector</div>
      <div id="ch-sector" style="height:280px"></div>
    </div>
    <div class="card">
      <div class="ct">Distribucion del cambio (creditos ganados/perdidos)</div>
      <div id="ch-hist" style="height:280px"></div>
    </div>
  </section>

  <section class="g2">
    <div class="card">
      <div class="ct">Top instituciones que mas cambian creditos</div>
      <div class="ct-note">Numero al lado de la barra: delta promedio de esa institucion (ver definicion arriba).</div>
      <div id="ch-instituciones" style="height:380px"></div>
    </div>
    <div class="card">
      <div class="ct">Top departamentos que mas cambian creditos</div>
      <div class="ct-note">Numero al lado de la barra: delta promedio de ese departamento (ver definicion arriba).</div>
      <div id="ch-departamentos" style="height:380px"></div>
    </div>
  </section>

  <section class="card">
    <div class="ct">Por campo CINE: que programas suben o bajan creditos</div>
    <div class="ct-note">Filtra por institucion arriba para ver el detalle de su oferta. Cada barra es un campo
      CINE; el valor es el balance neto de creditos ganados/perdidos entre los programas de ese campo
      (suma de los deltas). Verde = el campo gana creditos en neto; rojo = los pierde.</div>
    <div id="ch-cine-delta" style="height:420px"></div>
  </section>

  <section class="card">
    <div class="ct">Cuando cambian los creditos, que mas cambia?</div>
    <div class="ct-note">Barra ambar = entre los programas <strong>con</strong> cambio de creditos, que % tambien
      cambio ese campo. Barra gris = tasa base: que % cambia ese campo entre TODOS los programas modificados
      visibles con los filtros actuales (con o sin cambio de creditos) - es el punto de comparacion.</div>
    <div id="ch-cocambios" style="height:300px"></div>
  </section>

  <section class="card">
    <div class="ct">Creditos: antes -&gt; despues (coloreado por sector)</div>
    <div id="ch-scatter" style="height:380px"></div>
  </section>

  <section class="card">
    <div class="ct">Registros con cambio de creditos</div>
    <div class="tbl-wrap" id="tbl-wrap"></div>
  </section>
</main>

<script>
const D = __DATA__;
const PC = {responsive:true, displayModeBar:false};
const fmt = n => (n ?? 0).toLocaleString('es-CO');
const _norm = s => String(s==null?'':s).normalize('NFD').replace(/[\u0300-\u036f]/g,'').toLowerCase();
function _rowMatches(r, tokens) {
  if (!tokens.length) return true;
  const hay = _norm(Object.values(r).join(' '));
  return tokens.every(t => hay.includes(t));
}

function _emptyChart(id, msg) {
  const el = document.getElementById(id); if (!el) return;
  Plotly.purge(el);
  el.innerHTML = '<div style="display:flex;align-items:center;justify-content:center;height:100%;color:#64748b;font-size:.82rem">' + (msg || 'Sin datos para los filtros aplicados') + '</div>';
}

function agruparPorCampo(rows, field) {
  const m = new Map();
  rows.forEach(r => {
    const k = r[field]; if (!k) return;
    if (!m.has(k)) m.set(k, []);
    m.get(k).push(r);
  });
  return m;
}

function resumenGrupo(rows) {
  const n = rows.length;
  const suben = rows.filter(r => r._delta > 0).length;
  const bajan = rows.filter(r => r._delta < 0).length;
  const promedio = n ? rows.reduce((s, r) => s + r._delta, 0) / n : 0;
  return {n, suben, bajan, promedio_delta: Math.round(promedio * 10) / 10};
}

function ranking(rows, field, topN) {
  const m = agruparPorCampo(rows, field);
  const out = [...m.entries()].map(([nombre, g]) => ({nombre, ...resumenGrupo(g)}));
  out.sort((a, b) => b.n - a.n);
  return out.slice(0, topN);
}

const BUCKETS_DELTA = [
  {min: -Infinity, max: -30,      label: '≤ -30'},
  {min: -29,       max: -10,      label: '-29 a -10'},
  {min: -9,        max: -1,       label: '-9 a -1'},
  {min: 0,         max: 0,        label: '0'},
  {min: 1,         max: 9,        label: '1 a 9'},
  {min: 10,        max: 29,       label: '10 a 29'},
  {min: 30,        max: Infinity, label: '≥ 30'},
];

function binDeltas(rows) {
  const counts = BUCKETS_DELTA.map(b => rows.filter(r => r._delta >= b.min && r._delta <= b.max).length);
  const colors = BUCKETS_DELTA.map(b => b.max < 0 ? '#ae1e22' : b.min > 0 ? '#1a9e6b' : '#94a3b8');
  return {labels: BUCKETS_DELTA.map(b => b.label), counts, colors};
}

const CAMPOS_COCAMBIO = [
  {flag: '_cambia_periodo',   label: 'Duracion (periodos)'},
  {flag: '_cambia_costo',     label: 'Costo de matricula'},
  {flag: '_cambia_modalidad', label: 'Modalidad'},
  {flag: '_cambia_municipio', label: 'Municipio'},
];

function calcularCoCambios(filtrados, creditRows) {
  return CAMPOS_COCAMBIO.map(({flag, label}) => {
    const conCredito = creditRows.filter(r => r[flag] !== null);
    const tasaConCredito = conCredito.length
      ? Math.round(1000 * conCredito.filter(r => r[flag] === true).length / conCredito.length) / 10
      : 0;
    const baseValidos = filtrados.filter(r => r[flag] !== null);
    const tasaBase = baseValidos.length
      ? Math.round(1000 * baseValidos.filter(r => r[flag] === true).length / baseValidos.length) / 10
      : 0;
    return {campo: label, n_con_dato: conCredito.length, tasa_con_cambio_credito: tasaConCredito, tasa_base: tasaBase};
  });
}

function renderSector(porSector) {
  if (!porSector.length) { _emptyChart('ch-sector'); return; }
  const labels = porSector.map(s => s.nombre);
  Plotly.react('ch-sector', [
    {x: labels, y: porSector.map(s => s.suben), name: 'Suben', type: 'bar',
     marker: {color: '#1a9e6b', opacity: .85}},
    {x: labels, y: porSector.map(s => s.bajan), name: 'Bajan', type: 'bar',
     marker: {color: '#ae1e22', opacity: .85}},
  ], {
    barmode: 'group', margin: {t:10,r:10,b:30,l:45},
    yaxis: {showgrid: true, gridcolor: '#e2e8f0'},
    plot_bgcolor: 'white', paper_bgcolor: 'white',
    legend: {orientation: 'h', y: -0.18}
  }, PC);
}

function renderHist(creditRows) {
  const h = binDeltas(creditRows);
  if (!h.counts.some(c => c > 0)) { _emptyChart('ch-hist'); return; }
  Plotly.react('ch-hist', [{
    x: h.labels, y: h.counts, type: 'bar',
    marker: {color: h.colors, opacity: .85},
    hovertemplate: 'Rango: %{x} creditos<br><b>%{y}</b> programas<extra></extra>'
  }], {
    margin: {t:10,r:10,b:45,l:45},
    xaxis: {title: 'Delta creditos (despues - antes)', tickfont: {size: 11}},
    yaxis: {title: 'N. programas', showgrid: true, gridcolor: '#e2e8f0'},
    plot_bgcolor: 'white', paper_bgcolor: 'white', bargap: .15
  }, PC);
}

function renderRanking(id, data) {
  if (!data.length) { _emptyChart(id); return; }
  const d = [...data].slice(0, 12).reverse();
  const trunc = s => s.length > 36 ? s.slice(0, 36) + '...' : s;
  const maxN = Math.max(...d.map(r => r.n));
  Plotly.react(id, [{
    y: d.map(r => trunc(r.nombre)), x: d.map(r => r.n), customdata: d.map(r => r.nombre),
    type: 'bar', orientation: 'h', marker: {color: '#bd900b', opacity: .85},
    text: d.map(r => `${r.promedio_delta > 0 ? '+' : ''}${r.promedio_delta}`),
    textposition: 'outside', cliponaxis: false,
    textfont: {size: 10, color: '#7a5d06'},
    hovertemplate: '%{customdata}<br><b>%{x}</b> cambios<extra></extra>'
  }], {
    margin: {t:10,r:60,b:30,l:230},
    xaxis: {showgrid: true, gridcolor: '#e2e8f0', range: [0, maxN * 1.35]},
    yaxis: {tickfont: {size: 10}},
    plot_bgcolor: 'white', paper_bgcolor: 'white', bargap: .3
  }, PC);
}

function renderCineDelta(creditRows) {
  const CINE_COL = 'CINE_F_2013_AC_CAMPO_ESPECÍFIC';
  const m = agruparPorCampo(creditRows, CINE_COL);
  const data = [...m.entries()].map(([campo, rows]) => ({
    campo,
    n: rows.length,
    suben: rows.filter(r => r._delta > 0).length,
    bajan: rows.filter(r => r._delta < 0).length,
    neto: rows.reduce((s, r) => s + r._delta, 0),
  }));
  data.sort((a, b) => Math.abs(b.neto) - Math.abs(a.neto));
  const top = data.slice(0, 20).reverse();
  if (!top.length) { _emptyChart('ch-cine-delta'); return; }
  const trunc = s => s.length > 42 ? s.slice(0, 42) + '...' : s;
  Plotly.react('ch-cine-delta', [{
    y: top.map(d => trunc(d.campo)), x: top.map(d => d.neto), customdata: top,
    type: 'bar', orientation: 'h',
    marker: {color: top.map(d => d.neto >= 0 ? '#1a9e6b' : '#ae1e22'), opacity: .85},
    text: top.map(d => (d.neto > 0 ? '+' : '') + d.neto),
    textposition: 'outside', cliponaxis: false, textfont: {size: 10},
    hovertemplate: '%{y}<br>Balance neto: <b>%{x}</b> creditos' +
      '<br>%{customdata.suben} suben / %{customdata.bajan} bajan (%{customdata.n} programas)<extra></extra>'
  }], {
    margin: {t:10,r:50,b:40,l:270},
    xaxis: {title: 'Balance neto de creditos (suma de deltas)', zeroline: true, zerolinecolor: '#94a3b8',
      showgrid: true, gridcolor: '#e2e8f0'},
    yaxis: {tickfont: {size: 10}},
    plot_bgcolor: 'white', paper_bgcolor: 'white', bargap: .3
  }, PC);
}

function renderCoCambios(coCambios) {
  if (!coCambios.length) { _emptyChart('ch-cocambios'); return; }
  const labels = coCambios.map(c => c.campo);
  Plotly.react('ch-cocambios', [
    {x: labels, y: coCambios.map(c => c.tasa_con_cambio_credito), name: 'Cuando cambian creditos',
     type: 'bar', marker: {color: '#bd900b', opacity: .9},
     text: coCambios.map(c => c.tasa_con_cambio_credito + '%'), textposition: 'outside', cliponaxis: false},
    {x: labels, y: coCambios.map(c => c.tasa_base), name: 'Tasa general (control)',
     type: 'bar', marker: {color: '#94a3b8', opacity: .9},
     text: coCambios.map(c => c.tasa_base + '%'), textposition: 'outside', cliponaxis: false},
  ], {
    barmode: 'group', margin: {t:30,r:10,b:50,l:50},
    yaxis: {title: '% de los casos', showgrid: true, gridcolor: '#e2e8f0', range: [0, 100]},
    plot_bgcolor: 'white', paper_bgcolor: 'white',
    legend: {orientation: 'h', y: -0.25}
  }, PC);
}

function renderScatter(creditRows) {
  if (!creditRows.length) { _emptyChart('ch-scatter'); return; }
  const porSector = {};
  creditRows.forEach(p => { (porSector[p.SECTOR] = porSector[p.SECTOR] || []).push(p); });
  const colores = {Oficial: '#2d5b9e', Privado: '#bd900b'};
  const vals = creditRows.flatMap(p => [p._cred_antes, p._cred_despues]);
  const mn = Math.min(...vals), mx = Math.max(...vals);
  const traces = Object.entries(porSector).map(([sector, pts]) => ({
    x: pts.map(p => p._cred_antes), y: pts.map(p => p._cred_despues),
    text: pts.map(p => p['NOMBRE_INSTITUCIÓN'] + ' - ' + p['NOMBRE_DEL_PROGRAMA']),
    mode: 'markers', type: 'scatter', name: sector,
    marker: {color: colores[sector] || '#64748b', size: 7, opacity: .65},
    hovertemplate: '<b>%{text}</b><br>Antes: %{x} creditos<br>Despues: %{y} creditos<extra></extra>'
  }));
  traces.push({x: [mn, mx], y: [mn, mx], mode: 'lines', line: {color: '#9fb0c9', width: 1, dash: 'dot'},
    hoverinfo: 'skip', showlegend: false});
  Plotly.react('ch-scatter', traces, {
    margin: {t:10,r:20,b:50,l:60},
    xaxis: {title: 'Creditos antes', showgrid: true, gridcolor: '#e2e8f0'},
    yaxis: {title: 'Creditos despues', showgrid: true, gridcolor: '#e2e8f0'},
    plot_bgcolor: 'white', paper_bgcolor: 'white',
    legend: {orientation: 'h', y: -0.2}
  }, PC);
}

const COL_HEAD = {
  FECHA_OBTENCION: 'Fecha', 'CODIGO_SNIES_DEL_PROGRAMA': 'Cod. SNIES', NOMBRE_DEL_PROGRAMA: 'Programa',
  'NOMBRE_INSTITUCIÓN': 'Institucion', SECTOR: 'Sector', DEPARTAMENTO_OFERTA_PROGRAMA: 'Departamento',
  'DIVISION UNINORTE': 'Division', _cred_antes: 'Cred. antes', _cred_despues: 'Cred. despues',
  _delta: 'Delta', QUE_CAMBIO: 'Que mas cambio?'
};
const TBL_COLS = ['FECHA_OBTENCION', 'NOMBRE_DEL_PROGRAMA', 'NOMBRE_INSTITUCIÓN', 'SECTOR',
  'DEPARTAMENTO_OFERTA_PROGRAMA', '_cred_antes', '_cred_despues', '_delta', 'QUE_CAMBIO'];
let sortDir = {};
let tablaRows = [];

function buildTbl(rows) {
  const cols = TBL_COLS.filter(c => !rows.length || c in rows[0]);
  let h = '<table><thead><tr>';
  cols.forEach(c => { h += '<th onclick="sortTbl(\'' + c + '\')">' + (COL_HEAD[c] || c) + ' <span style="opacity:.4">↕</span></th>'; });
  h += '</tr></thead><tbody>';
  if (!rows.length) {
    h += '<tr><td colspan="' + cols.length + '" class="empty">Sin registros para los filtros seleccionados</td></tr>';
  } else {
    rows.forEach(r => {
      h += '<tr>' + cols.map(c => {
        if (c === '_delta') {
          const v = r[c];
          const cls = v > 0 ? 'delta-up' : (v < 0 ? 'delta-down' : '');
          return '<td class="' + cls + '">' + (v > 0 ? '+' : '') + v + '</td>';
        }
        return '<td>' + (r[c] ?? '') + '</td>';
      }).join('') + '</tr>';
    });
  }
  return h + '</tbody></table>';
}

function renderTbl(rows) { tablaRows = rows; document.getElementById('tbl-wrap').innerHTML = buildTbl(rows); }

function sortTbl(col) {
  sortDir[col] = !sortDir[col];
  tablaRows = [...tablaRows].sort((a, b) => {
    const va = a[col] ?? '', vb = b[col] ?? '';
    const na = parseFloat(va), nb = parseFloat(vb);
    const cmp = (!isNaN(na) && !isNaN(nb)) ? na - nb : String(va).localeCompare(String(vb), 'es');
    return sortDir[col] ? cmp : -cmp;
  });
  document.getElementById('tbl-wrap').innerHTML = buildTbl(tablaRows);
}

function uniq(arr) { return [...new Set(arr.filter(v => v && String(v).trim() !== ''))].sort(); }
function addOpts(id, vals) {
  const el = document.getElementById(id); if (!el) return;
  vals.forEach(v => { const o = document.createElement('option'); o.value = o.textContent = v; el.appendChild(o); });
}
function initAutocomplete(inputId, menuId, options, onChange) {
  const inp = document.getElementById(inputId), menu = document.getElementById(menuId);
  if (!inp || !menu) return;
  function render() {
    const q = _norm(inp.value).trim();
    const matches = (q ? options.filter(o => _norm(o).includes(q)) : options).slice(0, 50);
    menu.innerHTML = matches.length
      ? matches.map(o => '<div class="ac-item">' + o.replace(/&/g,'&amp;').replace(/</g,'&lt;') + '</div>').join('')
      : '<div class="ac-empty">Sin coincidencias</div>';
    menu.classList.add('show');
  }
  inp.addEventListener('focus', render);
  inp.addEventListener('input', () => { render(); onChange(); });
  menu.addEventListener('mousedown', e => {
    const it = e.target.closest('.ac-item'); if (!it) return;
    e.preventDefault();
    inp.value = it.textContent;
    menu.classList.remove('show');
    onChange();
  });
  document.addEventListener('click', e => {
    if (e.target !== inp && !menu.contains(e.target)) menu.classList.remove('show');
  });
}
addOpts('f-sector', uniq(D.universo.map(r => r['SECTOR'])));
addOpts('f-depto',  uniq(D.universo.map(r => r['DEPARTAMENTO_OFERTA_PROGRAMA'])));
initAutocomplete('f-institucion', 'f-institucion-menu', uniq(D.universo.map(r => r['NOMBRE_INSTITUCIÓN'])), applyFilters);

function gv(id) { const el = document.getElementById(id); return el ? el.value : ''; }

function applyFilters() {
  const qTokens = _norm(gv('f-q')).split(/\s+/).filter(Boolean);
  const se = gv('f-sector'), de = gv('f-depto');
  const insTokens = _norm(gv('f-institucion')).split(/\s+/).filter(Boolean);

  const filtrados = D.universo.filter(r => {
    if (!_rowMatches(r, qTokens)) return false;
    if (se && r['SECTOR'] !== se) return false;
    if (de && r['DEPARTAMENTO_OFERTA_PROGRAMA'] !== de) return false;
    if (insTokens.length) {
      const hayIns = _norm(r['NOMBRE_INSTITUCIÓN']);
      if (!insTokens.every(t => hayIns.includes(t))) return false;
    }
    return true;
  });
  const creditRows = filtrados.filter(r => r._cambia_credito);

  document.getElementById('f-count').textContent = fmt(creditRows.length) + ' cambios de creditos (' + fmt(filtrados.length) + ' programas modificados en total)';
  document.getElementById('k-total').textContent = fmt(creditRows.length);

  const porSectorAgg = ranking(creditRows, 'SECTOR', 10).sort((a, b) => a.nombre.localeCompare(b.nombre));
  const sOficial = porSectorAgg.find(s => s.nombre === 'Oficial');
  const sPrivado = porSectorAgg.find(s => s.nombre === 'Privado');
  document.getElementById('k-oficial').textContent = sOficial ? (sOficial.promedio_delta > 0 ? '+' : '') + sOficial.promedio_delta : '-';
  document.getElementById('k-oficial-sub').textContent = sOficial ? `${sOficial.suben} suben / ${sOficial.bajan} bajan` : 'sin datos';
  document.getElementById('k-privado').textContent = sPrivado ? (sPrivado.promedio_delta > 0 ? '+' : '') + sPrivado.promedio_delta : '-';
  document.getElementById('k-privado-sub').textContent = sPrivado ? `${sPrivado.suben} suben / ${sPrivado.bajan} bajan` : 'sin datos';

  const coCambios = calcularCoCambios(filtrados, creditRows);
  const coDuracion = coCambios.find(c => c.campo.includes('Duracion'));
  document.getElementById('k-cocambio').textContent = coDuracion ? coDuracion.tasa_con_cambio_credito + '%' : '-';
  document.getElementById('k-cocambio-sub').textContent = coDuracion ? `vs. ${coDuracion.tasa_base}% tasa general` : '';

  renderSector(porSectorAgg);
  renderHist(creditRows);
  renderRanking('ch-instituciones', ranking(creditRows, 'NOMBRE_INSTITUCIÓN', 20));
  renderRanking('ch-departamentos', ranking(creditRows, 'DEPARTAMENTO_OFERTA_PROGRAMA', 20));
  renderCineDelta(creditRows);
  renderCoCambios(coCambios);
  renderScatter(creditRows);
  renderTbl(creditRows);
}

function resetFilters() {
  ['f-q', 'f-sector', 'f-depto', 'f-institucion'].forEach(id => { const el = document.getElementById(id); if (el) el.value = ''; });
  applyFilters();
}

applyFilters();
</script>
</body>
</html>
"""

COSTOS_TEMPLATE = r"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Analisis de Costos de Matricula . SNIES Monitor</title>
<script src="https://cdn.plot.ly/plotly-2.35.2.min.js" charset="utf-8"></script>
<style>
:root{
  --bg:#f1f5f9;--surface:#fff;--text:#0f172a;--muted:#64748b;
  --border:#e2e8f0;--blue:#2d5b9e;--green:#1a9e6b;--red:#ae1e22;--amber:#bd900b;
  --radius:0.75rem;
}
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'Segoe UI',system-ui,sans-serif;background:var(--bg);color:var(--text);font-size:14px}
header{background:linear-gradient(135deg,#15284b,#1a9e6b);color:#fff;
  padding:1.2rem 2rem;display:flex;justify-content:space-between;align-items:center;gap:1rem;flex-wrap:wrap}
header h1{font-size:1.25rem;font-weight:700}
header .sub{font-size:.77rem;opacity:.75;margin-top:.2rem}
.back-btn{display:inline-flex;align-items:center;gap:.3rem;background:rgba(255,255,255,.2);
  border:1px solid rgba(255,255,255,.35);color:#fff;text-decoration:none;padding:.38rem .85rem;
  border-radius:.4rem;font-size:.8rem;font-weight:500;white-space:nowrap;transition:background .15s}
.back-btn:hover{background:rgba(255,255,255,.32)}
.filter-bar{position:sticky;top:0;z-index:100;background:var(--surface);
  border-bottom:1px solid var(--border);padding:.6rem 2rem;
  display:flex;gap:.45rem;flex-wrap:wrap;align-items:center;
  box-shadow:0 2px 8px rgba(0,0,0,.06)}
.f-input{flex:1;min-width:200px;padding:.5rem .8rem;border:1px solid var(--border);
  border-radius:.4rem;font-size:.8rem;outline:none}
.f-input:focus{border-color:var(--blue)}
.f-sel{padding:.4rem .6rem;border:1px solid var(--border);border-radius:.4rem;
  font-size:.77rem;background:var(--surface);outline:none;cursor:pointer;max-width:200px}
.f-btn{padding:.4rem .85rem;border:1px solid var(--border);border-radius:.4rem;
  font-size:.77rem;background:var(--surface);cursor:pointer;color:var(--muted);white-space:nowrap}
.f-btn:hover{background:var(--bg)}
.f-count{margin-left:auto;font-size:.82rem;font-weight:600;color:var(--blue);white-space:nowrap}
.ac-wrap{position:relative;flex:0 1 240px}
.ac-menu{position:absolute;top:calc(100% + 2px);left:0;right:0;z-index:300;
  background:var(--surface);border:1px solid var(--border);border-radius:.4rem;
  box-shadow:0 8px 20px rgba(0,0,0,.14);max-height:260px;overflow-y:auto;display:none}
.ac-menu.show{display:block}
.ac-item{padding:.45rem .75rem;font-size:.78rem;cursor:pointer;color:var(--text)}
.ac-item:hover{background:var(--bg)}
.ac-empty{padding:.45rem .75rem;font-size:.78rem;color:var(--muted)}
main{max-width:1380px;margin:0 auto;padding:1.5rem 2rem}
section{margin-bottom:1.25rem}
.kpi-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:1rem}
.kpi{background:var(--surface);border-radius:var(--radius);padding:1.1rem 1.4rem;
  box-shadow:0 1px 3px rgba(0,0,0,.07);border-left:4px solid var(--blue)}
.kpi.r{border-left-color:var(--red)}.kpi.g{border-left-color:var(--green)}.kpi.a{border-left-color:var(--amber)}
.kpi-label{font-size:.68rem;text-transform:uppercase;letter-spacing:.05em;color:var(--muted);margin-bottom:.4rem}
.kpi-val{font-size:1.8rem;font-weight:700;line-height:1}
.kpi-sub{font-size:.7rem;color:var(--muted);margin-top:.35rem}
.card{background:var(--surface);border-radius:var(--radius);padding:1.2rem;
  box-shadow:0 1px 3px rgba(0,0,0,.07);margin-bottom:1rem}
.ct{font-size:.68rem;font-weight:600;text-transform:uppercase;letter-spacing:.06em;
  color:var(--muted);margin-bottom:.85rem}
.ct-note{font-size:.74rem;color:var(--muted);margin-top:-.5rem;margin-bottom:.75rem;line-height:1.4}
.g2{display:grid;grid-template-columns:1fr 1fr;gap:1rem}
.tbl-wrap{max-height:480px;overflow-y:auto;border:1px solid var(--border);border-radius:.5rem}
table{width:100%;border-collapse:collapse;font-size:.77rem}
th{background:var(--bg);padding:.6rem .85rem;text-align:left;font-size:.67rem;
  text-transform:uppercase;letter-spacing:.05em;color:var(--muted);cursor:pointer;
  user-select:none;position:sticky;top:0;z-index:1;white-space:nowrap}
th:hover{background:#e2e8f0}
td{padding:.6rem .85rem;border-bottom:1px solid var(--border);vertical-align:top;
  max-width:270px;word-break:break-word}
tr:last-child td{border-bottom:none}
tr:hover td{background:#f8fafc}
.delta-up{color:var(--red);font-weight:600}
.delta-down{color:var(--green);font-weight:600}
.empty{text-align:center;color:var(--muted);padding:2.5rem}
@media(max-width:900px){
  .kpi-grid{grid-template-columns:repeat(2,1fr)}
  .g2{grid-template-columns:1fr}
  main{padding:1rem}
  header{flex-direction:column;text-align:center}
  .f-count{margin-left:0}
}
</style>
</head>
<body>
<header>
  <div style="display:flex;align-items:center;gap:.9rem">
    <a href="modificados.html" class="back-btn">← Modificados</a>
    <div>
      <h1>💰 Analisis de Costos de Matricula</h1>
      <div class="sub">Que cambia cuando un programa modifica el costo de matricula</div>
    </div>
  </div>
  <a href="modificados_creditos.html" class="back-btn">📐 Analisis de Creditos →</a>
</header>

<div class="filter-bar">
  <input id="f-q" class="f-input" placeholder="Buscar por nombre, institucion, departamento... (filtra TODA la pagina)" oninput="applyFilters()">
  <select id="f-sector" class="f-sel" onchange="applyFilters()"><option value="">Todos los sectores</option></select>
  <select id="f-depto"  class="f-sel" onchange="applyFilters()"><option value="">Todos los departamentos</option></select>
  <div class="ac-wrap">
    <input id="f-institucion" class="f-sel" placeholder="Buscar institucion..." style="cursor:text;width:100%" oninput="applyFilters()">
    <div class="ac-menu" id="f-institucion-menu"></div>
  </div>
  <button class="f-btn" onclick="resetFilters()">✕ Limpiar</button>
  <span class="f-count" id="f-count">–</span>
</div>

<main>
  <section class="kpi-grid">
    <div class="kpi">
      <div class="kpi-label">Cambios de costo detectados</div>
      <div class="kpi-val" id="k-total">–</div>
      <div class="kpi-sub">programas con costo antes/despues distinto</div>
    </div>
    <div class="kpi r">
      <div class="kpi-label">delta % promedio . Oficial</div>
      <div class="kpi-val" id="k-oficial">–</div>
      <div class="kpi-sub" id="k-oficial-sub">de costo por cambio</div>
    </div>
    <div class="kpi g">
      <div class="kpi-label">delta % promedio . Privado</div>
      <div class="kpi-val" id="k-privado">–</div>
      <div class="kpi-sub" id="k-privado-sub">de costo por cambio</div>
    </div>
    <div class="kpi a">
      <div class="kpi-label">Aumento maximo detectado</div>
      <div class="kpi-val" id="k-max">–</div>
      <div class="kpi-sub" id="k-max-sub">sin datos</div>
    </div>
  </section>
  <div class="ct-note" style="margin:-.5rem 0 1rem">
    "delta % promedio" = cambio promedio porcentual en el costo de matricula (costo despues vs. costo antes) entre
    los programas modificados de ese grupo. Se usa % y no pesos porque el costo varia en ordenes de magnitud
    distintos entre programas, asi que el porcentaje es lo unico comparable entre ellos.
    <strong>Negativo</strong> significa que, en promedio, baja la matricula; <strong>positivo</strong>, que sube.
  </div>

  <section class="g2">
    <div class="card">
      <div class="ct">Sube vs. baja, por sector</div>
      <div id="ch-sector" style="height:280px"></div>
    </div>
    <div class="card">
      <div class="ct">Distribucion del cambio (% de costo de matricula)</div>
      <div id="ch-hist" style="height:280px"></div>
    </div>
  </section>

  <section class="g2">
    <div class="card">
      <div class="ct">Top instituciones que mas cambian el costo</div>
      <div class="ct-note">Numero al lado de la barra: delta % promedio de esa institucion (ver definicion arriba).</div>
      <div id="ch-instituciones" style="height:380px"></div>
    </div>
    <div class="card">
      <div class="ct">Top departamentos que mas cambian el costo</div>
      <div class="ct-note">Numero al lado de la barra: delta % promedio de ese departamento (ver definicion arriba).</div>
      <div id="ch-departamentos" style="height:380px"></div>
    </div>
  </section>

  <section class="card">
    <div class="ct">Por campo CINE: que areas suben o bajan el costo de matricula</div>
    <div class="ct-note">Filtra por institucion arriba para ver el detalle de su oferta. Cada barra es un campo
      CINE; el valor es el cambio % promedio entre los programas de ese campo. Rojo = en promedio sube el costo;
      verde = en promedio baja.</div>
    <div id="ch-cine-delta" style="height:420px"></div>
  </section>

  <section class="card">
    <div class="ct">Costo de matricula: antes -&gt; despues (coloreado por sector, escala log)</div>
    <div id="ch-scatter" style="height:380px"></div>
  </section>

  <section class="card">
    <div class="ct">Registros con cambio de costo</div>
    <div class="tbl-wrap" id="tbl-wrap"></div>
  </section>
</main>

<script>
const D = __DATA__;
const PC = {responsive:true, displayModeBar:false};
const fmt = n => (n ?? 0).toLocaleString('es-CO');
const _norm = s => String(s==null?'':s).normalize('NFD').replace(/[̀-ͯ]/g,'').toLowerCase();
function _rowMatches(r, tokens) {
  if (!tokens.length) return true;
  const hay = _norm(Object.values(r).join(' '));
  return tokens.every(t => hay.includes(t));
}

function _emptyChart(id, msg) {
  const el = document.getElementById(id); if (!el) return;
  Plotly.purge(el);
  el.innerHTML = '<div style="display:flex;align-items:center;justify-content:center;height:100%;color:#64748b;font-size:.82rem">' + (msg || 'Sin datos para los filtros aplicados') + '</div>';
}

function agruparPorCampo(rows, field) {
  const m = new Map();
  rows.forEach(r => {
    const k = r[field]; if (!k) return;
    if (!m.has(k)) m.set(k, []);
    m.get(k).push(r);
  });
  return m;
}

function resumenGrupo(rows) {
  const n = rows.length;
  const suben = rows.filter(r => r._delta_pct > 0).length;
  const bajan = rows.filter(r => r._delta_pct < 0).length;
  const promedio = n ? rows.reduce((s, r) => s + r._delta_pct, 0) / n : 0;
  return {n, suben, bajan, promedio_delta: Math.round(promedio * 10) / 10};
}

function ranking(rows, field, topN) {
  const m = agruparPorCampo(rows, field);
  const out = [...m.entries()].map(([nombre, g]) => ({nombre, ...resumenGrupo(g)}));
  out.sort((a, b) => b.n - a.n);
  return out.slice(0, topN);
}

const BUCKETS_DELTA = [
  {min: -Infinity, max: -20,      label: '≤ -20%'},
  {min: -19,       max: -10,      label: '-19 a -10%'},
  {min: -9,        max: -1,       label: '-9 a -1%'},
  {min: 0,         max: 0,        label: '0%'},
  {min: 1,         max: 9,        label: '1 a 9%'},
  {min: 10,        max: 19,       label: '10 a 19%'},
  {min: 20,        max: 49,       label: '20 a 49%'},
  {min: 50,        max: Infinity, label: '≥ 50%'},
];

function binDeltas(rows) {
  const counts = BUCKETS_DELTA.map(b => rows.filter(r => r._delta_pct >= b.min && r._delta_pct <= b.max).length);
  const colors = BUCKETS_DELTA.map(b => b.max < 0 ? '#1a9e6b' : b.min > 0 ? '#ae1e22' : '#94a3b8');
  return {labels: BUCKETS_DELTA.map(b => b.label), counts, colors};
}

function renderSector(porSector) {
  if (!porSector.length) { _emptyChart('ch-sector'); return; }
  const labels = porSector.map(s => s.nombre);
  Plotly.react('ch-sector', [
    {x: labels, y: porSector.map(s => s.suben), name: 'Suben', type: 'bar',
     marker: {color: '#ae1e22', opacity: .85}},
    {x: labels, y: porSector.map(s => s.bajan), name: 'Bajan', type: 'bar',
     marker: {color: '#1a9e6b', opacity: .85}},
  ], {
    barmode: 'group', margin: {t:10,r:10,b:30,l:45},
    yaxis: {showgrid: true, gridcolor: '#e2e8f0'},
    plot_bgcolor: 'white', paper_bgcolor: 'white',
    legend: {orientation: 'h', y: -0.18}
  }, PC);
}

function renderHist(costRows) {
  const h = binDeltas(costRows);
  if (!h.counts.some(c => c > 0)) { _emptyChart('ch-hist'); return; }
  Plotly.react('ch-hist', [{
    x: h.labels, y: h.counts, type: 'bar',
    marker: {color: h.colors, opacity: .85},
    hovertemplate: 'Rango: %{x}<br><b>%{y}</b> programas<extra></extra>'
  }], {
    margin: {t:10,r:10,b:75,l:45},
    xaxis: {title: {text: 'Cambio en costo de matricula (%)', standoff: 25}, tickangle: -30, tickfont: {size: 10}},
    yaxis: {title: 'N. programas', showgrid: true, gridcolor: '#e2e8f0'},
    plot_bgcolor: 'white', paper_bgcolor: 'white', bargap: .15
  }, PC);
}

function renderRanking(id, data) {
  if (!data.length) { _emptyChart(id); return; }
  const d = [...data].slice(0, 12).reverse();
  const trunc = s => s.length > 36 ? s.slice(0, 36) + '...' : s;
  const maxN = Math.max(...d.map(r => r.n));
  Plotly.react(id, [{
    y: d.map(r => trunc(r.nombre)), x: d.map(r => r.n), customdata: d.map(r => r.nombre),
    type: 'bar', orientation: 'h',
    marker: {color: d.map(r => r.promedio_delta >= 0 ? '#ae1e22' : '#1a9e6b'), opacity: .85},
    text: d.map(r => `${r.promedio_delta > 0 ? '+' : ''}${r.promedio_delta}%`),
    textposition: 'outside', cliponaxis: false,
    textfont: {size: 10, color: d.map(r => r.promedio_delta >= 0 ? '#7a1518' : '#0f6e49')},
    hovertemplate: '%{customdata}<br><b>%{x}</b> cambios<extra></extra>'
  }], {
    margin: {t:10,r:60,b:30,l:230},
    xaxis: {showgrid: true, gridcolor: '#e2e8f0', range: [0, maxN * 1.35]},
    yaxis: {tickfont: {size: 10}},
    plot_bgcolor: 'white', paper_bgcolor: 'white', bargap: .3
  }, PC);
}

function renderCineDelta(costRows) {
  const CINE_COL = 'CINE_F_2013_AC_CAMPO_ESPECÍFIC';
  const m = agruparPorCampo(costRows, CINE_COL);
  const data = [...m.entries()].map(([campo, rows]) => {
    const n = rows.length;
    const suben = rows.filter(r => r._delta_pct > 0).length;
    const bajan = rows.filter(r => r._delta_pct < 0).length;
    const promedio = n ? rows.reduce((s, r) => s + r._delta_pct, 0) / n : 0;
    return {campo, n, suben, bajan, promedio: Math.round(promedio * 10) / 10};
  });
  data.sort((a, b) => Math.abs(b.promedio) - Math.abs(a.promedio));
  const top = data.slice(0, 20).reverse();
  if (!top.length) { _emptyChart('ch-cine-delta'); return; }
  const trunc = s => s.length > 42 ? s.slice(0, 42) + '...' : s;
  Plotly.react('ch-cine-delta', [{
    y: top.map(d => trunc(d.campo)), x: top.map(d => d.promedio), customdata: top,
    type: 'bar', orientation: 'h',
    marker: {color: top.map(d => d.promedio >= 0 ? '#ae1e22' : '#1a9e6b'), opacity: .85},
    text: top.map(d => (d.promedio > 0 ? '+' : '') + d.promedio + '%'),
    textposition: 'outside', cliponaxis: false, textfont: {size: 10},
    hovertemplate: '%{y}<br>Cambio promedio: <b>%{x}%</b>' +
      '<br>%{customdata.suben} suben / %{customdata.bajan} bajan (%{customdata.n} programas)<extra></extra>'
  }], {
    margin: {t:10,r:50,b:40,l:270},
    xaxis: {title: 'Cambio promedio en costo de matricula (%)', zeroline: true, zerolinecolor: '#94a3b8',
      showgrid: true, gridcolor: '#e2e8f0'},
    yaxis: {tickfont: {size: 10}},
    plot_bgcolor: 'white', paper_bgcolor: 'white', bargap: .3
  }, PC);
}

function renderScatter(costRows) {
  if (!costRows.length) { _emptyChart('ch-scatter'); return; }
  const porSector = {};
  costRows.forEach(p => { (porSector[p.SECTOR] = porSector[p.SECTOR] || []).push(p); });
  const colores = {Oficial: '#2d5b9e', Privado: '#bd900b'};
  const vals = costRows.flatMap(p => [p._costo_antes, p._costo_despues]);
  const mn = Math.min(...vals), mx = Math.max(...vals);
  const traces = Object.entries(porSector).map(([sector, pts]) => ({
    x: pts.map(p => p._costo_antes), y: pts.map(p => p._costo_despues),
    text: pts.map(p => p['NOMBRE_INSTITUCIÓN'] + ' - ' + p['NOMBRE_DEL_PROGRAMA']),
    mode: 'markers', type: 'scatter', name: sector,
    marker: {color: colores[sector] || '#64748b', size: 7, opacity: .65},
    hovertemplate: '<b>%{text}</b><br>Antes: $%{x:,.0f}<br>Despues: $%{y:,.0f}<extra></extra>'
  }));
  traces.push({x: [mn, mx], y: [mn, mx], mode: 'lines', line: {color: '#9fb0c9', width: 1, dash: 'dot'},
    hoverinfo: 'skip', showlegend: false});
  Plotly.react('ch-scatter', traces, {
    margin: {t:10,r:20,b:50,l:70},
    xaxis: {title: 'Costo antes (COP)', type: 'log', showgrid: true, gridcolor: '#e2e8f0'},
    yaxis: {title: 'Costo despues (COP)', type: 'log', showgrid: true, gridcolor: '#e2e8f0'},
    plot_bgcolor: 'white', paper_bgcolor: 'white',
    legend: {orientation: 'h', y: -0.2}
  }, PC);
}

const COL_HEAD = {
  FECHA_OBTENCION: 'Fecha', 'CODIGO_SNIES_DEL_PROGRAMA': 'Cod. SNIES', NOMBRE_DEL_PROGRAMA: 'Programa',
  'NOMBRE_INSTITUCIÓN': 'Institucion', SECTOR: 'Sector', DEPARTAMENTO_OFERTA_PROGRAMA: 'Departamento',
  'DIVISION UNINORTE': 'Division', _costo_antes: 'Costo antes', _costo_despues: 'Costo despues',
  _delta_pct: 'Delta %', QUE_CAMBIO: 'Que mas cambio?'
};
const TBL_COLS = ['FECHA_OBTENCION', 'NOMBRE_DEL_PROGRAMA', 'NOMBRE_INSTITUCIÓN', 'SECTOR',
  'DEPARTAMENTO_OFERTA_PROGRAMA', '_costo_antes', '_costo_despues', '_delta_pct', 'QUE_CAMBIO'];
let sortDir = {};
let tablaRows = [];

function buildTbl(rows) {
  const cols = TBL_COLS.filter(c => !rows.length || c in rows[0]);
  let h = '<table><thead><tr>';
  cols.forEach(c => { h += '<th onclick="sortTbl(\'' + c + '\')">' + (COL_HEAD[c] || c) + ' <span style="opacity:.4">↕</span></th>'; });
  h += '</tr></thead><tbody>';
  if (!rows.length) {
    h += '<tr><td colspan="' + cols.length + '" class="empty">Sin registros para los filtros seleccionados</td></tr>';
  } else {
    rows.forEach(r => {
      h += '<tr>' + cols.map(c => {
        if (c === '_delta_pct') {
          const v = r[c];
          const cls = v > 0 ? 'delta-up' : (v < 0 ? 'delta-down' : '');
          return '<td class="' + cls + '">' + (v > 0 ? '+' : '') + v + '%</td>';
        }
        if (c === '_costo_antes' || c === '_costo_despues') {
          return '<td>$' + fmt(r[c]) + '</td>';
        }
        return '<td>' + (r[c] ?? '') + '</td>';
      }).join('') + '</tr>';
    });
  }
  return h + '</tbody></table>';
}

function renderTbl(rows) { tablaRows = rows; document.getElementById('tbl-wrap').innerHTML = buildTbl(rows); }

function sortTbl(col) {
  sortDir[col] = !sortDir[col];
  tablaRows = [...tablaRows].sort((a, b) => {
    const va = a[col] ?? '', vb = b[col] ?? '';
    const na = parseFloat(va), nb = parseFloat(vb);
    const cmp = (!isNaN(na) && !isNaN(nb)) ? na - nb : String(va).localeCompare(String(vb), 'es');
    return sortDir[col] ? cmp : -cmp;
  });
  document.getElementById('tbl-wrap').innerHTML = buildTbl(tablaRows);
}

function uniq(arr) { return [...new Set(arr.filter(v => v && String(v).trim() !== ''))].sort(); }
function addOpts(id, vals) {
  const el = document.getElementById(id); if (!el) return;
  vals.forEach(v => { const o = document.createElement('option'); o.value = o.textContent = v; el.appendChild(o); });
}
function initAutocomplete(inputId, menuId, options, onChange) {
  const inp = document.getElementById(inputId), menu = document.getElementById(menuId);
  if (!inp || !menu) return;
  function render() {
    const q = _norm(inp.value).trim();
    const matches = (q ? options.filter(o => _norm(o).includes(q)) : options).slice(0, 50);
    menu.innerHTML = matches.length
      ? matches.map(o => '<div class="ac-item">' + o.replace(/&/g,'&amp;').replace(/</g,'&lt;') + '</div>').join('')
      : '<div class="ac-empty">Sin coincidencias</div>';
    menu.classList.add('show');
  }
  inp.addEventListener('focus', render);
  inp.addEventListener('input', () => { render(); onChange(); });
  menu.addEventListener('mousedown', e => {
    const it = e.target.closest('.ac-item'); if (!it) return;
    e.preventDefault();
    inp.value = it.textContent;
    menu.classList.remove('show');
    onChange();
  });
  document.addEventListener('click', e => {
    if (e.target !== inp && !menu.contains(e.target)) menu.classList.remove('show');
  });
}
addOpts('f-sector', uniq(D.universo.map(r => r['SECTOR'])));
addOpts('f-depto',  uniq(D.universo.map(r => r['DEPARTAMENTO_OFERTA_PROGRAMA'])));
initAutocomplete('f-institucion', 'f-institucion-menu', uniq(D.universo.map(r => r['NOMBRE_INSTITUCIÓN'])), applyFilters);

function gv(id) { const el = document.getElementById(id); return el ? el.value : ''; }
const truncKpi = s => s.length > 55 ? s.slice(0, 55) + '…' : s;

function applyFilters() {
  const qTokens = _norm(gv('f-q')).split(/\s+/).filter(Boolean);
  const se = gv('f-sector'), de = gv('f-depto');
  const insTokens = _norm(gv('f-institucion')).split(/\s+/).filter(Boolean);

  const filtrados = D.universo.filter(r => {
    if (!_rowMatches(r, qTokens)) return false;
    if (se && r['SECTOR'] !== se) return false;
    if (de && r['DEPARTAMENTO_OFERTA_PROGRAMA'] !== de) return false;
    if (insTokens.length) {
      const hayIns = _norm(r['NOMBRE_INSTITUCIÓN']);
      if (!insTokens.every(t => hayIns.includes(t))) return false;
    }
    return true;
  });
  const costRows = filtrados.filter(r => r._cambia_costo);

  document.getElementById('f-count').textContent = fmt(costRows.length) + ' cambios de costo (' + fmt(filtrados.length) + ' programas modificados en total)';
  document.getElementById('k-total').textContent = fmt(costRows.length);

  const porSectorAgg = ranking(costRows, 'SECTOR', 10).sort((a, b) => a.nombre.localeCompare(b.nombre));
  const sOficial = porSectorAgg.find(s => s.nombre === 'Oficial');
  const sPrivado = porSectorAgg.find(s => s.nombre === 'Privado');
  document.getElementById('k-oficial').textContent = sOficial ? (sOficial.promedio_delta > 0 ? '+' : '') + sOficial.promedio_delta + '%' : '-';
  document.getElementById('k-oficial-sub').textContent = sOficial ? `${sOficial.suben} suben / ${sOficial.bajan} bajan` : 'sin datos';
  document.getElementById('k-privado').textContent = sPrivado ? (sPrivado.promedio_delta > 0 ? '+' : '') + sPrivado.promedio_delta + '%' : '-';
  document.getElementById('k-privado-sub').textContent = sPrivado ? `${sPrivado.suben} suben / ${sPrivado.bajan} bajan` : 'sin datos';

  const maxRow = costRows.reduce((best, r) => (!best || r._delta_pct > best._delta_pct) ? r : best, null);
  document.getElementById('k-max').textContent = maxRow ? (maxRow._delta_pct > 0 ? '+' : '') + maxRow._delta_pct + '%' : '-';
  document.getElementById('k-max-sub').textContent = maxRow ? truncKpi(maxRow['NOMBRE_INSTITUCIÓN'] + ' — ' + maxRow['NOMBRE_DEL_PROGRAMA']) : 'sin datos';

  renderSector(porSectorAgg);
  renderHist(costRows);
  renderRanking('ch-instituciones', ranking(costRows, 'NOMBRE_INSTITUCIÓN', 20));
  renderRanking('ch-departamentos', ranking(costRows, 'DEPARTAMENTO_OFERTA_PROGRAMA', 20));
  renderCineDelta(costRows);
  renderScatter(costRows);
  renderTbl(costRows);
}

function resetFilters() {
  ['f-q', 'f-sector', 'f-depto', 'f-institucion'].forEach(id => { const el = document.getElementById(id); if (el) el.value = ''; });
  applyFilters();
}

applyFilters();
</script>
</body>
</html>
"""
if __name__ == "__main__":
    main()
