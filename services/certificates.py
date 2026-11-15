import httpx
from email.message import EmailMessage
import aiosmtplib

from core.config import settings


async def process_and_send_certificate(cert_data: dict, order_id: int):
    """
    Запрашивает выпуск сертификата у Django и отправляет красивое письмо клиенту.
    """
    amount = cert_data.get("price")
    recipient_email = cert_data.get("recipient_email")

    # ==========================================
    # 1. ЗАПРАШИВАЕМ СОЗДАНИЕ СЕРТИФИКАТА У DJANGO
    # ==========================================
    django_payload = {
        "amount": amount,
        "order_id": order_id
    }

    headers = {"X-Service-Token": settings.SERVICE_API_KEY}

    async with httpx.AsyncClient(headers=headers, timeout=10.0) as client:
        try:
            resp = await client.post(
                f"{settings.WAREHOUSE_URL}/api/certificates/",  # Путь до эндпоинта в Django
                json=django_payload
            )

            if resp.status_code not in (200, 201):
                print(f"❌ Ошибка склада при выпуске сертификата: {resp.text}")
                return  # Прерываемся, чтобы не отправить письмо без кода

            # Достаем сгенерированный код из ответа Django
            response_data = resp.json()
            promo_code = response_data.get("code")

        except Exception as e:
            print(f"❌ Ошибка связи со складом: {e}")
            return

    # ==========================================
    # 2. ОТПРАВЛЯЕМ КРАСИВОЕ ПИСЬМО ПОЛУЧАТЕЛЮ
    # ==========================================
    msg = EmailMessage()
    msg["From"] = settings.SMTP_USER
    msg["To"] = recipient_email
    msg["Subject"] = "Вам подарок! Сертификат на косметику M.D.M 🎁"

    sender = cert_data.get("sender_name") or "Тайного поклонника"
    message_text = cert_data.get("message")

    # HTML-версия письма (стилизована под премиум-сегмент)
    html_content = f"""
    <html>
      <body style="font-family: 'Helvetica Neue', Helvetica, Arial, sans-serif; color: #1a1a1a; background-color: #fafafa; padding: 40px 0;">
        <div style="max-w-500px; margin: 0 auto; background: #ffffff; padding: 40px; border-radius: 12px; box-shadow: 0 4px 15px rgba(0,0,0,0.05);">

          <h2 style="text-align: center; font-weight: 300; letter-spacing: 2px; color: #000; margin-bottom: 30px;">M.D.M</h2>

          <p style="font-size: 16px; line-height: 1.6;">Здравствуйте!</p>
          <p style="font-size: 16px; line-height: 1.6;">Вам подарили сертификат на сумму <b>{amount} руб.</b> от <i>{sender}</i>.</p>

          {"<div style='background: #f9f9f9; border-left: 3px solid #000; padding: 15px; margin: 20px 0; font-style: italic;'>" + message_text + "</div>" if message_text else ""}

          <div style="background: #000000; color: #ffffff; text-align: center; padding: 20px; font-size: 28px; font-weight: 300; letter-spacing: 4px; margin: 30px 0; border-radius: 8px;">
            {promo_code}
          </div>

          <p style="font-size: 14px; color: #666; text-align: center; margin-bottom: 30px;">
            Используйте этот код в корзине при оформлении заказа на нашем сайте.
          </p>

          <div style="text-align: center;">
            <a href="https://твой-сайт.ру" style="background: #000; color: #fff; padding: 12px 30px; text-decoration: none; border-radius: 6px; font-weight: 500;">Перейти в магазин</a>
          </div>

        </div>
      </body>
    </html>
    """

    msg.set_content("Пожалуйста, включите отображение HTML в вашем почтовом клиенте.")
    msg.add_alternative(html_content, subtype='html')

    try:
        await aiosmtplib.send(
            msg,
            hostname=settings.SMTP_HOST,
            port=settings.SMTP_PORT,
            username=settings.SMTP_USER,
            password=settings.SMTP_PASSWORD,
            use_tls=True
        )
        print(f"✅ Сертификат {promo_code} успешно отправлен на {recipient_email}")
    except Exception as e:
        print(f"❌ Ошибка при отправке письма на {recipient_email}: {e}")