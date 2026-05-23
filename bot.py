import logging
import os
from datetime import datetime
from typing import Optional

from dotenv import load_dotenv
from telegram import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
    Update,
)
from telegram.ext import (
    Application,
    CallbackQueryHandler,
    CommandHandler,
    ConversationHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

from database import Database
from exercises import WORKOUTS, get_weighted_exercises

load_dotenv()

logging.basicConfig(
    format="%(asctime)s | %(levelname)s | %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

TOKEN = os.getenv("BOT_TOKEN")
db = Database()

# ── Состояния ConversationHandler ──────────────────────────────────────────
DAY_SELECTION, EXERCISE_ACTIVE, WEIGHT_EDITING = range(3)


# ══════════════════════════════════════════════════════════════════════════════
#  ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ══════════════════════════════════════════════════════════════════════════════

def exercise_caption(exercise: dict, set_idx: int, weight: Optional[float], ex_pos: int, ex_total: int) -> str:
    sets_total = len(exercise["sets"])
    reps = exercise["sets"][set_idx]["reps"]
    weight_str = f"{weight} {exercise['weight_unit']}" if exercise["weight_unit"] else "без веса"

    done_dots   = "🟢" * set_idx
    active_dot  = "🔵"
    future_dots = "⚪" * (sets_total - set_idx - 1)
    progress_bar = done_dots + active_dot + future_dots

    return (
        f"📊 Упражнение *{ex_pos}/{ex_total}*\n\n"
        f"🏋️ *{exercise['name']}*\n"
        f"{progress_bar}\n\n"
        f"Подход: *{set_idx + 1} из {sets_total}*\n"
        f"Повторений: *{reps}*\n"
        f"Вес: *{weight_str}*\n\n"
        f"{exercise['tip']}"
    )


def exercise_keyboard(has_weight: bool) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton("✅  Подход выполнен", callback_data="set_done")],
    ]
    if has_weight:
        rows.append([InlineKeyboardButton("⚖️  Изменить вес", callback_data="change_weight")])
    rows.append([InlineKeyboardButton("⏭️  Пропустить упражнение", callback_data="skip_exercise")])
    rows.append([InlineKeyboardButton("🚫  Завершить тренировку", callback_data="finish_workout")])
    return InlineKeyboardMarkup(rows)


def current_exercise(context: ContextTypes.DEFAULT_TYPE) -> dict:
    day_num = context.user_data["day_num"]
    ex_idx  = context.user_data["exercise_idx"]
    return WORKOUTS[day_num]["exercises"][ex_idx]


def current_weight(context: ContextTypes.DEFAULT_TYPE) -> Optional[float]:
    ex = current_exercise(context)
    return context.user_data["weights"].get(ex["id"])


# ══════════════════════════════════════════════════════════════════════════════
#  ПОКАЗ УПРАЖНЕНИЯ
# ══════════════════════════════════════════════════════════════════════════════

async def show_exercise(message: Message, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Отправить GIF + подпись с кнопками для текущего упражнения."""
    day_num   = context.user_data["day_num"]
    ex_idx    = context.user_data["exercise_idx"]
    set_idx   = context.user_data["set_idx"]
    exercises = WORKOUTS[day_num]["exercises"]

    if ex_idx >= len(exercises):
        await finish_summary(message, context)
        return

    ex     = exercises[ex_idx]
    weight = current_weight(context)
    total  = len(exercises)
    text   = exercise_caption(ex, set_idx, weight, ex_idx + 1, total)
    kb     = exercise_keyboard(has_weight=bool(ex["weight_unit"]))

    if set_idx == 0 and ex.get("photo"):
        # Новое упражнение — отправляем фото с техникой
        try:
            with open(ex["photo"], "rb") as photo_file:
                await message.reply_photo(
                    photo=photo_file,
                    caption=text,
                    reply_markup=kb,
                    parse_mode="Markdown",
                )
        except Exception:
            await message.reply_text(text, reply_markup=kb, parse_mode="Markdown")
    else:
        # Следующий подход того же упражнения — только текст
        await message.reply_text(text, reply_markup=kb, parse_mode="Markdown")


# ══════════════════════════════════════════════════════════════════════════════
#  /start
# ══════════════════════════════════════════════════════════════════════════════

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    text = (
        "👋 *Привет! Я твой тренировочный бот.*\n\n"
        "Веду тебя по каждому упражнению, записываю веса и считаю прогресс.\n\n"
        "📋 *Команды:*\n"
        "/workout — начать тренировку\n"
        "/today — программа следующей тренировки\n"
        "/history — история тренировок\n"
        "/progress — прогресс по весам\n"
        "/stats — общая статистика\n"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


# ══════════════════════════════════════════════════════════════════════════════
#  СТАРТ ТРЕНИРОВКИ
# ══════════════════════════════════════════════════════════════════════════════

async def cmd_workout(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    keyboard = []
    for day_num, day_data in WORKOUTS.items():
        keyboard.append([
            InlineKeyboardButton(
                f"{day_data['emoji']}  {day_data['name']}",
                callback_data=f"day_{day_num}",
            )
        ])
    keyboard.append([InlineKeyboardButton("❌  Отмена", callback_data="cancel")])

    await update.message.reply_text(
        "💪 *Выбери тренировку:*",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown",
    )
    return DAY_SELECTION


async def cb_day_selected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    if query.data == "cancel":
        await query.edit_message_text("Отменено. Напиши /workout когда будешь готов 💪")
        return ConversationHandler.END

    day_num  = int(query.data.split("_")[1])
    day_data = WORKOUTS[day_num]

    workout_id = await db.create_workout(query.from_user.id, day_num)
    context.user_data.update({
        "workout_id":   workout_id,
        "day_num":      day_num,
        "exercise_idx": 0,
        "set_idx":      0,
        "weights": {ex["id"]: ex["default_weight"] for ex in day_data["exercises"]},
    })

    await query.edit_message_text(
        f"🚀 *{day_data['name']}*\n\nПоехали! {day_data['emoji']}",
        parse_mode="Markdown",
    )
    await show_exercise(query.message, context)
    return EXERCISE_ACTIVE


# ══════════════════════════════════════════════════════════════════════════════
#  ЛОГИКА ТРЕНИРОВКИ
# ══════════════════════════════════════════════════════════════════════════════

async def rest_timer_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    """Срабатывает после окончания отдыха — шлёт уведомление."""
    job  = context.job
    chat_id   = job.data["chat_id"]
    mode      = job.data["mode"]       # "next_set" или "next_exercise"
    rest_msg_id = job.data.get("rest_msg_id")
    user_data = job.data["user_data"]

    # Убираем кнопку у сообщения об отдыхе
    if rest_msg_id:
        try:
            await context.bot.edit_message_reply_markup(
                chat_id=chat_id, message_id=rest_msg_id, reply_markup=None
            )
        except Exception:
            pass

    if mode == "next_set":
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("▶️  Следующий подход", callback_data="continue_set")
        ]])
        await context.bot.send_message(
            chat_id=chat_id,
            text="⏰ *Время! Отдых закончен — следующий подход!* 💪",
            reply_markup=kb,
            parse_mode="Markdown",
        )
    else:
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("➡️  Следующее упражнение", callback_data="next_exercise")
        ]])
        next_name = user_data.get("next_exercise_name", "")
        await context.bot.send_message(
            chat_id=chat_id,
            text=f"⏰ *Время! Отдых закончен.*\n\nСледующее: *{next_name}* 💪",
            reply_markup=kb,
            parse_mode="Markdown",
        )


def cancel_rest_job(context: ContextTypes.DEFAULT_TYPE, chat_id: int) -> None:
    """Отменяет активный таймер отдыха если пользователь нажал кнопку сам."""
    job_name = f"rest_{chat_id}"
    for job in context.job_queue.get_jobs_by_name(job_name):
        job.schedule_removal()


async def cb_set_done(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer("✅ Подход записан!")

    day_num    = context.user_data["day_num"]
    ex_idx     = context.user_data["exercise_idx"]
    set_idx    = context.user_data["set_idx"]
    workout_id = context.user_data["workout_id"]
    exercises  = WORKOUTS[day_num]["exercises"]
    ex         = exercises[ex_idx]
    weight     = current_weight(context)
    chat_id    = query.message.chat_id

    # Отменяем предыдущий таймер если был
    cancel_rest_job(context, chat_id)

    # Сохраняем подход в БД
    await db.log_set(
        workout_id    = workout_id,
        exercise_id   = ex["id"],
        exercise_name = ex["name"],
        set_num       = set_idx + 1,
        reps_target   = ex["sets"][set_idx]["reps"],
        weight        = weight,
    )

    sets_total = len(ex["sets"])

    if set_idx + 1 < sets_total:
        # Следующий подход — запускаем таймер отдыха
        context.user_data["set_idx"] = set_idx + 1
        rest = ex["rest_seconds"]

        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("▶️  Не ждать — следующий подход", callback_data="continue_set")
        ]])
        rest_msg = await query.message.reply_text(
            f"⏱ *Отдых {rest} сек...*\n\nПодход {set_idx + 1}/{sets_total} выполнен 💪\n"
            f"Следующий: *{ex['sets'][set_idx + 1]['reps']}* повт.\n\n"
            f"_Бот напомнит когда время выйдет_",
            reply_markup=kb,
            parse_mode="Markdown",
        )
        context.job_queue.run_once(
            rest_timer_job,
            when=rest,
            name=f"rest_{chat_id}",
            data={
                "chat_id":      chat_id,
                "mode":         "next_set",
                "rest_msg_id":  rest_msg.message_id,
                "user_data":    {},
            },
        )
    else:
        # Упражнение завершено — переходим к следующему
        context.user_data["exercise_idx"] = ex_idx + 1
        context.user_data["set_idx"]      = 0
        next_idx = ex_idx + 1

        if next_idx < len(exercises):
            next_ex = exercises[next_idx]
            rest    = ex["rest_seconds"]

            kb = InlineKeyboardMarkup([[
                InlineKeyboardButton("➡️  Не ждать — следующее упражнение", callback_data="next_exercise")
            ]])
            rest_msg = await query.message.reply_text(
                f"✅ *{ex['name']}* — выполнено!\n\n"
                f"Следующее: *{next_ex['name']}*\n"
                f"⏱ Отдых *{rest} сек*...\n\n"
                f"_Бот напомнит когда время выйдет_",
                reply_markup=kb,
                parse_mode="Markdown",
            )
            context.job_queue.run_once(
                rest_timer_job,
                when=rest,
                name=f"rest_{chat_id}",
                data={
                    "chat_id":            chat_id,
                    "mode":               "next_exercise",
                    "rest_msg_id":        rest_msg.message_id,
                    "user_data":          {"next_exercise_name": next_ex["name"]},
                },
            )
        else:
            await finish_summary(query.message, context)
            return ConversationHandler.END

    return EXERCISE_ACTIVE


async def cb_continue_set(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    cancel_rest_job(context, query.message.chat_id)
    await query.edit_message_reply_markup(None)
    await show_exercise(query.message, context)
    return EXERCISE_ACTIVE


async def cb_next_exercise(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    cancel_rest_job(context, query.message.chat_id)
    await query.edit_message_reply_markup(None)
    await show_exercise(query.message, context)
    return EXERCISE_ACTIVE


async def cb_skip_exercise(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer("⏭️ Пропущено")

    day_num   = context.user_data["day_num"]
    exercises = WORKOUTS[day_num]["exercises"]

    context.user_data["exercise_idx"] += 1
    context.user_data["set_idx"]       = 0

    if context.user_data["exercise_idx"] >= len(exercises):
        await finish_summary(query.message, context)
        return ConversationHandler.END

    await show_exercise(query.message, context)
    return EXERCISE_ACTIVE


async def cb_change_weight(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()

    ex     = current_exercise(context)
    weight = current_weight(context)

    await query.message.reply_text(
        f"⚖️ Текущий вес: *{weight} {ex['weight_unit']}*\n\nВведи новый вес (например: 67.5):",
        parse_mode="Markdown",
    )
    return WEIGHT_EDITING


async def receive_new_weight(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    try:
        new_weight = float(update.message.text.replace(",", "."))
        if new_weight <= 0:
            raise ValueError
    except ValueError:
        await update.message.reply_text("❌ Введи положительное число, например: 67.5")
        return WEIGHT_EDITING

    ex = current_exercise(context)
    context.user_data["weights"][ex["id"]] = new_weight

    await update.message.reply_text(
        f"✅ Вес обновлён: *{new_weight} {ex['weight_unit']}*",
        parse_mode="Markdown",
    )
    await show_exercise(update.message, context)
    return EXERCISE_ACTIVE


async def cb_finish_workout(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    await finish_summary(query.message, context)
    return ConversationHandler.END


async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Тренировка отменена. Напиши /workout когда будешь готов 💪")
    context.user_data.clear()
    return ConversationHandler.END


# ══════════════════════════════════════════════════════════════════════════════
#  ИТОГ ТРЕНИРОВКИ
# ══════════════════════════════════════════════════════════════════════════════

async def finish_summary(message: Message, context: ContextTypes.DEFAULT_TYPE) -> None:
    workout_id = context.user_data.get("workout_id")
    day_num    = context.user_data.get("day_num")

    if workout_id:
        await db.complete_workout(workout_id)

    day_data = WORKOUTS.get(day_num, {})
    now      = datetime.now().strftime("%d.%m.%Y  %H:%M")

    await message.reply_text(
        f"🎉 *Тренировка завершена!*\n\n"
        f"📅 {now}\n"
        f"💪 {day_data.get('name', '')}\n\n"
        f"Отличная работа! Восстанавливайся и возвращайся сильнее 🔥",
        parse_mode="Markdown",
    )
    context.user_data.clear()


# ══════════════════════════════════════════════════════════════════════════════
#  /today — следующая тренировка
# ══════════════════════════════════════════════════════════════════════════════

async def cmd_today(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id  = update.effective_user.id
    last_day = await db.get_last_day(user_id)
    next_day = (last_day % 3) + 1 if last_day else 1

    day_data = WORKOUTS[next_day]
    text = f"📋 *Следующая: {day_data['name']}*\n\n"

    for i, ex in enumerate(day_data["exercises"], 1):
        weight_str = f"{ex['default_weight']} {ex['weight_unit']}" if ex["weight_unit"] else "без веса"
        sets_n     = len(ex["sets"])
        reps_first = ex["sets"][0]["reps"]
        text += f"{i}. *{ex['name']}* — {sets_n}×{reps_first} повт., {weight_str}\n"

    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton(f"💪  Начать прямо сейчас", callback_data=f"quick_{next_day}")
    ]])
    await update.message.reply_text(text, reply_markup=kb, parse_mode="Markdown")


async def cb_quick_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query    = update.callback_query
    await query.answer()
    day_num  = int(query.data.split("_")[1])
    day_data = WORKOUTS[day_num]

    workout_id = await db.create_workout(query.from_user.id, day_num)
    context.user_data.update({
        "workout_id":   workout_id,
        "day_num":      day_num,
        "exercise_idx": 0,
        "set_idx":      0,
        "weights": {ex["id"]: ex["default_weight"] for ex in day_data["exercises"]},
    })

    await query.edit_message_text(
        f"🚀 *{day_data['name']}*\n\nПоехали! {day_data['emoji']}",
        parse_mode="Markdown",
    )
    await show_exercise(query.message, context)
    return EXERCISE_ACTIVE


# ══════════════════════════════════════════════════════════════════════════════
#  /history
# ══════════════════════════════════════════════════════════════════════════════

async def cmd_history(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id  = update.effective_user.id
    workouts = await db.get_history(user_id, limit=7)

    if not workouts:
        await update.message.reply_text(
            "📋 История пуста. Начни первую тренировку: /workout"
        )
        return

    text = "📋 *История тренировок:*\n\n"
    for w in workouts:
        name     = WORKOUTS.get(w["day_num"], {}).get("name", f"День {w['day_num']}")
        date_str = datetime.fromisoformat(w["started_at"]).strftime("%d.%m.%Y")
        icon     = "✅" if w["completed"] else "⚠️"
        text += f"{icon} {date_str}  —  {name}\n"

    await update.message.reply_text(text, parse_mode="Markdown")


# ══════════════════════════════════════════════════════════════════════════════
#  /progress
# ══════════════════════════════════════════════════════════════════════════════

async def cmd_progress(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    weighted = get_weighted_exercises()
    keyboard = [
        [InlineKeyboardButton(ex["name"], callback_data=f"prog_{ex['id']}")]
        for ex in weighted
    ]
    await update.message.reply_text(
        "📈 *Прогресс по упражнению:*\nВыбери:",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown",
    )


async def cb_show_progress(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    query       = update.callback_query
    await query.answer()
    exercise_id = query.data.replace("prog_", "")
    user_id     = query.from_user.id
    logs        = await db.get_exercise_progress(user_id, exercise_id)

    # Найти название
    ex_name = exercise_id
    for day_data in WORKOUTS.values():
        for ex in day_data["exercises"]:
            if ex["id"] == exercise_id:
                ex_name = ex["name"]

    if not logs:
        await query.edit_message_text(f"По упражнению *{ex_name}* данных ещё нет.", parse_mode="Markdown")
        return

    text = f"📈 *{ex_name}*\n\n"
    for log in reversed(logs):  # от старых к новым
        date_str = datetime.fromisoformat(log["date"]).strftime("%d.%m.%Y")
        text += f"📅 {date_str}:  *{log['max_weight']} кг*\n"

    # Тренд
    if len(logs) >= 2:
        diff = logs[0]["max_weight"] - logs[-1]["max_weight"]
        if diff > 0:
            text += f"\n📉 За этот период −{abs(diff)} кг (показан последний)"
        elif diff < 0:
            text += f"\n📈 За этот период +{abs(diff)} кг 🔥"
        else:
            text += "\n➡️ Вес стабильный"

    await query.edit_message_text(text, parse_mode="Markdown")


# ══════════════════════════════════════════════════════════════════════════════
#  /stats
# ══════════════════════════════════════════════════════════════════════════════

async def cmd_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id        = update.effective_user.id
    total_workouts = await db.get_workout_count(user_id)
    total_sets     = await db.get_total_sets(user_id)
    last_day       = await db.get_last_day(user_id)
    next_day       = (last_day % 3) + 1 if last_day else 1
    next_name      = WORKOUTS[next_day]["name"]

    text = (
        f"📊 *Твоя статистика:*\n\n"
        f"🏋️ Тренировок завершено: *{total_workouts}*\n"
        f"✅ Всего подходов записано: *{total_sets}*\n\n"
        f"⏭️ Следующая: *{next_name}*\n\n"
        f"Продолжай в том же духе! 💪"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════════════════════════════

async def post_init(application: Application) -> None:
    await db.init()
    logger.info("Database initialised.")


def main():
    if not TOKEN:
        raise RuntimeError("BOT_TOKEN не задан в .env!")

    app = Application.builder().token(TOKEN).post_init(post_init).build()

    # ConversationHandler для тренировки
    conv = ConversationHandler(
        entry_points=[
            CommandHandler("workout", cmd_workout),
            CallbackQueryHandler(cb_quick_start, pattern=r"^quick_\d+$"),
        ],
        states={
            DAY_SELECTION: [
                CallbackQueryHandler(cb_day_selected, pattern=r"^(day_\d+|cancel)$"),
            ],
            EXERCISE_ACTIVE: [
                CallbackQueryHandler(cb_set_done,       pattern="^set_done$"),
                CallbackQueryHandler(cb_continue_set,   pattern="^continue_set$"),
                CallbackQueryHandler(cb_next_exercise,  pattern="^next_exercise$"),
                CallbackQueryHandler(cb_skip_exercise,  pattern="^skip_exercise$"),
                CallbackQueryHandler(cb_change_weight,  pattern="^change_weight$"),
                CallbackQueryHandler(cb_finish_workout, pattern="^finish_workout$"),
            ],
            WEIGHT_EDITING: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, receive_new_weight),
            ],
        },
        fallbacks=[CommandHandler("cancel", cmd_cancel)],
        per_user=True,
        per_chat=True,
    )

    app.add_handler(conv)
    app.add_handler(CommandHandler("start",    cmd_start))
    app.add_handler(CommandHandler("today",    cmd_today))
    app.add_handler(CommandHandler("history",  cmd_history))
    app.add_handler(CommandHandler("progress", cmd_progress))
    app.add_handler(CommandHandler("stats",    cmd_stats))
    app.add_handler(CallbackQueryHandler(cb_show_progress, pattern=r"^prog_"))

    logger.info("Bot polling started.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
