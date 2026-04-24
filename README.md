# SNIES Monitor · Uninorte

[![Ver Dashboard](https://img.shields.io/badge/📊_Ver_Dashboard-GitHub_Pages-blue?style=for-the-badge)](https://hasuarez32.github.io/snies-monitor/)

Monitor automático de cambios en programas universitarios de pregrado registrados en el [SNIES](https://hecaa.mineducacion.gov.co/consultaspublicas/programas) para la Universidad del Norte (Uninorte).

## ¿Qué hace?

Corre cada día hábil a las 8:00 a.m. (hora Colombia) vía GitHub Actions:

1. Descarga el snapshot actual de programas universitarios activos desde el portal SNIES.
2. Compara con el snapshot anterior para detectar **nuevos**, **inactivos** y **modificados**.
3. Acumula los hallazgos en archivos Excel en `data/novedades/`.
4. Envía un reporte por correo.
5. Regenera el dashboard en GitHub Pages.

## Dashboard

El dashboard se publica automáticamente en:  
**<https://hasuarez32.github.io/snies-monitor/>**

Incluye:
- Evolución histórica del número de programas
- Distribución por sector y departamento
- Tablas interactivas de nuevos, inactivos y modificados (con búsqueda y orden)

> **Nota:** Para activar GitHub Pages ve a *Settings → Pages → Source: Deploy from branch → Branch: main / docs/*.

## Estructura

```
snies-monitor/
├── scripts/
│   ├── run_snies.py            # Pipeline pregrado
│   └── run_snies_posgrado.py   # Pipeline posgrado
├── docs/
│   ├── generar_dashboard.py    # Genera index.html
│   └── index.html              # Dashboard (auto-generado)
├── data/
│   ├── novedades/              # Nuevos / Inactivos / Modificados acumulados
│   └── Categorización divisiones SNIES.xlsx
├── Programas/                  # Snapshots históricos DD-MM-YY.xlsx
└── .github/workflows/
    └── snies_daily.yml         # Workflow diario
```

## Ejecución local

```bash
pip install -r requirements.txt
python scripts/run_snies.py          # descarga + compara + envía correo
python docs/generar_dashboard.py     # regenera el dashboard con datos locales
```
