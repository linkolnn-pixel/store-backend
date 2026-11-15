from email.message import EmailMessage
import aiosmtplib
from core.config import settings


async def send_certificate_email(recipient_email: str, customer_name: str, certificates: list):
    """Асинхронная отправка красивого письма с промокодами"""
    if not recipient_email:
        return

    msg = EmailMessage()
    msg["Subject"] = "Ваш подарочный сертификат M.D.M 🤍"
    msg["From"] = settings.SMTP_USER
    msg["To"] = recipient_email

    # Формируем HTML-список кодов
    certs_html = "".join(
        f"<div style='padding: 15px; background: #f9f9f9; border-left: 4px solid #000; margin-bottom: 10px;'>"
        f"<p style='margin: 0; font-size: 14px; color: #666;'>Номинал: {c['amount']} ₽</p>"
        f"<p style='margin: 5px 0 0 0; font-size: 24px; font-weight: bold; letter-spacing: 2px;'>{c['code']}</p>"
        f"</div>"
        for c in certificates
    )

    html_content = f"""
    <html>
        <body style="font-family: sans-serif; color: #333; line-height: 1.5;">
            <h2 style="font-weight: 300;">Здравствуйте, {customer_name}!</h2>
            <p>Спасибо за ваш заказ. Ваши электронные подарочные сертификаты готовы к использованию:</p>
            {certs_html}
            <p>Вы можете применить этот промокод при оформлении заказа на нашем сайте или назвать его на оффлайн-приеме.</p>
        </body>
    </html>
    """

    msg.set_content("Пожалуйста, включите поддержку HTML для просмотра этого письма.")
    msg.add_alternative(html_content, subtype='html')

    try:
        await aiosmtplib.send(
            msg,
            hostname=settings.SMTP_HOST,
            port=settings.SMTP_PORT,
            username=settings.SMTP_USER,
            password=settings.SMTP_PASSWORD,
            use_tls=True  # Или start_tls=True, в зависимости от провайдера
        )
        print(f"Письмо с сертификатами успешно отправлено на {recipient_email}")
    except Exception as e:
        print(f"Ошибка при отправке письма: {e}")