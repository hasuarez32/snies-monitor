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

import os
import re
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
# Anclados al texto visible, no a IDs dinámicos JSF que cambian con cada deploy.
XPATHS = {
    "descarga": '//button[.//span[normalize-space()="Descargar programas"]]',
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

def _build_driver(download_dir: Path, headless: bool = True) -> webdriver.Chrome:
    opts = webdriver.ChromeOptions()
    if headless:
        opts.add_argument("--headless=new")
    opts.add_argument("--window-size=1920,1080")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.add_experimental_option("useAutomationExtension", False)
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


def _click_radio_box(driver: webdriver.Chrome, box_xpath: str, label: str, timeout: int = 30) -> None:
    """JS-click en el div.ui-radiobutton-box de PrimeFaces para disparar su handler jQuery."""
    el = WebDriverWait(driver, timeout).until(
        EC.presence_of_element_located((By.XPATH, box_xpath))
    )
    driver.execute_script("arguments[0].click();", el)
    log.info(f"[radio] click JS en box → {label}")


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
    Navega el portal SNIES, aplica filtros (institución activa, programa activo,
    pregrado) usando labels de texto y descarga el Excel.
    Devuelve la ruta al archivo Programas.xlsx dentro de download_dir.
    """
    expected_file = download_dir / "Programas.xlsx"
    partial_file  = download_dir / "Programas.crdownload"

    for f in (expected_file, partial_file):
        if f.exists():
            f.unlink()

    headless = os.environ.get("SNIES_HEADLESS", "1") != "0"
    driver = _build_driver(download_dir, headless=headless)
    try:
        log.info("[pregrado] Abriendo SNIES...")
        driver.get(SNIES_URL)
        time.sleep(8)

        screenshot_path = TMP_DIR / "debug_snies.png"
        driver.save_screenshot(str(screenshot_path))
        log.info(f"[pregrado] Screenshot guardado en {screenshot_path}")

        log.info("[pregrado] Aplicando filtros...")
        _click_radio_box(driver,
            '//label[normalize-space()="Activo"]/../div[contains(@class,"ui-radiobutton")]/div[contains(@class,"ui-radiobutton-box")]',
            "institución Activo")
        _wait_ajax(driver)
        time.sleep(3)

        _click_radio_box(driver,
            '//label[starts-with(normalize-space(),"Activo (")]/../div[contains(@class,"ui-radiobutton")]/div[contains(@class,"ui-radiobutton-box")]',
            "programa Activo")
        _wait_ajax(driver)
        time.sleep(3)

        _click_radio_box(driver,
            '//label[starts-with(normalize-space(),"Pregrado (")]/../div[contains(@class,"ui-radiobutton")]/div[contains(@class,"ui-radiobutton-box")]',
            "académico Pregrado")
        _wait_ajax(driver)
        time.sleep(5)

        driver.save_screenshot(str(TMP_DIR / "debug_post_filtros.png"))
        log.info("[pregrado] Screenshot post-filtros guardado")

        log.info("[pregrado] Solicitando descarga...")
        _safe_click(driver, XPATHS["descarga"])

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
    shutil.copy2(raw_file, archive_path)
    log.info(f"  Archivado {archive_path.name}")
    return archive_path


_PROG_RE = re.compile(r"^Programas (\d{2}-\d{2}-\d{2})(?:__\d{6})?\.xlsx$")


def get_snapshot_anterior(today: date) -> Path | None:
    """Devuelve el archivo más reciente de Programas/ con fecha estrictamente anterior a today."""
    candidates = []
    for f in PROGRAMAS_DIR.glob("Programas *.xlsx"):
        m = _PROG_RE.match(f.name)
        if not m:
            continue
        try:
            file_date = datetime.strptime(m.group(1), "%d-%m-%y").date()
        except ValueError:
            continue
        if file_date < today:
            candidates.append((file_date, f))
    if not candidates:
        return None
    return max(candidates, key=lambda x: x[0])[1]


# ── Pipeline de pregrado ─────────────────────────────────────────────────────

def procesar(cat: pd.DataFrame, today: date) -> dict:
    """
    Ejecuta el pipeline completo para pregrado.
    Devuelve {'nuevos': df, 'inactivos': df, 'modificados': df}.
    """
    log.info("── PREGRADO ──────────────────────────────────")
    vacio = {"nuevos": pd.DataFrame(), "inactivos": pd.DataFrame(), "modificados": pd.DataFrame()}

    # 1. Descargar (o reutilizar si ya existe el archivo de hoy)
    today_archive = PROGRAMAS_DIR / f"Programas {today.strftime('%d-%m-%y')}.xlsx"
    if today_archive.exists():
        log.info(f"[pregrado] Archivo de hoy ya archivado ({today_archive.name}). Saltando descarga.")
        raw_file = today_archive
        ya_archivado = True
    else:
        download_dir = TMP_DIR / "pregrado"
        download_dir.mkdir(parents=True, exist_ok=True)
        raw_file = descargar_snies(download_dir)
        ya_archivado = False

    # 2. Archivar el Excel crudo (solo si fue descargado ahora)
    if not ya_archivado:
        archivar_descarga(raw_file, today)

    # 3. Cargar snapshot de hoy
    df_hoy = load_snapshot(raw_file)
    log.info(f"[pregrado] Snapshot HOY: {len(df_hoy)} programas")

    # 4. Cargar snapshot anterior (el más reciente en Programas/ antes de hoy)
    anterior_path = get_snapshot_anterior(today)
    if anterior_path is None:
        log.warning("[pregrado] No hay snapshot anterior en Programas/. El de hoy quedará como línea base.")
        if not ya_archivado:
            raw_file.unlink(missing_ok=True)
        return vacio

    try:
        df_ant = load_snapshot(anterior_path)
    except Exception as e:
        log.warning(f"[pregrado] Snapshot anterior no legible ({e}). Abortando comparación.")
        if not ya_archivado:
            raw_file.unlink(missing_ok=True)
        return vacio

    log.info(f"[pregrado] Snapshot ANTERIOR: {anterior_path.name} ({len(df_ant)} programas)")

    # 5. Validar tamaño razonable (pregrado activo ≈ 8-10k programas)
    UMBRAL = 15_000
    if len(df_hoy) > UMBRAL:
        log.error(
            f"[pregrado] Snapshot HOY tiene {len(df_hoy)} programas — demasiados. "
            "Probable descarga sin filtros. Abortando comparación."
        )
        if not ya_archivado:
            raw_file.unlink(missing_ok=True)
        return vacio
    if len(df_ant) > UMBRAL:
        log.error(
            f"[pregrado] Snapshot ANTERIOR ({anterior_path.name}) tiene {len(df_ant)} programas "
            "— parece un archivo sin filtrar. Abortando comparación."
        )
        if not ya_archivado:
            raw_file.unlink(missing_ok=True)
        return vacio

    # 6. Detectar novedades
    nuevos, inactivos, modificados = detectar_novedades(df_hoy, df_ant, today)
    log.info(
        f"[pregrado] Nuevos={len(nuevos)} | "
        f"Inactivos={len(inactivos)} | "
        f"Modificados={len(modificados)}"
    )

    # 7. Agregar división Uninorte
    nuevos      = merge_division(nuevos,      cat)
    inactivos   = merge_division(inactivos,   cat)
    modificados = merge_division(modificados, cat)

    # 8. Acumular y guardar
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

    if not ya_archivado:
        raw_file.unlink(missing_ok=True)

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

    if today.weekday() == 0:  # 0 = lunes
        try:
            from send_report import enviar_reporte
            enviar_reporte(resultados, today, chart_paths)
        except Exception:
            log.exception("Error enviando el correo.")
    else:
        log.info("[correo] No es lunes — reporte semanal omitido.")

    log.info("╚══ Run finalizado. ══╝")


if __name__ == "__main__":
    main()
