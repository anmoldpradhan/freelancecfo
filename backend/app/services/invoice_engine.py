"""
Invoice engine — handles PDF generation, S3 upload, and SendGrid delivery.
"""
import io
import logging
import boto3
from datetime import date
from decimal import Decimal
from jinja2 import Environment, FileSystemLoader, select_autoescape
from weasyprint import HTML
from sendgrid import SendGridAPIClient
from sendgrid.helpers.mail import (
    Mail, Attachment, FileContent, FileName,
    FileType, Disposition
)
import base64

from app.core.config import settings

logger = logging.getLogger(__name__)

# Jinja2 template environment — loads from templates/ directory
_template_dir = str(__file__).replace("invoice_engine.py", "templates")
jinja_env = Environment(
    loader=FileSystemLoader(_template_dir),
    autoescape=select_autoescape(["html"]),
)


# ── PDF Generation ────────────────────────────────────────────────────────────

def generate_pdf(invoice_data: dict) -> bytes:
    """
    Renders the invoice HTML template and converts to PDF bytes.
    Returns raw PDF bytes ready for S3 upload or HTTP streaming.
    """
    template = jinja_env.get_template("invoice.html")
    html_content = template.render(**invoice_data)

    pdf_bytes = HTML(string=html_content).write_pdf()
    logger.info("PDF generated for invoice %s", invoice_data.get("invoice_number"))
    return pdf_bytes


# ── S3 Storage ────────────────────────────────────────────────────────────────

def upload_pdf_to_s3(pdf_bytes: bytes, invoice_number: str) -> str:
    """
    Uploads PDF to S3 and returns the S3 key.
    Key format: invoices/{invoice_number}.pdf
    Returns empty string if S3 is not configured (dev mode).
    """
    if not settings.aws_s3_bucket or not settings.aws_access_key_id:
        logger.warning("S3 not configured — skipping upload for %s", invoice_number)
        return ""

    s3_key = f"invoices/{invoice_number}.pdf"

    try:
        s3 = boto3.client(
            "s3",
            aws_access_key_id=settings.aws_access_key_id,
            aws_secret_access_key=settings.aws_secret_access_key,
        )
        s3.put_object(
            Bucket=settings.aws_s3_bucket,
            Key=s3_key,
            Body=pdf_bytes,
            ContentType="application/pdf",
        )
        logger.info("PDF uploaded to S3: %s", s3_key)
        return s3_key

    except Exception as e:
        logger.error("S3 upload failed for %s: %s", invoice_number, e)
        return ""


def download_pdf_from_s3(s3_key: str) -> bytes:
    """Downloads PDF bytes from S3 for streaming to client."""
    s3 = boto3.client(
        "s3",
        aws_access_key_id=settings.aws_access_key_id,
        aws_secret_access_key=settings.aws_secret_access_key,
    )
    response = s3.get_object(Bucket=settings.aws_s3_bucket, Key=s3_key)
    return response["Body"].read()


# ── SendGrid Email ────────────────────────────────────────────────────────────

def send_invoice_email(
    to_email: str,
    client_name: str,
    invoice_number: str,
    total: float,
    currency: str,
    pdf_bytes: bytes,
    trading_name: str = "FreelanceCFO",
) -> bool:
    """
    Sends invoice email via SendGrid with PDF attachment.
    Returns True on success, False on failure.
    Skips silently if SendGrid not configured (dev mode).
    """
    if not settings.sendgrid_api_key:
        logger.warning("SendGrid not configured — skipping email for %s", invoice_number)
        return False

    message = Mail(
        from_email=f"invoices@freelancecfo.com",
        to_emails=to_email,
        subject=f"Invoice {invoice_number} from {trading_name}",
        html_content=f"""
        <p>Dear {client_name},</p>
        <p>Please find attached invoice <strong>{invoice_number}</strong>
           for <strong>{currency} {total:.2f}</strong>.</p>
        <p>Thank you for your business.</p>
        <p>Best regards,<br>{trading_name}</p>
        """,
    )

    # Attach PDF
    encoded = base64.b64encode(pdf_bytes).decode()
    attachment = Attachment(
        FileContent(encoded),
        FileName(f"{invoice_number}.pdf"),
        FileType("application/pdf"),
        Disposition("attachment"),
    )
    message.attachment = attachment

    try:
        sg = SendGridAPIClient(settings.sendgrid_api_key)
        response = sg.send(message)
        logger.info(
            "Invoice email sent to %s | invoice=%s status=%d",
            to_email, invoice_number, response.status_code
        )
        return response.status_code in (200, 202)

    except Exception as e:
        logger.error("SendGrid failed for %s: %s", invoice_number, e)
        return False