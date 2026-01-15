FROM python:3.11-slim

WORKDIR /app

COPY mafia_bot/requirements.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY mafia_bot/ .

CMD ["python", "bot.py"]
