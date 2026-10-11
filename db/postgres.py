from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from core.config import settings

# Настраиваем асинхронный движок с учетом высоких нагрузок
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,           # Включите True для дебага SQL-запросов в консоли
    pool_size=20,         # Базовое количество одновременных соединений
    max_overflow=10,      # Дополнительные соединения при пиковой нагрузке
)

# Фабрика сессий
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    expire_on_commit=False,
    autoflush=False,
    autocommit=False
)

# Dependency для внедрения сессии в эндпоинты
async def get_db_session():
    async with AsyncSessionLocal() as session:
        yield session