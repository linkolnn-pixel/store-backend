import asyncio
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
        # Ограничиваем выборку 50 записями за раз (защита от переполнения памяти)
        stmt = select(OutboxEvent).where(OutboxEvent.processed == False).order_by(OutboxEvent.created_at).limit(50)
        result = await session.execute(stmt)
        events = result.scalars().all()

        if not events:
            return

        print(f"Найдено необработанных заказов: {len(events)}")
        headers = {"X-Service-Token": settings.SERVICE_API_KEY}

        async with httpx.AsyncClient(headers=headers, timeout=15.0) as client:
            for event in events:
                payload = event.payload
                local_order_id = str(payload.get('local_order_id', ''))

                try:
                    # --- ЭТАП 1: КЛИЕНТ ---
                    # Телефон теперь гарантированно валидный благодаря FastAPI
                    phone = payload["customer_phone"]

                    # Разбиваем строку с ФИО на имя и фамилию для Django
                    name_parts = payload["customer_name"].strip().split(" ", 1)
                    first_name = name_parts[0]
                    last_name = name_parts[1] if len(name_parts) > 1 else "-"

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
                                f"Ошибка создания клиента: HTTP {create_resp.status_code} - {create_resp.text}")

                    # --- ЭТАП 2: ДОКУМЕНТ SALE В DJANGO ---
                    created_sale_id = None
                    is_new_sale = False  # Флаг для защиты от спама дублями в Telegram

                    # 1. Идемпотентность: проверяем, нет ли уже такого заказа
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

                    # 2. Создаем заказ, если его еще нет
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
                            raise ValueError(f"Ошибка создания Sale: HTTP {sale_resp.status_code} - {sale_resp.text}")

                        created_sale_id = sale_resp.json().get("id")
                        is_new_sale = True

                    # --- ЭТАП 3: ОТПРАВКА В TELEGRAM ---
                    if is_new_sale:
                        total_sum = 0
                        items_text = ""
                        for item in payload["items"]:
                            item_total = float(item["price"]) * item["quantity"]
                            total_sum += item_total

                            # Если имя сохранено в OutboxEvent на этапе чекаута - используем его
                            product_name = item.get("name", f"Товар ID {item['product_id']}")

                            # Если имени нет, запрашиваем (Fallback)
                            if "name" not in item:
                                try:
                                    prod_resp = await client.get(
                                        f"{settings.WAREHOUSE_URL}/api/products/{item['product_id']}/")
                                    if prod_resp.status_code == 200:
                                        product_name = prod_resp.json().get("name", product_name)
                                except Exception as e:
                                    print(f"Сетевая ошибка при получении имени товара: {e}")

                            items_text += f"• {product_name} — {item['quantity']} шт. ({item_total} руб.)\n"

                        order_url = f"{settings.WAREHOUSE_URL}/inventory/sale/{created_sale_id}/"
                        tg_msg = (
                            f"🚨 <b>НОВЫЙ ЗАКАЗ #{local_order_id}</b>\n\n"
                            f"👤 <b>Клиент:</b> {payload['customer_name']}\n"
                            f"📞 <b>Телефон:</b> {phone}\n"
                            f"💳 <b>Сумма:</b> {total_sum} руб.\n\n"
                            f"📦 <b>Состав заказа:</b>\n{items_text}\n"
                            f"🔗 <a href='{order_url}'>Открыть заказ</a>"
                        )
                        await send_telegram_message(client, tg_msg)

                    # --- ЭТАП 4: УСПЕХ ---
                    event.processed = True
                    event.error_message = None
                    print(f"Заказ #{local_order_id} успешно обработан!")

                except ValueError as e:
                    # Бизнес-ошибки от API склада (например, 400 Bad Request)
                    # Помечаем обработанным, чтобы не спамить склад, и записываем лог ошибки
                    event.processed = True
                    event.error_message = str(e)
                    print(f"Бизнес-ошибка заказа #{local_order_id}: {e}")

                except Exception as e:
                    # Сетевые сбои (500, таймауты). Оставляем processed=False для следующего круга
                    event.error_message = f"Требует повтора: {str(e)}"
                    print(f"Сетевая ошибка заказа #{local_order_id}: {e}")

                # ИНДИВИДУАЛЬНЫЙ КОММИТ: Сохраняем статус каждого события отдельно!
                await session.commit()


async def main():
    print("Воркер запущен. Ожидание заказов...")
    while True:
        try:
            await process_outbox_events()
        except Exception as e:
            print(f"Критическая ошибка подключения к БД: {e}")

        # Пауза в 5 секунд обеспечивает быструю реакцию на новые заказы без CPU-спама
        await asyncio.sleep(5)


if __name__ == "__main__":
    asyncio.run(main())