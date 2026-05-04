"""
docs/generar_dashboard.py
Genera docs/index.html y las páginas de detalle (nuevos/inactivos/modificados.html).
Se ejecuta en CI justo después del pipeline de descarga/comparación.

Uso:
    python docs/generar_dashboard.py
"""
import json
import re
import warnings
from datetime import datetime
from pathlib import Path

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
    "DIVISIÓN UNINORTE",
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
        "color": "#059669", "colorAlpha": "rgba(5,150,105,0.08)",
        "cols": COLS_DETAIL,
    },
    "inactivos": {
        "tipo": "inactivos", "title": "Programas Inactivos", "emoji": "❌",
        "color": "#dc2626", "colorAlpha": "rgba(220,38,38,0.08)",
        "cols": COLS_DETAIL,
    },
    "modificados": {
        "tipo": "modificados", "title": "Programas Modificados", "emoji": "⚠️",
        "color": "#d97706", "colorAlpha": "rgba(217,119,6,0.08)",
        "cols": COLS_MOD_DETAIL,
    },
}

HDR_GRAD = {
    "nuevos":      "linear-gradient(135deg,#065f46,#059669)",
    "inactivos":   "linear-gradient(135deg,#991b1b,#dc2626)",
    "modificados": "linear-gradient(135deg,#92400e,#d97706)",
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
              style="padding:.35rem .8rem;background:#2563eb;color:#fff;border:none;border-radius:.4rem;font-size:.78rem;cursor:pointer;white-space:nowrap">+ Agregar</button>
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
              style="padding:.35rem .8rem;background:#2563eb;color:#fff;border:none;border-radius:.4rem;font-size:.78rem;cursor:pointer;white-space:nowrap">+ Agregar</button>
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
<div class="card"><div class="ct">Modificaciones por fecha de run</div><div id="ch-timeline" style="height:200px"></div></div>
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
    """Fill base column from first available source column."""
    for src in sources:
        if src not in df.columns:
            continue
        if base not in df.columns:
            df[base] = df[src]
            return
        mask = df[base].isna()
        if mask.any():
            df.loc[mask, base] = df.loc[mask, src]
        return


def _normalizar_modificados(df: pd.DataFrame) -> pd.DataFrame:
    """Rellena columnas base vacías desde variantes _NUEVO para filas acumuladas
    antes de que detectar_novedades renombrara los sufijos del merge."""
    if df is None or df.empty:
        return df
    df = df.copy()

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

    _fill_num(df, "NÚMERO_CRÉDITOS",
              ("NÚMERO_CRÉDITOS_NUEVO", "NÚMERO_CRÉDITOS_NUEVOS"))
    _fill_num(df, "NÚMERO_CRÉDITOS_ANTERIOR",
              ("NÚMERO_CRÉDITOS_ANTIGUO", "NÚMERO_CRÉDITOS_ANTERIORES"))

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
                n_col = f"{col}_NUEVO"
                a_col = next(
                    (c for c in (f"{col}_ANTIGUO", f"{col}_ANTERIOR") if c in row.index),
                    None,
                )
                if n_col in row.index and a_col:
                    vn, va = str(row[n_col]).strip(), str(row[a_col]).strip()
                    if vn != va and vn not in ("nan", "") and va not in ("nan", ""):
                        parts.append(f"{label}: {va} -> {vn}")
            return " | ".join(parts) if parts else ""
        df.loc[empty, "QUE_CAMBIO"] = df[empty].apply(_rebuild, axis=1)

    return df


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
    nuevos_df    = leer_novedades("Nuevos_pregrado.xlsx")
    inactivos_df = leer_novedades("Inactivos_pregrado.xlsx")
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

    col_per = next(
        (c for c in snapshot_df.columns if "PERIODO" in c.upper() and "DURACI" in c.upper()),
        None,
    )
    if col_per and not snapshot_df.empty:
        counts = snapshot_df[col_per].dropna().value_counts()
        por_periodos = sorted(
            [{"label": int(k), "value": int(v)} for k, v in counts.items()],
            key=lambda x: x["label"],
        )
    else:
        por_periodos = []

    data = {
        "ultima_actualizacion": historico[-1]["fecha"] if historico else "N/A",
        "historico":     historico,
        "kpis":          kpis,
        "por_sector":    _distribucion(snapshot_df, "SECTOR"),
        "por_depto":     _distribucion(snapshot_df, "DEPARTAMENTO_OFERTA_PROGRAMA"),
        "por_modalidad": _distribucion(snapshot_df, "MODALIDAD"),
        "por_periodos":  por_periodos,
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
            .replace("__XFILTER__", XFILTER[tipo])
            .replace("__TITLE__",   DETAIL_CFGS[tipo]["title"])
            .replace("__EMOJI__",   DETAIL_CFGS[tipo]["emoji"])
            .replace("__HDRGRD__",  HDR_GRAD[tipo])
        )
        p = DOCS_DIR / f"{tipo}.html"
        p.write_text(html, encoding="utf-8")
        print(f"  HTML: {p}")

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
  --bg:#f1f5f9; --surface:#fff; --hdr1:#1e3a8a; --hdr2:#2563eb;
  --text:#0f172a; --muted:#64748b; --border:#e2e8f0;
  --blue:#2563eb; --green:#059669; --red:#dc2626; --amber:#d97706;
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

  <section class="card">
    <div class="card-title">Evolución histórica de programas universitarios activos</div>
    <div id="ch-hist" style="height:280px"></div>
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
    <div class="card-title">Distribución de programas activos por duración (periodos requeridos)</div>
    <div id="ch-periodos" style="height:280px"></div>
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
      <input class="search" placeholder="Buscar por nombre, institución, código SNIES…" oninput="filter('nue',this.value)">
      <div class="tbl-wrap" id="tw-nue"></div>
    </div>
    <div id="tp-ina" class="tab-pane">
      <input class="search" placeholder="Buscar por nombre, institución, código SNIES…" oninput="filter('ina',this.value)">
      <div class="tbl-wrap" id="tw-ina"></div>
    </div>
    <div id="tp-mod" class="tab-pane">
      <input class="search" placeholder="Buscar por nombre, institución, código SNIES…" oninput="filter('mod',this.value)">
      <div class="tbl-wrap" id="tw-mod"></div>
    </div>
  </section>
</main>

<script>
const D = __DATA__;
const fmt = n => (n ?? 0).toLocaleString('es-CO');
document.getElementById('fecha-update').textContent = D.ultima_actualizacion;
document.getElementById('k-total').textContent = fmt(D.kpis.total_activos);
document.getElementById('k-nue').textContent   = fmt(D.kpis.nuevos_ultimo);
document.getElementById('k-ina').textContent   = fmt(D.kpis.inactivos_ultimo);
document.getElementById('k-mod').textContent   = fmt(D.kpis.mods_ultimo);
document.getElementById('k-nue-sub').textContent = 'acumulado: ' + fmt(D.kpis.nuevos_total);
document.getElementById('k-ina-sub').textContent = 'acumulado: ' + fmt(D.kpis.inactivos_total);
document.getElementById('k-mod-sub').textContent = 'acumulado: ' + fmt(D.kpis.mods_total);

(function() {
  const h = D.historico;
  if (!h.length) return;
  Plotly.newPlot('ch-hist', [{
    x: h.map(p => p.fecha), y: h.map(p => p.total),
    type: 'scatter', mode: 'lines+markers',
    line: {color:'#2563eb', width:2.5}, marker: {color:'#2563eb', size:6},
    fill: 'tozeroy', fillcolor: 'rgba(37,99,235,0.07)',
    hovertemplate: '%{x}<br><b>%{y:,}</b> programas<extra></extra>'
  }], {
    margin: {t:10,r:20,b:40,l:60},
    xaxis: {showgrid:false, tickfont:{size:11}},
    yaxis: {showgrid:true, gridcolor:'#e2e8f0', tickfont:{size:11}, rangemode:'tozero'},
    plot_bgcolor:'white', paper_bgcolor:'white', hovermode:'x unified'
  }, {responsive:true, displayModeBar:false});
})();

(function() {
  const d = D.por_sector;
  if (!d.length) return;
  Plotly.newPlot('ch-sector', [{
    labels: d.map(x => x.label), values: d.map(x => x.value),
    type:'pie', hole:0.45,
    marker:{colors:['#2563eb','#10b981','#f59e0b','#ef4444','#8b5cf6','#06b6d4']},
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
    marker:{color:'#2563eb', opacity:0.82},
    hovertemplate:'%{y}<br><b>%{x:,}</b><extra></extra>'
  }], {
    margin:{t:10,r:20,b:40,l:170},
    xaxis:{showgrid:true, gridcolor:'#e2e8f0', tickfont:{size:11}},
    yaxis:{tickfont:{size:11}},
    plot_bgcolor:'white', paper_bgcolor:'white', bargap:0.3
  }, {responsive:true, displayModeBar:false});
})();

(function() {
  const d = D.por_periodos;
  if (!d || !d.length) return;
  Plotly.newPlot('ch-periodos', [{
    x: d.map(p => p.label),
    y: d.map(p => p.value),
    type: 'bar',
    marker: {color: '#2563eb', opacity: 0.82},
    text: d.map(p => p.value.toLocaleString('es-CO')),
    textposition: 'outside',
    cliponaxis: false,
    hovertemplate: '%{x} periodos<br><b>%{y:,}</b> programas<extra></extra>'
  }], {
    margin: {t:30, r:20, b:50, l:70},
    xaxis: {title: 'Periodos', tickmode: 'array',
            tickvals: d.map(p => p.label), tickfont: {size:11}},
    yaxis: {title: 'N. Programas', showgrid: true,
            gridcolor: '#e2e8f0', tickfont: {size:11}},
    plot_bgcolor: 'white', paper_bgcolor: 'white', bargap: 0.25
  }, {responsive: true, displayModeBar: false});
})();

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
let sortDir = {};

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

function filter(type, q) {
  q = q.toLowerCase();
  const filtered = q
    ? rows[type].filter(r => Object.values(r).some(v => String(v).toLowerCase().includes(q)))
    : rows[type];
  render(type, filtered);
}

function sortTbl(type, col) {
  const key = type + col;
  sortDir[key] = !sortDir[key];
  rows[type] = [...rows[type]].sort((a, b) => {
    const va = a[col] || '', vb = b[col] || '';
    return sortDir[key] ? va.localeCompare(vb, 'es') : vb.localeCompare(va, 'es');
  });
  render(type, rows[type]);
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
  --border:#e2e8f0;--blue:#2563eb;--radius:0.75rem;
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
  <div class="badge-update">
    <span style="opacity:.7;font-size:.67rem">Total acumulado</span>
    <strong id="badge-total">–</strong>
  </div>
</header>

<div class="filter-bar">
  <input id="f-q" class="f-input" placeholder="Buscar por nombre, institución, código SNIES, departamento…" oninput="applyFilters()">
  <select id="f-sector"   class="f-sel" onchange="applyFilters()"><option value="">Todos los sectores</option></select>
  <select id="f-depto"    class="f-sel" onchange="applyFilters()"><option value="">Todos los departamentos</option></select>
  <select id="f-division" class="f-sel" onchange="applyFilters()"><option value="">Todas las divisiones</option></select>
  __XFILTER__
  <select id="f-fecha"    class="f-sel" onchange="applyFilters()"><option value="">Todas las fechas</option></select>
  <button class="f-btn" onclick="resetFilters()">✕ Limpiar</button>
  <span class="f-count" id="f-count">–</span>
</div>

<main>
  <section>__CHARTS__</section>

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

addOpts('f-sector',   uniq(ROWS.map(r => r['SECTOR'])));
addOpts('f-depto',    uniq(ROWS.map(r => r['DEPARTAMENTO_OFERTA_PROGRAMA'])));
addOpts('f-division', uniq(ROWS.map(r => r['DIVISIÓN UNINORTE'])));

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
}

// ── Filters ────────────────────────────────────────────────────────────────
function gv(id) { const el=document.getElementById(id); return el?el.value:''; }

function applyFilters() {
  const q  = gv('f-q').toLowerCase();
  const se = gv('f-sector'), de = gv('f-depto'), di = gv('f-division');
  const mo = gv('f-modalidad'), fe = gv('f-fecha'), tc = gv('f-tipo-cambio');

  filtered = ROWS.filter(r => {
    if (q  && !Object.values(r).some(v => String(v).toLowerCase().includes(q))) return false;
    if (se && r['SECTOR'] !== se) return false;
    if (de && r['DEPARTAMENTO_OFERTA_PROGRAMA'] !== de) return false;
    if (di && r['DIVISIÓN UNINORTE'] !== di) return false;
    if (mo && r['MODALIDAD'] !== mo) return false;
    if (fe && r['FECHA_OBTENCION'] !== fe) return false;
    if (tc && !(r['QUE_CAMBIO']||'').includes(tc)) return false;
    return true;
  });
  renderAll(filtered);
}

function resetFilters() {
  ['f-q','f-sector','f-depto','f-division','f-modalidad','f-fecha','f-tipo-cambio'].forEach(id => {
    const el = document.getElementById(id); if (el) el.value = '';
  });
  applyFilters();
}

// ── Distribution helpers ───────────────────────────────────────────────────
function countBy(rows, field, n) {
  const c={};
  rows.forEach(r => { const v=(r[field]||'Sin datos').toString().trim()||'Sin datos'; c[v]=(c[v]||0)+1; });
  return Object.entries(c).sort((a,b)=>b[1]-a[1]).slice(0,n||12);
}
function byDate(rows) {
  const c={};
  rows.forEach(r => { const v=r['FECHA_OBTENCION']||'?'; c[v]=(c[v]||0)+1; });
  const e=Object.entries(c).sort();
  return {x:e.map(i=>i[0]), y:e.map(i=>i[1])};
}

// ── Shared date helper ─────────────────────────────────────────────────────
function getSem(s) {
  if(!s||!s.trim()) return null;
  let y,m;
  const iso=s.match(/^(\d{4})-(\d{2})/);
  if(iso){y=+iso[1];m=+iso[2];}
  else{const dmy=s.match(/^(\d{2})\/(\d{2})\/(\d{4})/);if(dmy){y=+dmy[3];m=+dmy[2];}}
  if(!y||y<2014||y>2035) return null;
  return y+'-'+(m<=6?'S1':'S2');
}

// ── Charts ─────────────────────────────────────────────────────────────────
function plotDonut(id, rows, field) {
  const el=document.getElementById(id); if(!el) return;
  const d=countBy(rows,field,20); if(!d.length) return;
  Plotly.react(id,[{labels:d.map(e=>e[0]),values:d.map(e=>e[1]),type:'pie',hole:.45,
    marker:{colors:['#2563eb','#10b981','#f59e0b','#ef4444','#8b5cf6','#06b6d4','#ec4899']},
    textinfo:'label+percent',hovertemplate:'%{label}<br><b>%{value:,}</b><extra></extra>'}],
    {margin:{t:10,r:10,b:35,l:10},showlegend:true,legend:{orientation:'h',y:-0.12,font:{size:10}},
    plot_bgcolor:'white',paper_bgcolor:'white'},PC);
}

function plotHBar(id, rows, field, color, n, maxLen) {
  const el=document.getElementById(id); if(!el) return;
  const d=[...countBy(rows,field,n||10)].reverse(); if(!d.length) return;
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
  const d=countBy(rows,field,10); if(!d.length) return;
  Plotly.react(id,[{x:d.map(e=>e[0]),y:d.map(e=>e[1]),type:'bar',
    marker:{color,opacity:.85},hovertemplate:'%{x}<br><b>%{y:,}</b><extra></extra>'}],
    {margin:{t:10,r:10,b:80,l:45},
    xaxis:{tickfont:{size:10},tickangle:-30},
    yaxis:{showgrid:true,gridcolor:'#e2e8f0'},
    plot_bgcolor:'white',paper_bgcolor:'white',bargap:.35},PC);
}

function plotTimeline(id, rows) {
  const el=document.getElementById(id); if(!el) return;
  const {x,y}=byDate(rows); if(!x.length) return;
  Plotly.react(id,[{x,y,type:'scatter',mode:'lines+markers',
    line:{color:C,width:2.5},marker:{color:C,size:7},
    fill:'tozeroy',fillcolor:CA,
    hovertemplate:'%{x}<br><b>%{y:,}</b><extra></extra>'}],
    {margin:{t:10,r:20,b:40,l:50},
    xaxis:{showgrid:false,tickfont:{size:11}},
    yaxis:{showgrid:true,gridcolor:'#e2e8f0',rangemode:'tozero'},
    plot_bgcolor:'white',paper_bgcolor:'white',hovermode:'x unified'},PC);
}

function plotAcumuladoModalidad(id, rows) {
  const el=document.getElementById(id); if(!el||!rows.length) return;

  const semSet=new Set();
  rows.forEach(r=>{const s=getSem(r['FECHA_DE_REGISTRO_EN_SNIES']);if(s)semSet.add(s);});
  const sems=[...semSet].sort(); // "YYYY-S1" < "YYYY-S2" sorts correctly as strings

  if(!sems.length){
    el.innerHTML='<div style="display:flex;align-items:center;justify-content:center;height:100%;color:#64748b;font-size:.82rem">Sin datos de fecha de registro en SNIES</div>';
    return;
  }

  const mods=[...new Set(rows.map(r=>r['MODALIDAD']).filter(v=>v&&v.trim()))].sort();
  const COLORS=['#2563eb','#059669','#d97706','#dc2626','#8b5cf6','#06b6d4','#ec4899'];

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

  if(!traces.length) return;
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
const CINE_COLORS=['#2563eb','#059669','#d97706','#dc2626','#8b5cf6',
                   '#06b6d4','#ec4899','#f97316','#84cc16','#14b8a6'];
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
  const sems=allSems.filter(s=>s>='2023-S2');

  const tagsEl=document.getElementById('cine-tags');
  if(tagsEl){
    tagsEl.innerHTML=_cineActive.map((cine,i)=>{
      const col=CINE_COLORS[i%CINE_COLORS.length];
      const safe=cine.replace(/\\/g,'\\\\').replace(/'/g,"\\'");
      return '<span style="display:inline-flex;align-items:center;gap:.3rem;'+
        'background:'+col+'22;border:1px solid '+col+'66;border-radius:2rem;'+
        'padding:.18rem .55rem;font-size:.72rem;color:'+col+';font-weight:500">'+
        cine+
        '<button onclick="cineRemove(\''+safe+'\')" '+
        'style="background:none;border:none;cursor:pointer;color:'+col+';'+
        'font-size:.9rem;padding:0 0 0 .2rem;line-height:1;opacity:.75">\xd7</button></span>';
    }).join('');
  }

  if(!sems.length){
    el.innerHTML='<div style="display:flex;align-items:center;justify-content:center;'+
      'height:100%;color:#64748b;font-size:.82rem">Sin datos de fecha de registro</div>';
    return;
  }

  const traces=_cineActive.map((cine,i)=>{
    const isUnclass=cine==='Sin clasificar';
    const bySem={};
    rows.filter(r=>{const v=(r[CINE_COL]||'').trim();return isUnclass?!v:v===cine;})
        .forEach(r=>{const s=getSem(r['FECHA_DE_REGISTRO_EN_SNIES']);if(s)bySem[s]=(bySem[s]||0)+1;});
    let cum=0;const x=[],y=[];
    allSems.forEach(s=>{cum+=(bySem[s]||0);if(s>='2023-S2'){x.push(s);y.push(cum);}});
    if(cum===0) return null;
    const col=CINE_COLORS[i%CINE_COLORS.length];
    return{x,y,name:cine,type:'scatter',mode:'lines+markers',
      line:{color:col,width:2.5},marker:{color:col,size:6},
      hovertemplate:cine+'<br><b>%{x}</b><br>%{y:,} acumulados<extra></extra>'};
  }).filter(Boolean);

  if(!traces.length) return;
  Plotly.react('ch-timeline',traces,{
    margin:{t:10,r:20,b:65,l:55},
    xaxis:{showgrid:false,tickfont:{size:11},tickangle:-30,type:'category'},
    yaxis:{showgrid:true,gridcolor:'#e2e8f0',rangemode:'tozero',tickfont:{size:11}},
    plot_bgcolor:'white',paper_bgcolor:'white',
    hovermode:'x unified',
    legend:{orientation:'h',y:-0.28,font:{size:11}}
  },PC);
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
  const COL='NÚMERO_PERIODOS_DE_DURACIÓN';
  const c={};
  rows.forEach(r=>{const v=r[COL];if(v&&v.trim()!=='')c[+v]=(c[+v]||0)+1;});
  const d=Object.entries(c).map(([k,v])=>({k:+k,v})).filter(e=>!isNaN(e.k)).sort((a,b)=>a.k-b.k);
  if(!d.length) return;
  Plotly.react(id,[{
    x:d.map(e=>e.k), y:d.map(e=>e.v), type:'bar',
    marker:{color:C,opacity:.82},
    text:d.map(e=>e.v.toLocaleString('es-CO')),
    textposition:'outside', cliponaxis:false,
    hovertemplate:'%{x} periodos<br><b>%{y:,}</b> programas<extra></extra>'
  }],{
    margin:{t:25,r:20,b:45,l:60},
    xaxis:{title:'Periodos',tickmode:'array',tickvals:d.map(e=>e.k),tickfont:{size:11}},
    yaxis:{title:'N. Programas',showgrid:true,gridcolor:'#e2e8f0',tickfont:{size:11}},
    plot_bgcolor:'white',paper_bgcolor:'white',bargap:.25
  },PC);
}

function plotTipoCambio(id, rows) {
  const el=document.getElementById(id); if(!el) return;
  const c={};
  rows.forEach(r => { (r['QUE_CAMBIO']||'').split(' | ').forEach(p => { const f=p.split(':')[0].trim(); if(f&&f!=='nan'&&f!=='') c[f]=(c[f]||0)+1; }); });
  const d=Object.entries(c).sort((a,b)=>b[1]-a[1]); if(!d.length) return;
  Plotly.react(id,[{x:d.map(e=>e[0]),y:d.map(e=>e[1]),type:'bar',
    marker:{color:'#d97706',opacity:.85},
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
  if(!pts.length){
    el.innerHTML='<div style="display:flex;align-items:center;justify-content:center;height:100%;color:#64748b;font-size:.82rem">Sin datos de creditos para comparar</div>';
    return;
  }
  const vals=pts.flatMap(p=>[p.x,p.y]);
  const mn=Math.min(...vals), mx=Math.max(...vals);
  Plotly.react(id,[
    {x:pts.map(p=>p.x),y:pts.map(p=>p.y),text:pts.map(p=>p.t),
     mode:'markers',type:'scatter',
     marker:{color:'#d97706',size:8,opacity:.7},
     hovertemplate:'<b>%{text}</b><br>Antes: %{x} creditos<br>Despues: %{y} creditos<extra></extra>'},
    {x:[mn,mx],y:[mn,mx],mode:'lines',
     line:{color:'#94a3b8',width:1,dash:'dot'},hoverinfo:'skip',showlegend:false}
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
  renderTbl(filtered);
}

// ── Render all ─────────────────────────────────────────────────────────────
function renderAll(rows) {
  document.getElementById('f-count').textContent = fmt(rows.length) + ' programas';

  plotDonut('ch-sector', rows, 'SECTOR');
  plotHBar('ch-instituciones', rows, 'NOMBRE_INSTITUCIÓN', C, 10, 32);
  plotHBar('ch-division',      rows, 'DIVISIÓN UNINORTE',  C, 12);
  plotHBar('ch-depto',         rows, 'DEPARTAMENTO_OFERTA_PROGRAMA', '#6366f1', 15);

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

  renderTbl(rows);
}

// ── Init ───────────────────────────────────────────────────────────────────
applyFilters();
</script>
</body>
</html>
"""

if __name__ == "__main__":
    main()
