FROM python:3.11-slim

WORKDIR /app

# Встановлюємо системні залежності
RUN apt-get update && apt-get install -y \
    ca-certificates \
    && update-ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Копіюємо файл залежностей
COPY requirements.txt .

# Встановлюємо всі залежності з файлу (включаючи asyncpg)
RUN pip install --no-cache-dir -r requirements.txt

# Копіюємо решту коду
COPY . .

# Запуск бота
CMD ["python", "mafia_bot/bot.py"]
