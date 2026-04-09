"""
send_report.py
--------------
Construcción y envío del correo de reporte SNIES por SMTP (Office 365).

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


def _bloque_nivel(sfx: str, label: str, res: dict | None) -> str:
    """Genera el bloque HTML de un nivel (pregrado / posgrado)."""
    if res is None:
        return (
            f"<h3 style='color:#003893;'>{label}</h3>"
            f"<p style='color:#dc3545;'>"
            f"Error procesando {label}. Revisar los logs del workflow.</p>"
        )

    nuevos     = res.get("nuevos",     pd.DataFrame())
    inactivos  = res.get("inactivos",  pd.DataFrame())
    modificados = res.get("modificados", pd.DataFrame())

    return f"""
    <h3 style="color:#003893;border-bottom:2px solid #003893;padding-bottom:6px;
               font-family:Arial,sans-serif;">
        {label}
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

    bloques = _bloque_nivel("pregrado", "Pregrado", resultados.get("pregrado"))
    bloques += _bloque_nivel("posgrado", "Posgrado", resultados.get("posgrado"))

    return f"""
    <div style="font-family:Arial,sans-serif;max-width:950px;margin:auto;">
        <h2 style="color:#003893;border-bottom:3px solid #003893;padding-bottom:10px;">
            Reporte Diario SNIES — {today_str}
        </h2>
        <p style="font-size:13px;color:#333;">
            Monitoreo automático de programas académicos activos en Colombia.
            Los archivos Excel completos van adjuntos a este correo.
        </p>

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

def enviar_reporte(resultados: dict, today: date) -> None:
    """
    Construye y envía el correo HTML con los adjuntos de novedades.
    Lee credenciales y destinatarios desde variables de entorno.
    """
    smtp_user     = os.environ["SMTP_USER"]
    smtp_pass     = os.environ["SMTP_PASS"]
    destinatarios = [d.strip() for d in os.environ["DESTINATARIOS"].split(",")]

    cuerpo = construir_cuerpo(resultados, today)

    msg            = MIMEMultipart("mixed")
    msg["Subject"] = f"Reporte SNIES — {today.strftime('%d/%m/%Y')}"
    msg["From"]    = smtp_user
    msg["To"]      = ", ".join(destinatarios)
    msg.attach(MIMEText(cuerpo, "html", "utf-8"))

    # Adjuntar todos los xlsx de novedades que existan
    adjuntos = sorted(NOVEDADES_DIR.glob("*.xlsx"))
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
