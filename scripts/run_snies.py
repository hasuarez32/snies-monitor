"""
run_snies.py
------------
Orquestador principal del monitor SNIES para pregrado.
Descarga el snapshot de pregrado, detecta novedades,
acumula los resultados en data/novedades/, archiva cada Excel crudo en
Programas/ y llama al módulo de correo.

Ejecución:
    python scripts/run_snies.py
"""

import sys
import logging
import shutil
import time
from datetime import date, datetime
from pathlib import Path

import matplotlib
matplotlib.use("Agg")  # debe ir antes de cualquier import de pyplot

import pandas as pd
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import StaleElementReferenceException, TimeoutException
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager

# ── Logging ───────────────────────────────────────────────────────────────────
# Reconfigure stdout to UTF-8 so box-drawing chars don't crash on Windows cp1252
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

logging.basicConfig(
    stream=sys.stdout,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

# ── Rutas base ────────────────────────────────────────────────────────────────
ROOT          = Path(__file__).parent.parent
DATA_DIR      = ROOT / "data"
NOVEDADES_DIR = DATA_DIR / "novedades"
PROGRAMAS_DIR = ROOT / "Programas"
CAT_FILE      = DATA_DIR / "Categorización divisiones SNIES.xlsx"
TMP_DIR       = ROOT / "tmp"

NOVEDADES_DIR.mkdir(parents=True, exist_ok=True)
PROGRAMAS_DIR.mkdir(parents=True, exist_ok=True)
TMP_DIR.mkdir(parents=True, exist_ok=True)

# ── Constantes de descarga ────────────────────────────────────────────────────
SNIES_URL        = "https://hecaa.mineducacion.gov.co/consultaspublicas/programas"
DOWNLOAD_TIMEOUT = 120  # segundos máximos esperando la descarga

# ── XPaths del flujo de pregrado ─────────────────────────────────────────────
# If the portal is updated, run the page-dump snippet in tmp/ to re-derive IDs.
XPATHS = {
    "institucion": '//*[@id="formFiltro:j_idt35"]/tbody/tr[2]/td/div/div[2]/span',
    "programa":    '//*[@id="formFiltro:j_idt68"]/tbody/tr[2]/td/div/div[2]/span',
    "academico":   '//*[@id="formFiltro:j_idt109"]/tbody/tr[2]/td/div/div[2]/span',
    "formacion":   '//*[@id="formFiltro:j_idt116"]/tbody/tr[4]/td/div/div[2]/span',
    "descarga":    '//*[@id="j_idt169:j_idt171"]',
}

# ── Columnas de trabajo ───────────────────────────────────────────────────────
BASE_COLS = [
    "CÓDIGO_INSTITUCIÓN",
    "NOMBRE_INSTITUCIÓN",
    "SECTOR",
    "DEPARTAMENTO_OFERTA_PROGRAMA",
    "MUNICIPIO_OFERTA_PROGRAMA",
    "CÓDIGO_SNIES_DEL_PROGRAMA",
    "NOMBRE_DEL_PROGRAMA",
    "MODALIDAD",
    "NÚMERO_CRÉDITOS",
    "NÚMERO_PERIODOS_DE_DURACIÓN",
    "PERIODICIDAD",
    "COSTO_MATRÍCULA_ESTUD_NUEVOS",
    "PERIODICIDAD_ADMISIONES",
    "FECHA_DE_REGISTRO_EN_SNIES",
    "CINE_F_2013_AC_CAMPO_AMPLIO",
    "CINE_F_2013_AC_CAMPO_ESPECÍFIC",   # nombre truncado por Excel
    "CINE_F_2013_AC_CAMPO_DETALLADO",
    "NÚCLEO_BÁSICO_DEL_CONOCIMIENTO",
]

# Campos cuyo cambio clasifica un programa como "Modificado"
COLS_VIGILAR = [
    "MODALIDAD",
    "NÚMERO_CRÉDITOS",
    "COSTO_MATRÍCULA_ESTUD_NUEVOS",
    "MUNICIPIO_OFERTA_PROGRAMA",
]


# ── Selenium ──────────────────────────────────────────────────────────────────

def _build_driver(download_dir: Path) -> webdriver.Chrome:
    opts = webdriver.ChromeOptions()
    opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument(
        "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
    opts.add_experimental_option(
        "prefs",
        {
            "download.default_directory": str(download_dir.resolve()),
            "download.prompt_for_download": False,
            "download.directory_upgrade": True,
        },
    )
    return webdriver.Chrome(
        service=Service(ChromeDriverManager().install()),
        options=opts,
    )


def _safe_click(driver: webdriver.Chrome, xpath: str, timeout: int = 15) -> None:
    locator = (By.XPATH, xpath)
    for attempt in range(2):
        try:
            el = WebDriverWait(driver, timeout).until(EC.element_to_be_clickable(locator))
            el.click()
            return
        except (StaleElementReferenceException, TimeoutException):
            if attempt == 1:
                raise
            time.sleep(2)


def _wait_ajax(driver: webdriver.Chrome, timeout: int = 20) -> None:
    """
    Espera a que terminen las peticiones AJAX lanzadas por PrimeFaces/jQuery
    tras un click de filtro.  Si jQuery o PrimeFaces no están cargados en la
    página, la condición se evalúa como True de inmediato.
    Si el timeout vence (portal muy lento) se emite un warning y se continúa.
    """
    try:
        WebDriverWait(driver, timeout).until(
            lambda d: d.execute_script(
                "return (typeof jQuery === 'undefined' || jQuery.active === 0) && "
                "(typeof PrimeFaces === 'undefined' || PrimeFaces.ajax.Queue.isEmpty())"
            )
        )
    except TimeoutException:
        log.warning("AJAX no terminó en %ds; continuando de todas formas.", timeout)


def descargar_snies(download_dir: Path) -> Path:
    """
    Navega el portal SNIES con los filtros del nivel `sfx` y descarga el Excel.
    Devuelve la ruta al archivo Programas.xlsx dentro de download_dir.
    """
    xp            = XPATHS
    expected_file = download_dir / "Programas.xlsx"
    partial_file  = download_dir / "Programas.crdownload"

    # Limpiar restos de descargas anteriores
    for f in (expected_file, partial_file):
        if f.exists():
            f.unlink()

    driver = _build_driver(download_dir)
    try:
        log.info("[pregrado] Abriendo SNIES...")
        driver.get(SNIES_URL)
        driver.implicitly_wait(5)

        log.info("[pregrado] Aplicando filtros...")
        _safe_click(driver, xp["institucion"], timeout=30)
        _wait_ajax(driver)
        _safe_click(driver, xp["programa"], timeout=30)
        _wait_ajax(driver)
        _safe_click(driver, xp["academico"], timeout=30)
        _wait_ajax(driver)
        _safe_click(driver, xp["formacion"], timeout=30)
        _wait_ajax(driver)

        log.info("[pregrado] Solicitando descarga...")
        _safe_click(driver, xp["descarga"])

        elapsed = 0
        while elapsed < DOWNLOAD_TIMEOUT:
            time.sleep(5)
            elapsed += 5
            if expected_file.exists() and not partial_file.exists():
                log.info(f"[pregrado] Descarga completada en {elapsed}s.")
                break
            log.info(f"[pregrado] Esperando descarga... ({elapsed}s)")
        else:
            raise TimeoutError(
                f"[pregrado] Archivo no apareció tras {DOWNLOAD_TIMEOUT}s. "
                "Verifica que los XPaths del portal no hayan cambiado."
            )
    finally:
        driver.quit()

    return expected_file


# ── Carga de datos ────────────────────────────────────────────────────────────

def load_categorizacion() -> pd.DataFrame:
    return (
        pd.read_excel(CAT_FILE, sheet_name="Hoja3")[
            ["CINE_F_2013_AC_CAMPO_DETALLADO", "DIVISIÓN UNINORTE"]
        ]
        .drop_duplicates()
    )


def load_snapshot(path: Path) -> pd.DataFrame:
    """
    Lee un archivo Excel del SNIES, elimina las 2 filas de pie de página,
    filtra las columnas de trabajo y normaliza tipos.
    """
    df = pd.read_excel(path, sheet_name="Programas")
    df = df.iloc[:-2].copy()  # las 2 últimas filas son el aviso legal del SNIES

    # Intersección defensiva: sólo columnas que existen en este archivo
    cols_ok = [c for c in BASE_COLS if c in df.columns]
    df = df[cols_ok].copy()

    df["CÓDIGO_SNIES_DEL_PROGRAMA"] = pd.to_numeric(
        df["CÓDIGO_SNIES_DEL_PROGRAMA"], errors="coerce"
    )
    df = df.dropna(subset=["CÓDIGO_SNIES_DEL_PROGRAMA"])
    df["CÓDIGO_SNIES_DEL_PROGRAMA"] = df["CÓDIGO_SNIES_DEL_PROGRAMA"].astype(int)

    df["NÚMERO_CRÉDITOS"] = df["NÚMERO_CRÉDITOS"].fillna(0).astype(int)

    df["FECHA_DE_REGISTRO_EN_SNIES"] = pd.to_datetime(
        df["FECHA_DE_REGISTRO_EN_SNIES"], errors="coerce"
    ).dt.date

    return df


# ── Lógica de negocio ─────────────────────────────────────────────────────────

def detectar_novedades(
    df_hoy: pd.DataFrame,
    df_ant: pd.DataFrame,
    today: date,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """
    Compara dos snapshots y clasifica los programas:
    - Nuevos:      código en HOY pero no en ANTERIOR.
    - Inactivos:   código en ANTERIOR pero no en HOY.
    - Modificados: código en ambos con al menos un campo vigilado distinto.
      Genera columna QUE_CAMBIO con el detalle "CAMPO: anterior → nuevo".
    """
    snies_hoy = set(df_hoy["CÓDIGO_SNIES_DEL_PROGRAMA"])
    snies_ant = set(df_ant["CÓDIGO_SNIES_DEL_PROGRAMA"])

    nuevosDF    = df_hoy[df_hoy["CÓDIGO_SNIES_DEL_PROGRAMA"].isin(snies_hoy - snies_ant)].copy()
    inactivosDF = df_ant[df_ant["CÓDIGO_SNIES_DEL_PROGRAMA"].isin(snies_ant - snies_hoy)].copy()

    # ── Detectar modificados ──────────────────────────────────────────────────
    comunes = snies_hoy & snies_ant
    df_com_hoy = df_hoy[df_hoy["CÓDIGO_SNIES_DEL_PROGRAMA"].isin(comunes)]
    df_com_ant = df_ant[df_ant["CÓDIGO_SNIES_DEL_PROGRAMA"].isin(comunes)]

    # Deduplicar por código antes del merge para evitar producto cartesiano.
    # Si el snapshot tiene filas duplicadas con el mismo código (p.ej. error del
    # portal o varias modalidades sin variación de código), el merge many-to-many
    # generaría combinaciones falsas que se detectarían como modificados espurios.
    _KEY = "CÓDIGO_SNIES_DEL_PROGRAMA"
    dups_hoy = df_com_hoy.duplicated(subset=_KEY, keep=False).sum()
    dups_ant = df_com_ant.duplicated(subset=_KEY, keep=False).sum()
    if dups_hoy:
        log.warning(
            f"  Snapshot HOY tiene {dups_hoy} fila(s) con código SNIES duplicado "
            "en el conjunto 'comunes'. Se conserva la primera aparición."
        )
    if dups_ant:
        log.warning(
            f"  Snapshot ANTERIOR tiene {dups_ant} fila(s) con código SNIES duplicado "
            "en el conjunto 'comunes'. Se conserva la primera aparición."
        )
    df_com_hoy = df_com_hoy.drop_duplicates(subset=_KEY, keep="first")
    df_com_ant = df_com_ant.drop_duplicates(subset=_KEY, keep="first")

    comparativa = df_com_hoy.merge(
        df_com_ant,
        on=_KEY,
        suffixes=("_NUEVO", "_ANTIGUO"),
    )

    mascara = pd.Series(False, index=comparativa.index)
    for col in COLS_VIGILAR:
        col_n, col_a = f"{col}_NUEVO", f"{col}_ANTIGUO"
        if col_n in comparativa.columns and col_a in comparativa.columns:
            mascara |= (
                comparativa[col_n].fillna("").astype(str)
                != comparativa[col_a].fillna("").astype(str)
            )

    modificadosDF = comparativa[mascara].copy()

    def _que_cambio(row) -> str:
        partes = []
        for col in COLS_VIGILAR:
            col_n, col_a = f"{col}_NUEVO", f"{col}_ANTIGUO"
            if col_n in row.index and col_a in row.index:
                val_n = str(row[col_n]).strip()
                val_a = str(row[col_a]).strip()
                if val_n != val_a:
                    partes.append(f"{col}: {val_a} → {val_n}")
        return " | ".join(partes) if partes else "Cambio en otros campos"

    if not modificadosDF.empty:
        modificadosDF["QUE_CAMBIO"] = modificadosDF.apply(_que_cambio, axis=1)

    # _NUEVO  → nombre limpio (valor actual del programa)
    # _ANTIGUO → nombre_ANTERIOR (valor previo, para referencia)
    rn = {c: c[:-6]               for c in modificadosDF.columns if c.endswith("_NUEVO")}
    ra = {c: c[:-8] + "_ANTERIOR" for c in modificadosDF.columns if c.endswith("_ANTIGUO")}
    modificadosDF = modificadosDF.rename(columns={**rn, **ra})

    # ── Metadatos comunes ─────────────────────────────────────────────────────
    today_str = today.strftime("%Y-%m-%d")
    for df_tmp in (nuevosDF, inactivosDF, modificadosDF):
        df_tmp["FECHA_OBTENCION"] = today_str
        df_tmp["Estado"] = df_tmp["CÓDIGO_SNIES_DEL_PROGRAMA"].apply(
            lambda x: "Activo" if x in snies_hoy else "Inactivo"
        )

    return nuevosDF, inactivosDF, modificadosDF


def merge_division(df: pd.DataFrame, cat: pd.DataFrame) -> pd.DataFrame:
    cine_col = "CINE_F_2013_AC_CAMPO_DETALLADO"
    if cine_col not in df.columns or df.empty:
        df = df.copy()
        df["DIVISIÓN UNINORTE"] = "Sin clasificar"
        return df
    df = df.merge(cat, on=cine_col, how="left")
    df["DIVISIÓN UNINORTE"] = df["DIVISIÓN UNINORTE"].fillna("Sin clasificar")
    return df


def acumular(existing_path: Path, nuevo_df: pd.DataFrame) -> pd.DataFrame:
    """Concatena con el archivo existente y deduplica por código + fecha."""
    dedup_cols = ["CÓDIGO_SNIES_DEL_PROGRAMA", "FECHA_OBTENCION"]
    if existing_path.exists():
        existing = pd.read_excel(existing_path)
        if nuevo_df.empty:
            return existing
        combined = pd.concat([existing, nuevo_df], ignore_index=True)
        return combined.drop_duplicates(subset=dedup_cols, keep="last")
    return nuevo_df


def _guardar(df: pd.DataFrame, path: Path) -> None:
    df.to_excel(path, index=False, sheet_name="Sheet1")
    log.info(f"  Guardado {path.name} ({len(df)} filas)")


def archivar_descarga(raw_file: Path, today: date) -> Path:
    """Guarda una copia permanente del Excel crudo en Programas/."""
    PROGRAMAS_DIR.mkdir(parents=True, exist_ok=True)
    archive_path = PROGRAMAS_DIR / f"Programas {today.strftime('%d-%m-%y')}.xlsx"
    if archive_path.exists():
        stamp = datetime.now().strftime("%H%M%S")
        archive_path = PROGRAMAS_DIR / f"Programas {today.strftime('%d-%m-%y')}__{stamp}.xlsx"
    shutil.copy2(raw_file, archive_path)
    log.info(f"  Archivado {archive_path.name}")
    return archive_path


# ── Pipeline de pregrado ─────────────────────────────────────────────────────

def procesar(cat: pd.DataFrame, today: date) -> dict:
    """
    Ejecuta el pipeline completo para pregrado.
    Devuelve {'nuevos': df, 'inactivos': df, 'modificados': df}.
    """
    log.info("── PREGRADO ──────────────────────────────────")
    vacio = {"nuevos": pd.DataFrame(), "inactivos": pd.DataFrame(), "modificados": pd.DataFrame()}

    # 1. Descargar
    download_dir = TMP_DIR / "pregrado"
    download_dir.mkdir(parents=True, exist_ok=True)
    raw_file = descargar_snies(download_dir)

    # 2. Archivar el Excel crudo antes de cualquier limpieza o comparación.
    archivar_descarga(raw_file, today)

    # 3. Cargar snapshot de hoy
    df_hoy = load_snapshot(raw_file)
    log.info(f"[pregrado] Snapshot HOY: {len(df_hoy)} programas")

    # 4. Cargar snapshot anterior
    anterior_path = DATA_DIR / "Programas_pregrado_anterior.xlsx"
    if not anterior_path.exists():
        log.warning(
            "[pregrado] No hay snapshot anterior. "
            "Guardando el de hoy como línea base para el próximo run."
        )
        shutil.copy2(raw_file, anterior_path)
        raw_file.unlink(missing_ok=True)
        return vacio

    try:
        df_ant = load_snapshot(anterior_path)
    except Exception as e:
        log.warning(
            f"[pregrado] Snapshot anterior no legible ({e}). "
            "Reemplazando con el snapshot de hoy como nueva línea base."
        )
        shutil.copy2(raw_file, anterior_path)
        raw_file.unlink(missing_ok=True)
        return vacio
    log.info(f"[pregrado] Snapshot ANTERIOR: {len(df_ant)} programas")

    # 5. Detectar novedades
    nuevos, inactivos, modificados = detectar_novedades(df_hoy, df_ant, today)
    log.info(
        f"[pregrado] Nuevos={len(nuevos)} | "
        f"Inactivos={len(inactivos)} | "
        f"Modificados={len(modificados)}"
    )

    # 6. Agregar división Uninorte
    nuevos      = merge_division(nuevos,      cat)
    inactivos   = merge_division(inactivos,   cat)
    modificados = merge_division(modificados, cat)

    # 7. Acumular y guardar
    _guardar(
        acumular(NOVEDADES_DIR / "Nuevos_pregrado.xlsx", nuevos),
        NOVEDADES_DIR / "Nuevos_pregrado.xlsx",
    )
    _guardar(
        acumular(NOVEDADES_DIR / "Inactivos_pregrado.xlsx", inactivos),
        NOVEDADES_DIR / "Inactivos_pregrado.xlsx",
    )
    _guardar(
        acumular(NOVEDADES_DIR / "Modificados_pregrado.xlsx", modificados),
        NOVEDADES_DIR / "Modificados_pregrado.xlsx",
    )

    # 8. Rotar snapshot: raw de hoy → nuevo anterior
    shutil.copy2(raw_file, anterior_path)
    raw_file.unlink(missing_ok=True)
    log.info("[pregrado] Snapshot anterior actualizado.")

    return {"nuevos": nuevos, "inactivos": inactivos, "modificados": modificados}


# ── Entry point ───────────────────────────────────────────────────────────────

def main() -> None:
    today = date.today()
    log.info(f"╔══ Run SNIES — {today.isoformat()} ══╗")

    cat = load_categorizacion()
    resultados: dict[str, dict | None] = {"pregrado": None}

    try:
        resultados["pregrado"] = procesar(cat, today)
    except Exception:
        log.exception("Error fatal procesando pregrado.")

    # Generar gráficos antes del correo
    chart_paths = []
    try:
        sys.path.insert(0, str(ROOT))
        from analisis_historico_pregrado import generar_graficos
        chart_paths = generar_graficos()
    except Exception:
        log.exception("Error generando gráficos de novedades.")

    try:
        from send_report import enviar_reporte
        enviar_reporte(resultados, today, chart_paths)
    except Exception:
        log.exception("Error enviando el correo.")

    log.info("╚══ Run finalizado. ══╝")


if __name__ == "__main__":
    main()
