"""
docs/generar_dashboard.py
Genera docs/index.html — dashboard estático para GitHub Pages.
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

COLS_NOVEDAD = [
    "FECHA_OBTENCION",
    "CÓDIGO_SNIES_DEL_PROGRAMA",
    "NOMBRE_DEL_PROGRAMA",
    "NOMBRE_INSTITUCIÓN",
    "SECTOR",
    "MODALIDAD",
    "DEPARTAMENTO_OFERTA_PROGRAMA",
    "DIVISIÓN UNINORTE",
]
COLS_MOD = COLS_NOVEDAD + ["QUE_CAMBIO"]


# ── helpers ──────────────────────────────────────────────────────────────────

def _read_xl(path, **kw):
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return pd.read_excel(path, **kw)


def _distribucion(df, campo, top_n=15):
    if df is None or df.empty or campo not in df.columns:
        return []
    counts = df[campo].value_counts().head(top_n)
    return [{"label": str(k), "value": int(v)} for k, v in counts.items()]


def _to_records(df, cols, max_rows=500):
    if df is None or df.empty:
        return []
    if "FECHA_OBTENCION" in df.columns:
        df = df.copy()
        df["_s"] = pd.to_datetime(df["FECHA_OBTENCION"], errors="coerce")
        df = df.sort_values("_s", ascending=False).drop(columns=["_s"])
    cols_ok = [c for c in cols if c in df.columns]
    sub = df[cols_ok].head(max_rows).copy()
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


# ── data loading ─────────────────────────────────────────────────────────────

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
            df = df.dropna(subset=["CÓDIGO_SNIES_DEL_PROGRAMA"])
            if len(df) > 2:
                df = df.iloc[:-2]
            puntos.append({"fecha": fecha.isoformat(), "total": len(df)})
        except Exception as e:
            print(f"  saltando {f.name}: {e}")
    puntos.sort(key=lambda x: x["fecha"])
    print(f"  historico: {len(puntos)} snapshots")
    return puntos


def leer_novedades(nombre):
    path = NOVEDADES_DIR / nombre
    if not path.exists():
        print(f"  {nombre}: no existe aún")
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

    kpis = {
        "total_activos":   historico[-1]["total"] if historico else 0,
        "nuevos_ultimo":   _count_last_run(nuevos_df),
        "inactivos_ultimo":_count_last_run(inactivos_df),
        "mods_ultimo":     _count_last_run(mods_df),
        "nuevos_total":    len(nuevos_df),
        "inactivos_total": len(inactivos_df),
        "mods_total":      len(mods_df),
    }

    data = {
        "ultima_actualizacion": historico[-1]["fecha"] if historico else "N/A",
        "historico":     historico,
        "kpis":          kpis,
        "por_sector":    _distribucion(snapshot_df, "SECTOR"),
        "por_depto":     _distribucion(snapshot_df, "DEPARTAMENTO_OFERTA_PROGRAMA"),
        "por_modalidad": _distribucion(snapshot_df, "MODALIDAD"),
        "nuevos":        _to_records(nuevos_df,    COLS_NOVEDAD),
        "inactivos":     _to_records(inactivos_df, COLS_NOVEDAD),
        "modificados":   _to_records(mods_df,      COLS_MOD),
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
    print("Dashboard generado OK")


# ── HTML generation ───────────────────────────────────────────────────────────

def generar_html(data: dict) -> str:
    # Embed JSON safely inside <script>: escape </ to avoid tag injection
    data_js = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    ultima  = data["ultima_actualizacion"]
    k       = data["kpis"]

    return HTML_TEMPLATE.replace("__DATA__", data_js)


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

/* ── header ── */
header{background:linear-gradient(135deg,var(--hdr1),var(--hdr2));color:#fff;
  padding:1.25rem 2rem;display:flex;justify-content:space-between;align-items:center}
header h1{font-size:1.35rem;font-weight:700;letter-spacing:-.01em}
header .sub{font-size:.8rem;opacity:.75;margin-top:.2rem}
.badge-update{background:rgba(255,255,255,.15);border:1px solid rgba(255,255,255,.3);
  padding:.5rem 1rem;border-radius:2rem;font-size:.75rem;text-align:right;white-space:nowrap}
.badge-update strong{display:block;font-size:.9rem}

/* ── layout ── */
main{max-width:1380px;margin:0 auto;padding:1.5rem 2rem}
section{margin-bottom:1.5rem}

/* ── KPI grid ── */
.kpi-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:1rem}
.kpi{background:var(--surface);border-radius:var(--radius);padding:1.25rem 1.5rem;
  box-shadow:0 1px 3px rgba(0,0,0,.07);border-left:4px solid var(--blue)}
.kpi.g{border-left-color:var(--green)}.kpi.r{border-left-color:var(--red)}.kpi.a{border-left-color:var(--amber)}
.kpi-label{font-size:.7rem;text-transform:uppercase;letter-spacing:.05em;color:var(--muted);margin-bottom:.4rem}
.kpi-val{font-size:2rem;font-weight:700;line-height:1}
.kpi-sub{font-size:.72rem;color:var(--muted);margin-top:.35rem}

/* ── card ── */
.card{background:var(--surface);border-radius:var(--radius);padding:1.25rem;
  box-shadow:0 1px 3px rgba(0,0,0,.07)}
.card-title{font-size:.7rem;font-weight:600;text-transform:uppercase;
  letter-spacing:.06em;color:var(--muted);margin-bottom:.9rem}
.chart-2col{display:grid;grid-template-columns:1fr 2fr;gap:1rem}

/* ── tabs ── */
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

/* ── table ── */
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

/* ── responsive ── */
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

  <!-- KPIs -->
  <section class="kpi-grid">
    <div class="kpi">
      <div class="kpi-label">Programas activos</div>
      <div class="kpi-val" id="k-total">–</div>
      <div class="kpi-sub">universitarios hoy</div>
    </div>
    <div class="kpi g">
      <div class="kpi-label">Nuevos (último run)</div>
      <div class="kpi-val" id="k-nue">–</div>
      <div class="kpi-sub" id="k-nue-sub">acumulado: –</div>
    </div>
    <div class="kpi r">
      <div class="kpi-label">Inactivos (último run)</div>
      <div class="kpi-val" id="k-ina">–</div>
      <div class="kpi-sub" id="k-ina-sub">acumulado: –</div>
    </div>
    <div class="kpi a">
      <div class="kpi-label">Modificados (último run)</div>
      <div class="kpi-val" id="k-mod">–</div>
      <div class="kpi-sub" id="k-mod-sub">acumulado: –</div>
    </div>
  </section>

  <!-- Historical chart -->
  <section class="card">
    <div class="card-title">Evolución histórica de programas universitarios activos</div>
    <div id="ch-hist" style="height:280px"></div>
  </section>

  <!-- Distribution charts -->
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

  <!-- Novedades tables -->
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
      <input class="search" placeholder="Buscar nuevos…" oninput="filter('nue',this.value)">
      <div class="tbl-wrap" id="tw-nue"></div>
    </div>
    <div id="tp-ina" class="tab-pane">
      <input class="search" placeholder="Buscar inactivos…" oninput="filter('ina',this.value)">
      <div class="tbl-wrap" id="tw-ina"></div>
    </div>
    <div id="tp-mod" class="tab-pane">
      <input class="search" placeholder="Buscar modificados…" oninput="filter('mod',this.value)">
      <div class="tbl-wrap" id="tw-mod"></div>
    </div>
  </section>

</main>

<script>
const D = __DATA__;

// ── KPIs ────────────────────────────────────────────────────────────────────
const fmt = n => (n ?? 0).toLocaleString('es-CO');
document.getElementById('fecha-update').textContent = D.ultima_actualizacion;
document.getElementById('k-total').textContent = fmt(D.kpis.total_activos);
document.getElementById('k-nue').textContent   = fmt(D.kpis.nuevos_ultimo);
document.getElementById('k-ina').textContent   = fmt(D.kpis.inactivos_ultimo);
document.getElementById('k-mod').textContent   = fmt(D.kpis.mods_ultimo);
document.getElementById('k-nue-sub').textContent = 'acumulado: ' + fmt(D.kpis.nuevos_total);
document.getElementById('k-ina-sub').textContent = 'acumulado: ' + fmt(D.kpis.inactivos_total);
document.getElementById('k-mod-sub').textContent = 'acumulado: ' + fmt(D.kpis.mods_total);

// ── Historical line ──────────────────────────────────────────────────────────
(function() {
  const h = D.historico;
  if (!h.length) return;
  Plotly.newPlot('ch-hist', [{
    x: h.map(p => p.fecha),
    y: h.map(p => p.total),
    type: 'scatter', mode: 'lines+markers',
    line: {color:'#2563eb', width:2.5},
    marker: {color:'#2563eb', size:6},
    fill: 'tozeroy', fillcolor: 'rgba(37,99,235,0.07)',
    hovertemplate: '%{x}<br><b>%{y:,}</b> programas<extra></extra>'
  }], {
    margin: {t:10,r:20,b:40,l:60},
    xaxis: {showgrid:false, tickfont:{size:11}},
    yaxis: {showgrid:true, gridcolor:'#e2e8f0', tickfont:{size:11}, rangemode:'tozero'},
    plot_bgcolor:'white', paper_bgcolor:'white', hovermode:'x unified'
  }, {responsive:true, displayModeBar:false});
})();

// ── Sector donut ─────────────────────────────────────────────────────────────
(function() {
  const d = D.por_sector;
  if (!d.length) return;
  Plotly.newPlot('ch-sector', [{
    labels: d.map(x => x.label),
    values: d.map(x => x.value),
    type:'pie', hole:0.45,
    marker:{colors:['#2563eb','#10b981','#f59e0b','#ef4444','#8b5cf6','#06b6d4']},
    textinfo:'label+percent',
    hovertemplate:'%{label}<br><b>%{value:,}</b><extra></extra>'
  }], {
    margin:{t:10,r:10,b:10,l:10}, showlegend:false,
    plot_bgcolor:'white', paper_bgcolor:'white'
  }, {responsive:true, displayModeBar:false});
})();

// ── Department bar ────────────────────────────────────────────────────────────
(function() {
  const d = [...D.por_depto].reverse();
  if (!d.length) return;
  Plotly.newPlot('ch-depto', [{
    y: d.map(x => x.label),
    x: d.map(x => x.value),
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

// ── Tables ───────────────────────────────────────────────────────────────────
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
    h += `<th onclick="sortTbl('${type}','${c}')">${HEAD[c]||c} <span style="opacity:.4">↕</span></th>`;
  });
  h += '</tr></thead><tbody>';
  if (!data.length) {
    h += `<tr><td colspan="${cols.length}" class="empty">Sin registros</td></tr>`;
  } else {
    data.forEach(r => {
      h += '<tr>' + cols.map(c => `<td>${r[c]||''}</td>`).join('') + '</tr>';
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

if __name__ == "__main__":
    main()
