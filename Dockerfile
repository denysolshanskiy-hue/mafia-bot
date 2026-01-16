FROM python:3.11-slim

WORKDIR /app

# Копіюємо все, що є в репозиторії, у робочу папку /app
COPY . .

# Оновлюємо сертифікати
RUN apt-get update && apt-get install -y ca-certificates && update-ca-certificates

# Встановлюємо залежності (використовуємо знайти файл, якщо він глибоко)
RUN pip install --no-cache-dir aiogram aiohttp

# Запуск бота (вказуємо шлях до bot.py)
# Якщо ваш bot.py лежить всередині папки mafia_bot, замініть на: 
# CMD ["python", "mafia_bot/bot.py"]
CMD ["python", "mafia_bot/bot.py"]

