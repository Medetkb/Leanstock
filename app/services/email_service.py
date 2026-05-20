import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from app.config import settings


def _send(to_email: str, subject: str, html: str):
    """Low-level SMTP send. Called from BackgroundTasks or Celery."""
    # Базовая функция отправки. Все остальные функции используют её.
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = settings.SMTP_FROM
    msg["To"] = to_email
    msg.attach(MIMEText(html, "html"))
    # MIME "alternative" — письмо в HTML формате

    with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT) as server:
        server.ehlo()
        server.starttls()
        # starttls() — шифруем соединение (обязательно для Gmail порт 587)
        server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
        server.sendmail(settings.SMTP_FROM, to_email, msg.as_string())


def send_verification_email(to_email: str, token: str):
    url = f"{settings.APP_URL}/auth/verify-email/{token}"
    # Формируем ссылку с токеном — пользователь кликает и его email подтверждается
    html = f"""
    <div style="font-family: Arial, sans-serif; max-width: 500px;">
        <h2>Welcome to LeanStock!</h2>
        <p>Click the button below to verify your email address:</p>
        <a href="{url}"
           style="background:#4f46e5;color:white;padding:12px 24px;
                  border-radius:6px;text-decoration:none;display:inline-block;">
            Verify Email
        </a>
        <p style="margin-top:16px;color:#666;">
            Or copy this link: <code>{url}</code>
        </p>
        <p style="color:#999;font-size:13px;">This link expires in 24 hours.</p>
    </div>
    """
    _send(to_email, "Verify your LeanStock account", html)
    # Письмо после регистрации — ссылка активна 24 часа


def send_password_reset_email(to_email: str, token: str):
    url = f"{settings.APP_URL}/auth/reset-password?token={token}"
    html = f"""
    <div style="font-family: Arial, sans-serif; max-width: 500px;">
        <h2>Password Reset</h2>
        <p>You requested a password reset for your LeanStock account.</p>
        <a href="{url}"
           style="background:#dc2626;color:white;padding:12px 24px;
                  border-radius:6px;text-decoration:none;display:inline-block;">
            Reset Password
        </a>
        <p style="margin-top:16px;color:#666;">
            Or copy this link: <code>{url}</code>
        </p>
        <p style="color:#999;font-size:13px;">
            This link expires in 1 hour. If you did not request this, ignore this email.
        </p>
    </div>
    """
    _send(to_email, "Reset your LeanStock password", html)
    # Письмо сброса пароля — ссылка активна 1 час


def send_transfer_notification_email(
    to_email: str,
    product_name: str,
    quantity: int,
    from_location: str,
    to_location: str,
):
    html = f"""
    <div style="font-family: Arial, sans-serif; max-width: 500px;">
        <h2>Inventory Transfer Completed ✓</h2>
        <table style="border-collapse:collapse;width:100%;">
            <tr><td style="padding:8px;border:1px solid #ddd;"><b>Product</b></td>
                <td style="padding:8px;border:1px solid #ddd;">{product_name}</td></tr>
            <tr><td style="padding:8px;border:1px solid #ddd;"><b>Quantity</b></td>
                <td style="padding:8px;border:1px solid #ddd;">{quantity} units</td></tr>
            <tr><td style="padding:8px;border:1px solid #ddd;"><b>From</b></td>
                <td style="padding:8px;border:1px solid #ddd;">{from_location}</td></tr>
            <tr><td style="padding:8px;border:1px solid #ddd;"><b>To</b></td>
                <td style="padding:8px;border:1px solid #ddd;">{to_location}</td></tr>
        </table>
        <p style="color:#666;font-size:13px;margin-top:12px;">
            This is an automated notification from LeanStock.
        </p>
    </div>
    """
    _send(to_email, f"Transfer complete: {product_name}", html)
    # Уведомление после трансфера: кто переместил, что, откуда, куда


def send_invite_email(to_email: str, username: str, role: str, token: str):
    url = f"{settings.APP_URL}/auth/verify-email/{token}"
    html = f"""
    <div style="font-family: Arial, sans-serif; max-width: 500px;">
        <h2>Вас добавили в LeanStock 🎉</h2>
        <p>Администратор создал для вас аккаунт:</p>
        <table style="border-collapse:collapse;width:100%;margin:12px 0;">
            <tr><td style="padding:8px;border:1px solid #ddd;"><b>Email</b></td>
                <td style="padding:8px;border:1px solid #ddd;">{to_email}</td></tr>
            <tr><td style="padding:8px;border:1px solid #ddd;"><b>Имя</b></td>
                <td style="padding:8px;border:1px solid #ddd;">{username}</td></tr>
            <tr><td style="padding:8px;border:1px solid #ddd;"><b>Роль</b></td>
                <td style="padding:8px;border:1px solid #ddd;">{role}</td></tr>
        </table>
        <p>Нажмите кнопку ниже, чтобы подтвердить email и начать работу:</p>
        <a href="{url}"
           style="background:#4f46e5;color:white;padding:12px 24px;
                  border-radius:6px;text-decoration:none;display:inline-block;margin:8px 0;">
            Подтвердить и войти
        </a>
        <p style="color:#999;font-size:13px;margin-top:12px;">
            Ссылка действует 48 часов.<br>
            Ваш пароль вам сообщит администратор.
        </p>
    </div>
    """
    _send(to_email, "Приглашение в LeanStock", html)
    # Invite письмо для новых сотрудников — содержит данные аккаунта и ссылку активации


def send_dead_stock_alert_email(to_email: str, product_name: str, days: int, new_discount: float):
    html = f"""
    <div style="font-family: Arial, sans-serif; max-width: 500px;">
        <h2>Dead Stock Alert ⚠️</h2>
        <p>A product has been sitting in inventory for a long time and received an automatic discount:</p>
        <ul>
            <li><b>Product:</b> {product_name}</li>
            <li><b>Days in inventory:</b> {days}</li>
            <li><b>New discount:</b> {new_discount}%</li>
        </ul>
        <p style="color:#666;font-size:13px;">
            This is an automated notification from the LeanStock dead-stock decay job.
        </p>
    </div>
    """
    _send(to_email, f"Dead stock alert: {product_name} now {new_discount}% off", html)


def send_low_stock_alert_email(to_email: str, product_name: str, sku: str, current_qty: int, min_stock: int):
    html = f"""
    <div style="font-family: Arial, sans-serif; max-width: 500px;">
        <h2>Low Stock Alert 🔴</h2>
        <p>A product has fallen at or below its minimum stock threshold:</p>
        <table style="border-collapse:collapse;width:100%;margin:12px 0;">
            <tr><td style="padding:8px;border:1px solid #ddd;"><b>Product</b></td>
                <td style="padding:8px;border:1px solid #ddd;">{product_name}</td></tr>
            <tr><td style="padding:8px;border:1px solid #ddd;"><b>SKU</b></td>
                <td style="padding:8px;border:1px solid #ddd;">{sku}</td></tr>
            <tr><td style="padding:8px;border:1px solid #ddd;"><b>Current Stock</b></td>
                <td style="padding:8px;border:1px solid #ddd;">{current_qty} units</td></tr>
            <tr><td style="padding:8px;border:1px solid #ddd;"><b>Minimum Required</b></td>
                <td style="padding:8px;border:1px solid #ddd;">{min_stock} units</td></tr>
        </table>
        <p style="color:#dc2626;font-weight:bold;">Please create a purchase order to restock this item.</p>
        <p style="color:#666;font-size:13px;">This is an automated notification from LeanStock.</p>
    </div>
    """
    _send(to_email, f"Low stock alert: {product_name} ({current_qty} remaining)", html)


def send_po_confirmation_email(to_email: str, po_id: int, supplier_name: str, items: list):
    rows = "".join(
        f"<tr><td style='padding:8px;border:1px solid #ddd;'>Product #{i['product_id']}</td>"
        f"<td style='padding:8px;border:1px solid #ddd;'>{i['qty']} units</td>"
        f"<td style='padding:8px;border:1px solid #ddd;'>${i['price']:.2f}</td></tr>"
        for i in items
    )
    html = f"""
    <div style="font-family: Arial, sans-serif; max-width: 600px;">
        <h2>Purchase Order #{po_id} Confirmation</h2>
        <p>Dear <b>{supplier_name}</b>, please confirm receipt of this purchase order.</p>
        <table style="border-collapse:collapse;width:100%;margin:12px 0;">
            <thead>
                <tr style="background:#f3f4f6;">
                    <th style="padding:8px;border:1px solid #ddd;text-align:left;">Product</th>
                    <th style="padding:8px;border:1px solid #ddd;text-align:left;">Qty</th>
                    <th style="padding:8px;border:1px solid #ddd;text-align:left;">Unit Price</th>
                </tr>
            </thead>
            <tbody>{rows}</tbody>
        </table>
        <p style="color:#666;font-size:13px;">
            Purchase Order #{po_id} from LeanStock inventory system.
        </p>
    </div>
    """
    _send(to_email, f"Purchase Order #{po_id} from LeanStock", html)
