import asyncio
import html
import httpx
from sqlalchemy.future import select

from core.config import settings
from db.postgres import AsyncSessionLocal
from models.outbox import OutboxEvent, OutboxStatus
from services.notifications import send_certificate_email  # <--- Импорт отправки email

headers = {"X-Service-Token": settings.SERVICE_API_KEY}


async def send_telegram_message(client: httpx.AsyncClient, text: str):
    """Отправка уведомления в Telegram"""
    url = f"https://api.telegram.org/bot{settings.TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": settings.TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML"
    }
    try:
        resp = await client.post(url, json=payload)
        if resp.status_code != 200:
            print(f"Ошибка Telegram API: {resp.text}")
    except Exception as e:
        print(f"Сбой при отправке в Telegram: {e}")


async def process_outbox_events():
    async with AsyncSessionLocal() as session:
        # Ограничиваем выборку 50 записями за раз
        stmt = select(OutboxEvent).where(
            OutboxEvent.processed == False,
            OutboxEvent.status == OutboxStatus.PENDING.value
        ).order_by(OutboxEvent.created_at).limit(50)

        result = await session.execute(stmt)
        events = result.scalars().all()

        if not events:
            return

        print(f"Найдено необработанных событий: {len(events)}")

        async with httpx.AsyncClient(headers=headers, timeout=15.0) as client:
            for event in events:
                payload = event.payload
                local_order_id = str(payload.get('local_order_id', ''))

                try:
                    # ==========================================
                    # 1. ОБРАБОТКА: СОЗДАНИЕ НОВОГО ЗАКАЗА
                    # ==========================================
                    if event.event_type == "order_created":
                        phone = payload["customer_phone"]

                        # Разбиваем строку с ФИО на имя и фамилию для Django
                        raw_name = payload.get("customer_name")
                        customer_name = raw_name.strip() if raw_name else "Без имени"
                        name_parts = customer_name.split(" ", 1)
                        first_name = name_parts[0]
                        last_name = name_parts[1] if len(name_parts) > 1 else "-"

                        # Ищем клиента
                        customers_resp = await client.get(
                            f"{settings.WAREHOUSE_URL}/api/customers/",
                            params={"phone": phone}
                        )

                        customer_id = None
                        if customers_resp.status_code == 200:
                            res = customers_resp.json()
                            res_list = res.get("results", res) if isinstance(res, dict) else res
                            if res_list:
                                customer_id = res_list[0]["id"]

                        # Создаем клиента
                        if not customer_id:
                            new_customer = {
                                "first_name": first_name,
                                "last_name": last_name,
                                "phone": phone
                            }
                            create_resp = await client.post(
                                f"{settings.WAREHOUSE_URL}/api/customers/",
                                json=new_customer
                            )
                            if create_resp.status_code in (200, 201):
                                customer_id = create_resp.json()["id"]
                            else:
                                raise ValueError(
                                    f"Ошибка создания клиента: HTTP {create_resp.status_code} {create_resp.text}")

                        created_sale_id = None
                        is_new_sale = False

                        # Идемпотентность (проверяем, не отправляли ли мы уже этот заказ)
                        if local_order_id:
                            check_resp = await client.get(
                                f"{settings.WAREHOUSE_URL}/api/sales/",
                                params={"external_id": local_order_id}
                            )
                            if check_resp.status_code == 200:
                                res = check_resp.json()
                                res_list = res.get("results", res) if isinstance(res, dict) else res
                                if res_list:
                                    created_sale_id = res_list[0]["id"]
                                    print(f"⚠️ Заказ #{local_order_id} уже есть в Django (ID {created_sale_id}).")

                        # Создаем заказ в складе (если его там еще нет)
                        if not created_sale_id:
                            sale_items = [
                                {"product_id": i["product_id"], "quantity": i["quantity"], "price": float(i["price"]),
                                 "name": i.get("name")}
                                for i in payload["items"]
                            ]

                            # ДОСТАЕМ ДАННЫЕ СКИДКИ И СЕРТИФИКАТА
                            order_details = payload.get("order_details", {})
                            promo_code = order_details.get("promo_code", None)
                            discount_amount = float(order_details.get("discount_amount", 0.0))

                            gift_certificate = payload.get("gift_certificate", None)
                            certificate_amount_used = float(order_details.get("certificate_amount_used", 0.0))

                            # Собираем комментарий
                            raw_comment = payload.get("comment")
                            base_comment = raw_comment.strip() if raw_comment else ""
                            comment = base_comment + "\n" if base_comment else ""
                            comment += f"Заказ #{local_order_id}. Email: {payload.get('customer_email', '')}"

                            if promo_code:
                                comment += f"\nПромокод: {promo_code} (Скидка: {discount_amount} руб.)"
                            if gift_certificate:
                                comment += f"\nСертификат: {gift_certificate} (Списано: {certificate_amount_used} руб.)"

                            sale_data = {
                                "warehouse": payload.get("warehouse_id", settings.DEFAULT_WAREHOUSE_ID),
                                "customer": customer_id,
                                "comment": comment,
                                "posted": False,
                                "is_online": True,
                                "external_id": local_order_id,
                                "items": sale_items,
                                "promo_code": promo_code,
                                "discount_amount": discount_amount,
                                "gift_certificate": gift_certificate
                            }

                            sale_resp = await client.post(f"{settings.WAREHOUSE_URL}/api/sales/", json=sale_data)

                            if sale_resp.status_code not in (200, 201):
                                raise ValueError(f"Ошибка создания Sale: HTTP {sale_resp.status_code} {sale_resp.text}")

                            response_data = sale_resp.json()
                            created_sale_id = response_data.get("id")
                            is_new_sale = True

                            # ==========================================
                            # 🚀 НОВАЯ ЛОГИКА: ОТПРАВКА СЕРТИФИКАТОВ
                            # ==========================================
                            generated_certificates = response_data.get("generated_certificates", [])
                            customer_email = payload.get("customer_email")

                            if generated_certificates and customer_email:
                                print(f"Отправка {len(generated_certificates)} сертификатов на {customer_email}")
                                # Вызываем функцию асинхронно, чтобы не тормозить цикл воркера
                                asyncio.create_task(
                                    send_certificate_email(
                                        recipient_email=customer_email,
                                        customer_name=customer_name,
                                        certificates=generated_certificates
                                    )
                                )

                        # Отправка в Telegram о новом заказе
                        if is_new_sale:
                            total_sum = 0
                            items_text = ""
                            for item in payload["items"]:
                                item_total = float(item["price"]) * item["quantity"]
                                total_sum += item_total

                                product_name = item.get("name", f"Товар ID {item['product_id']}")
                                if "name" not in item:
                                    try:
                                        # Не делаем запрос в Django, если это сертификат (начинается с CERT_)
                                        if not str(item['product_id']).startswith("CERT_"):
                                            prod_resp = await client.get(
                                                f"{settings.WAREHOUSE_URL}/api/products/{item['product_id']}/")
                                            if prod_resp.status_code == 200:
                                                product_name = prod_resp.json().get("name", product_name)
                                    except Exception as e:
                                        print(f"Сетевая ошибка при получении имени товара: {e}")

                                safe_product_name = html.escape(product_name)
                                items_text += f"• {safe_product_name} — {item['quantity']} шт. ({item_total} руб.)\n"

                            if discount_amount > 0:
                                total_sum -= discount_amount
                                items_text += f"\n🎁 <b>Скидка (промокод {promo_code}):</b> -{discount_amount} руб.\n"

                            if certificate_amount_used > 0:
                                total_sum -= certificate_amount_used
                                items_text += f"\n💳 <b>Оплачено картой ({gift_certificate}):</b> -{certificate_amount_used} руб.\n"

                            payment_status = "полностью оплачен картой" if total_sum <= 0 else "ожидает доплаты"
                            order_url = f"{settings.WAREHOUSE_URL}/inventory/sale/{created_sale_id}/"
                            safe_customer_name = html.escape(payload['customer_name'])

                            tg_msg = (
                                f"🚨 <b>НОВЫЙ ЗАКАЗ #{local_order_id}</b>\n\n"
                                f"👤 <b>Клиент:</b> {safe_customer_name}\n"
                                f"📞 <b>Телефон:</b> {phone}\n"
                                f"💳 <b>К оплате:</b> {max(0, total_sum)} руб. <i>({payment_status})</i>\n\n"
                                f"📦 <b>Состав заказа:</b>\n{items_text}\n"
                                f"🔗 <a href='{order_url}'>Открыть заказ в админке</a>"
                            )
                            await send_telegram_message(client, tg_msg)

                        event.processed = True
                        event.error_message = None
                        print(f"Событие создания заказа #{local_order_id} успешно обработано!")

                    # ==========================================
                    # 2. ОБРАБОТКА: ОПЛАТА ЗАКАЗА (С АВТО-ПРОВЕДЕНИЕМ)
                    # ==========================================
                    elif event.event_type == "order_paid":
                        payment_id = payload.get("payment_id")
                        amount = payload.get("amount")

                        # 1. Ищем ID заказа в Django по нашему external_id
                        check_resp = await client.get(
                            f"{settings.WAREHOUSE_URL}/api/sales/",
                            params={"external_id": local_order_id}
                        )

                        sale_id = None
                        if check_resp.status_code == 200:
                            res = check_resp.json()
                            res_list = res.get("results", res) if isinstance(res, dict) else res
                            if res_list:
                                sale_id = res_list[0]["id"]

                        if not sale_id:
                            raise ValueError(f"Не удалось найти заказ {local_order_id} в Django для списания остатков.")

                        # 2. Дергаем эндпоинт ПРОВЕДЕНИЯ (/post/), чтобы списать остатки
                        post_resp = await client.post(
                            f"{settings.WAREHOUSE_URL}/api/sales/{sale_id}/post/"
                        )

                        order_url = f"{settings.WAREHOUSE_URL}/inventory/sale/{sale_id}/"

                        if post_resp.status_code not in (200, 201):
                            # ДЖАНГО ВЕРНУЛ ОШИБКУ (НАПРИМЕР, НЕ ХВАТАЕТ ОСТАТКОВ)
                            error_text = html.escape(post_resp.text)

                            tg_msg = (
                                f"⚠️ <b>ВНИМАНИЕ! НЕ ХВАТКА ТОВАРА</b>\n\n"
                                f"🛒 <b>Заказ:</b> #{local_order_id}\n"
                                f"💰 <b>Сумма:</b> {amount} руб.\n"
                                f"❌ <b>Ответ склада:</b> {error_text[:250]}\n\n"
                                f"<i>Заказ успешно передан на Склад (возможно, не хватает товара). Требуется ручная проверка!</i>\n\n"
                                f"🔗 <a href='{order_url}'>Проверить заказ вручную</a>"
                            )
                            await send_telegram_message(client, tg_msg)

                            event.processed = True
                            event.error_message = f"Оплачен, но не проведен (ошибка склада): {post_resp.text}"
                            print(f"⚠️ Ошибка проведения заказа #{local_order_id}, отправлено уведомление менеджерам.")

                        else:
                            # 3. УСПЕШНОЕ ПРОВЕДЕНИЕ И СПИСАНИЕ ОСТАТКОВ
                            tg_msg = (
                                f"✅ <b>ОПЛАТА ПОСТУПИЛА И ЗАКАЗ ПРОВЕДЕН!</b>\n\n"
                                f"🛒 <b>Заказ:</b> #{local_order_id}\n"
                                f"💰 <b>Сумма:</b> {amount} руб.\n"
                                f"💳 <b>Транзакция:</b> {payment_id}\n"
                                f"🔗 <a href='{order_url}'>Посмотреть заказ</a>"
                            )
                            await send_telegram_message(client, tg_msg)

                            event.processed = True
                            event.error_message = None
                            print(f"Событие оплаты для заказа #{local_order_id} успешно обработано (остатки списаны).")

                    # ==========================================
                    # 3. НЕИЗВЕСТНОЕ СОБЫТИЕ
                    # ==========================================
                    else:
                        event.processed = True
                        event.error_message = f"Неизвестный тип события: {event.event_type}"
                        print(event.error_message)

                except ValueError as e:
                    event.processed = True
                    event.status = "ERROR"
                    event.error_message = str(e)
                    print(f"Бизнес-ошибка (заказ #{local_order_id}): {e}")

                except Exception as e:
                    event.error_message = f"Требует повтора: {str(e)}"
                    print(f"Сетевая ошибка (заказ #{local_order_id}): {e}")

                # ИНДИВИДУАЛЬНЫЙ КОММИТ (сохраняем статус события в БД)
                await session.commit()


async def main():
    print("Воркер запущен. Ожидание событий из Outbox...")
    while True:
        try:
            await process_outbox_events()
        except Exception as e:
            print(f"Критическая ошибка подключения к БД: {e}")

        await asyncio.sleep(5)


if __name__ == "__main__":
    asyncio.run(main())