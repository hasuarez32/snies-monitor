"""
send_report.py
--------------
Construcción y envío del correo de reporte SNIES para pregrado por SMTP.

Variables de entorno requeridas:
    SMTP_USER      — dirección de correo remitente (ej. monitor@uninorte.edu.co)
    SMTP_PASS      — contraseña / app-password de la cuenta
    DESTINATARIOS  — lista separada por comas (ej. a@u.edu.co,b@u.edu.co)
"""

import os
import logging
import smtplib
from datetime import date
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

import pandas as pd

log = logging.getLogger(__name__)

ROOT          = Path(__file__).parent.parent
NOVEDADES_DIR = ROOT / "data" / "novedades"

# Configuración SMTP Office 365
SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587

DASHBOARD_URL = "https://hasuarez32.github.io/snies-monitor/"

# ── HTML helpers ──────────────────────────────────────────────────────────────

def _tabla_html(df: pd.DataFrame | None, color_header: str) -> str:
    """Genera una tabla HTML con las primeras 10 filas del DataFrame."""
    if df is None or df.empty:
        return (
            "<p style='color:#666;font-family:Arial,sans-serif;font-size:13px;'>"
            "Sin novedades este día.</p>"
        )

    # Columnas preferidas para la vista previa del correo
    candidatas = [
        "NOMBRE_DEL_PROGRAMA",
        "NOMBRE_INSTITUCIÓN",
        "MUNICIPIO_OFERTA_PROGRAMA",
        "DIVISIÓN UNINORTE",
        "QUE_CAMBIO",
    ]
    cols = [c for c in candidatas if c in df.columns]
    if not cols:
        cols = df.columns[:5].tolist()

    style_tabla = (
        "border-collapse:collapse;width:100%;font-family:Arial,sans-serif;"
        "font-size:12px;margin-bottom:20px;"
    )
    style_th = (
        f"background-color:{color_header};color:#FFFFFF;padding:10px;"
        "text-align:left;border:1px solid #ddd;"
    )
    style_td = "padding:8px;border:1px solid #ddd;color:#333;text-align:left;"

    html = f'<table style="{style_tabla}"><thead><tr>'
    for col in cols:
        html += f'<th style="{style_th}">{col.replace("_", " ")}</th>'
    html += "</tr></thead><tbody>"

    for _, row in df.head(10).iterrows():
        html += "<tr>"
        for col in cols:
            val = row.get(col, "")
            html += f'<td style="{style_td}">{val}</td>'
        html += "</tr>"

    html += "</tbody></table>"

    if len(df) > 10:
        html += (
            f"<p style='font-size:11px;color:#666;'>"
            f"... y {len(df) - 10} registro(s) más en el adjunto Excel.</p>"
        )
    return html


def _bloque_pregrado(res: dict | None) -> str:
    """Genera el bloque HTML de pregrado."""
    if res is None:
        return (
            "<h3 style='color:#003893;'>Pregrado</h3>"
            f"<p style='color:#dc3545;'>"
            f"Error procesando Pregrado. Revisar los logs del workflow.</p>"
        )

    nuevos     = res.get("nuevos",     pd.DataFrame())
    inactivos  = res.get("inactivos",  pd.DataFrame())
    modificados = res.get("modificados", pd.DataFrame())

    return f"""
    <h3 style="color:#003893;border-bottom:2px solid #003893;padding-bottom:6px;
               font-family:Arial,sans-serif;">
        Pregrado
    </h3>

    <h4 style="color:#28a745;font-family:Arial,sans-serif;">
        ✅ Programas Nuevos ({len(nuevos)})
    </h4>
    <p style="font-size:12px;color:#555;font-family:Arial,sans-serif;">
        Aparecieron hoy en el SNIES pero no estaban en el snapshot anterior.
    </p>
    {_tabla_html(nuevos, "#28a745")}

    <h4 style="color:#dc3545;font-family:Arial,sans-serif;">
        ❌ Programas Inactivos ({len(inactivos)})
    </h4>
    <p style="font-size:12px;color:#555;font-family:Arial,sans-serif;">
        Estaban en el snapshot anterior pero ya no figuran en el SNIES.
    </p>
    {_tabla_html(inactivos, "#dc3545")}

    <h4 style="color:#fd7e14;font-family:Arial,sans-serif;">
        ⚠️ Programas Modificados ({len(modificados)})
    </h4>
    <p style="font-size:12px;color:#555;font-family:Arial,sans-serif;">
        Código SNIES presente en ambos snapshots pero con cambios en:
        Modalidad, Créditos, Costo matrícula o Municipio.
    </p>
    {_tabla_html(modificados, "#fd7e14")}
    """


def construir_cuerpo(resultados: dict, today: date) -> str:
    today_str = today.strftime("%d/%m/%Y")

    bloques = _bloque_pregrado(resultados.get("pregrado"))

    return f"""
    <div style="font-family:Arial,sans-serif;max-width:950px;margin:auto;">
        <h2 style="color:#003893;border-bottom:3px solid #003893;padding-bottom:10px;">
            Reporte Diario SNIES — Pregrado — {today_str}
        </h2>
        <p style="font-size:13px;color:#333;">
            Monitoreo automático de programas académicos de pregrado en Colombia.
            Los archivos Excel completos de pregrado van adjuntos a este correo.
        </p>

        <div style="text-align:center;margin:24px 0;">
            <a href="{DASHBOARD_URL}"
               style="display:inline-block;background-color:#1e40af;color:#ffffff;
                      font-family:Arial,sans-serif;font-size:15px;font-weight:bold;
                      text-decoration:none;padding:14px 36px;border-radius:8px;
                      letter-spacing:0.03em;">
                📊 Ver Dashboard Completo
            </a>
            <p style="font-size:11px;color:#888;margin-top:8px;font-family:Arial,sans-serif;">
                Gráficos interactivos · Historial · Tablas con filtros
            </p>
        </div>

        {bloques}

        <p style="background-color:#f8f9fa;padding:12px;
                  border-left:5px solid #003893;font-size:11px;color:#555;">
            <strong>Fuente:</strong>
            SNIES — Sistema Nacional de Información de la Educación Superior.<br>
            <strong>Generado automáticamente</strong> por el workflow diario en GitHub Actions.
        </p>
    </div>
    """


# ── Envío ─────────────────────────────────────────────────────────────────────

def enviar_reporte(resultados: dict, today: date, chart_paths: list | None = None) -> None:
    """
    Construye y envía el correo HTML con los adjuntos de novedades y gráficos.
    Lee credenciales y destinatarios desde variables de entorno.
    """
    smtp_user     = os.environ["SMTP_USER"]
    smtp_pass     = os.environ["SMTP_PASS"]
    destinatarios = [d.strip() for d in os.environ["DESTINATARIOS"].split(",")]

    cuerpo = construir_cuerpo(resultados, today)

    msg            = MIMEMultipart("mixed")
    msg["Subject"] = f"Reporte SNIES Pregrado — {today.strftime('%d/%m/%Y')}"
    msg["From"]    = smtp_user
    msg["To"]      = ", ".join(destinatarios)
    msg.attach(MIMEText(cuerpo, "html", "utf-8"))

    # Adjuntar gráficos PNG
    for png_path in (chart_paths or []):
        try:
            with open(png_path, "rb") as f:
                part = MIMEBase("image", "png")
                part.set_payload(f.read())
            encoders.encode_base64(part)
            part.add_header(
                "Content-Disposition",
                f'attachment; filename="{Path(png_path).name}"',
            )
            msg.attach(part)
            log.info(f"Adjunto gráfico: {Path(png_path).name}")
        except Exception:
            log.exception(f"No se pudo adjuntar {png_path}")

    # Adjuntar solo los xlsx de novedades de pregrado
    adjuntos = sorted(NOVEDADES_DIR.glob("*_pregrado.xlsx"))
    for path in adjuntos:
        try:
            with open(path, "rb") as f:
                part = MIMEBase("application", "octet-stream")
                part.set_payload(f.read())
            encoders.encode_base64(part)
            part.add_header(
                "Content-Disposition",
                f'attachment; filename="{path.name}"',
            )
            msg.attach(part)
            log.info(f"Adjunto: {path.name}")
        except Exception:
            log.exception(f"No se pudo adjuntar {path.name}")

    log.info(f"Conectando a {SMTP_HOST}:{SMTP_PORT}...")
    with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
        server.ehlo()
        server.starttls()
        server.login(smtp_user, smtp_pass)
        server.sendmail(smtp_user, destinatarios, msg.as_bytes())

    log.info(f"Correo enviado a: {msg['To']}")
