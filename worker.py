import asyncio
import html  # ВАЖНО: нужно для безопасной отправки в Telegram
import httpx
from sqlalchemy.future import select

from core.config import settings
from db.postgres import AsyncSessionLocal
from models.outbox import OutboxEvent


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
        stmt = select(OutboxEvent).where(OutboxEvent.processed == False).order_by(OutboxEvent.created_at).limit(50)
        result = await session.execute(stmt)
        events = result.scalars().all()

        if not events:
            return

        print(f"Найдено необработанных событий: {len(events)}")
        headers = {"X-Service-Token": settings.SERVICE_API_KEY}

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
                        name_parts = payload["customer_name"].strip().split(" ", 1)
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
                                # ИСПРАВЛЕНО: убрал перенос строки в f-строке
                                raise ValueError(
                                    f"Ошибка создания клиента: HTTP {create_resp.status_code} {create_resp.text}")

                        created_sale_id = None
                        is_new_sale = False

                        # Идемпотентность
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

                        # Создаем заказ в складе
                        if not created_sale_id:
                            sale_items = [
                                {"product": i["product_id"], "quantity": i["quantity"], "sale_price": float(i["price"])}
                                for i in payload["items"]
                            ]
                            sale_data = {
                                "warehouse": payload.get("warehouse_id", settings.DEFAULT_WAREHOUSE_ID),
                                "customer": customer_id,
                                "comment": f"Заказ #{local_order_id}. Email: {payload.get('customer_email', '')}",
                                "posted": False,
                                "is_online": True,
                                "external_id": local_order_id,
                                "items": sale_items
                            }
                            sale_resp = await client.post(f"{settings.WAREHOUSE_URL}/api/sales/", json=sale_data)

                            if sale_resp.status_code not in (200, 201):
                                # ИСПРАВЛЕНО: убрал перенос строки в f-строке
                                raise ValueError(f"Ошибка создания Sale: HTTP {sale_resp.status_code} {sale_resp.text}")

                            created_sale_id = sale_resp.json().get("id")
                            is_new_sale = True

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
                                        prod_resp = await client.get(
                                            f"{settings.WAREHOUSE_URL}/api/products/{item['product_id']}/")
                                        if prod_resp.status_code == 200:
                                            product_name = prod_resp.json().get("name", product_name)
                                    except Exception as e:
                                        print(f"Сетевая ошибка при получении имени товара: {e}")

                                # Экранируем HTML (иначе Telegram отбросит сообщение с ошибкой 400, если будут символы < > &)
                                safe_product_name = html.escape(product_name)
                                items_text += f"• {safe_product_name} — {item['quantity']} шт. ({item_total} руб.)\n"

                            order_url = f"{settings.WAREHOUSE_URL}/inventory/sale/{created_sale_id}/"
                            safe_customer_name = html.escape(payload['customer_name'])

                            tg_msg = (
                                f"🚨 <b>НОВЫЙ ЗАКАЗ #{local_order_id}</b>\n\n"
                                f"👤 <b>Клиент:</b> {safe_customer_name}\n"
                                f"📞 <b>Телефон:</b> {phone}\n"
                                f"💳 <b>Сумма:</b> {total_sum} руб.\n\n"
                                f"📦 <b>Состав заказа:</b>\n{items_text}\n"
                                f"🔗 <a href='{order_url}'>Открыть заказ (не оплачен)</a>"
                            )
                            await send_telegram_message(client, tg_msg)

                        event.processed = True
                        event.error_message = None
                        print(f"Событие создания заказа #{local_order_id} успешно обработано!")

                    # ==========================================
                    # 2. ОБРАБОТКА: ОПЛАТА ЗАКАЗА
                    # ==========================================
                    elif event.event_type == "order_paid":
                        payment_id = payload.get("payment_id")
                        amount = payload.get("amount")

                        tg_msg = (
                            f"✅ <b>ОПЛАТА ПОСТУПИЛА!</b>\n\n"
                            f"🛒 <b>Заказ:</b> #{local_order_id}\n"
                            f"💰 <b>Сумма:</b> {amount} руб.\n"
                            f"💳 <b>Транзакция:</b> {payment_id}"
                        )
                        await send_telegram_message(client, tg_msg)

                        event.processed = True
                        event.error_message = None
                        print(f"Событие оплаты для заказа #{local_order_id} успешно обработано.")

                    # ==========================================
                    # 3. НЕИЗВЕСТНОЕ СОБЫТИЕ
                    # ==========================================
                    else:
                        event.processed = True
                        event.error_message = f"Неизвестный тип события: {event.event_type}"
                        print(event.error_message)

                except ValueError as e:
                    event.processed = True
                    event.error_message = str(e)
                    print(f"Бизнес-ошибка (заказ #{local_order_id}): {e}")

                except Exception as e:
                    event.error_message = f"Требует повтора: {str(e)}"
                    print(f"Сетевая ошибка (заказ #{local_order_id}): {e}")

                # ИНДИВИДУАЛЬНЫЙ КОММИТ
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