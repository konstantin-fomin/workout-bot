# 🏋️ Workout Telegram Bot

## Быстрый старт

### 1. Получи токен
Напиши @BotFather в Telegram → /newbot → скопируй токен.

### 2. Создай .env
```bash
cp .env.example .env
nano .env   # вставь свой BOT_TOKEN
```

### 3. Запусти
```bash
docker compose up -d --build
```

### 4. Проверь логи
```bash
docker compose logs -f
```

---

## Команды бота

| Команда | Описание |
|---|---|
| /start | Приветствие и список команд |
| /workout | Начать тренировку (выбор дня) |
| /today | Показать следующую тренировку |
| /history | История последних 7 тренировок |
| /progress | Прогресс по весам в упражнениях |
| /stats | Общая статистика |
| /cancel | Прервать текущую тренировку |

---

## Обновить упражнения или веса

Редактируй `exercises.py` — там все три дня, веса, подходы, советы и GIF-ссылки.

После изменений:
```bash
docker compose up -d --build
```

## Остановить / перезапустить
```bash
docker compose stop
docker compose restart
```
