import asyncio
import os

import httpx
from sqlalchemy.future import select

from core.config import settings
from db.postgres import AsyncSessionLocal
from models.outbox import OutboxEvent



async def send_telegram_message(client: httpx.AsyncClient, text: str):
    """Функция отправки сообщения в Telegram"""
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
        stmt = select(OutboxEvent).where(OutboxEvent.processed == False).order_by(OutboxEvent.created_at)
        result = await session.execute(stmt)
        events = result.scalars().all()

        if not events:
            return

        print(f"Найдено необработанных заказов: {len(events)}")

        async with httpx.AsyncClient() as client:
            for event in events:
                payload = event.payload
                try:
                    # Подготавливаем безопасные данные для Django
                    phone = payload["customer_phone"]
                    safe_phone = phone if phone.startswith("+") else f"+{phone}"

                    # Если клиент ввел только имя, фамилия будет "-",
                    # чтобы не вызывать ошибку пустого поля в Django.
                    name_parts = payload["customer_name"].strip().split(" ", 1)
                    first_name = name_parts[0]
                    last_name = name_parts[1] if len(name_parts) > 1 else "-"

                    # --- ЭТАП 1: КЛИЕНТ ---
                    customers_resp = await client.get(
                        f"{settings.WAREHOUSE_URL}/api/customers/",
                        params={"phone": safe_phone}
                    )
                    customer_id = None
                    if customers_resp.status_code == 200:
                        res = customers_resp.json()
                        res_list = res.get("results", res) if isinstance(res, dict) else res
                        if res_list: customer_id = res_list[0]["id"]

                    if not customer_id:
                        new_customer = {
                            "first_name": first_name,
                            "last_name": last_name,
                            "phone": safe_phone
                        }

                        create_resp = await client.post(
                            f"{settings.WAREHOUSE_URL}/api/customers/",
                            json=new_customer
                        )

                        if create_resp.status_code in (200, 201):
                            customer_id = create_resp.json()["id"]
                        else:
                            # Если Django снова ответит 400, мы точно увидим причину в консоли
                            raise Exception(
                                f"Ошибка валидации клиента в Django: "
                                f"HTTP {create_resp.status_code}: {create_resp.text}"
                            )

                    # --- ЭТАП 2: ДОКУМЕНТ SALE В DJANGO ---
                    local_order_id = str(payload.get('local_order_id', ''))
                    created_sale_id = None

                    # 1. ПРОВЕРЯЕМ, НЕТ ЛИ УЖЕ ТАКОГО ЗАКАЗА В DJANGO (ИДЕМПОТЕНТНОСТЬ)
                    if local_order_id:
                        check_resp = await client.get(
                            f"{settings.WAREHOUSEI_URL}/api/sales/",
                            params={"external_id": local_order_id}
                        )
                        if check_resp.status_code == 200:
                            res = check_resp.json()
                            res_list = res.get("results", res) if isinstance(res, dict) else res
                            if res_list:
                                created_sale_id = res_list[0]["id"]
                                print(
                                    f"⚠️ Заказ #{local_order_id} уже есть в Django (ID {created_sale_id}). Пропускаем создание дубля.")

                    # 2. ЕСЛИ ЗАКАЗА НЕТ - СОЗДАЕМ
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
                            raise Exception(f"Ошибка создания Sale: {sale_resp.text}")

                        created_sale_id = sale_resp.json().get("id")

                    # --- ЭТАП 3: ОТПРАВКА В TELEGRAM ---
                    # Считаем общую сумму и красиво форматируем список товаров
                    total_sum = 0
                    items_text = ""
                    for item in payload["items"]:
                        item_total = float(item["price"]) * item["quantity"]
                        total_sum += item_total
                        # Спрашиваем название товара у Django по его ID
                        product_name = f"Товар ID {item['product_id']}"
                        try:
                            prod_resp = await client.get(f"{settings.WAREHOUSE_URL}/api/products/{item['product_id']}/")
                            if prod_resp.status_code == 200:
                                product_name = prod_resp.json().get("name", product_name)
                            else:
                                print(f"Ошибка товара: Код {prod_resp.status_code}, Ответ: {prod_resp.text}")
                        except Exception as e:
                            print(f"СЕТЕВАЯ ОШИБКА ТОВАРА: {e}")

                        items_text += f"• {product_name} — {item['quantity']} шт. ({item_total} руб.)\n"

                        order_url = f"{settings.WAREHOUSE_URL}/sale/{created_sale_id}/"

                        tg_msg = (
                            f"🚨 <b>НОВЫЙ ЗАКАЗ #{payload.get('local_order_id')}</b>\n\n"
                            f"👤 <b>Клиент:</b> {payload['customer_name']}\n"
                            f"📞 <b>Телефон:</b> {safe_phone}\n"
                            f"💳 <b>Сумма:</b> {total_sum} руб.\n\n"
                            f"📦 <b>Состав заказа:</b>\n{items_text}\n"
                            f"🔗 <a href='{order_url}'>Открыть заказ в панели управления</a>"
                        )
                    await send_telegram_message(client, tg_msg)

                    # --- ЭТАП 4: УСПЕХ! ---
                    event.processed = True
                    event.error_message = None
                    print(f"Заказ #{payload.get('local_order_id')} обработан и отправлен в ТГ!")

                except Exception as e:
                    event.error_message = str(e)
                    print(f"Ошибка отправки заказа: {str(e)}")

        await session.commit()


async def main():
    print("Воркер запущен. Ожидание заказов...")
    while True:
        try:
            await process_outbox_events()
        except Exception as e:
            print(f"Критическая ошибка базы: {e}")
        await asyncio.sleep(60)


if __name__ == "__main__":
    asyncio.run(main())