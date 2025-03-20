import os
import django
from asgiref.sync import sync_to_async

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Saypress.settings')
django.setup()

import logging
from aiogram import Bot, Dispatcher, types, executor
from aiogram.types import (
    ReplyKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardRemove,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    InlineQueryResultArticle,
    InputTextMessageContent
)

from main.models import Category, Question, UserQuestion, TeleUser, Company, TimeOff
from datetime import datetime
import calendar
from datetime import date

logging.basicConfig(level=logging.INFO)

TOKEN = "7943795810:AAG0wun2bnwieW2K8Aefv9XHSXx2lFIJV8Y"
bot = Bot(token=TOKEN, parse_mode=types.ParseMode.HTML)
dp = Dispatcher(bot)

# ---------------------------
#  States
# ---------------------------
STATE_NONE = "NONE"
STATE_AWAITING_QUESTION = "AWAITING_QUESTION"
STATE_CONFIRM_PENDING = "CONFIRM_PENDING"

# Registration states
STATE_REG_NAME = "REG_NAME"
STATE_REG_NICKNAME = "REG_NICKNAME"
STATE_REG_TRUCK = "REG_TRUCK"
STATE_REG_COMPANY = "REG_COMPANY"  # New step: user chooses company

# Inline-edit state
STATE_INLINE_EDIT = "INLINE_EDIT"

# TimeOff states
STATE_TIMEOFF_FROM = "TIMEOFF_FROM"
STATE_TIMEOFF_TILL = "TIMEOFF_TILL"
STATE_TIMEOFF_REASON = "TIMEOFF_REASON"
STATE_TIMEOFF_PAUSE = "TIMEOFF_PAUSE"

# ---------------------------
#  Global dictionaries
# ---------------------------
user_selected_category = {}  # { user_id: category_name }
user_state = {}              # { user_id: state_name }
pending_question = {}        # { user_id: {"category":..., "question":...} }
temp_user_data = {}          # { user_id: {...} }

# ---------------------------
#  Django ORM Async wrappers
# ---------------------------
@sync_to_async
def get_teleuser_by_id(telegram_id):
    return TeleUser.objects.filter(telegram_id=telegram_id).first()

@sync_to_async
def create_teleuser(telegram_id, name, nickname, truck_number, company_id=None):
    company_obj = None
    if company_id:
        company_obj = Company.objects.get(id=company_id)
    # В модели TeleUser предположим, что у вас есть поле first_name (или name), nickname, truck_number, company
    return TeleUser.objects.create(
        telegram_id=telegram_id,
        first_name=name,         # Используем поле first_name как "Name"
        nickname=nickname,
        truck_number=truck_number,
        company=company_obj
    )

@sync_to_async
def get_companies():
    return list(Company.objects.all())

@sync_to_async
def create_timeoff(teleuser_id, date_from, date_till, reason, pause):
    user = TeleUser.objects.get(id=teleuser_id)
    return TimeOff.objects.create(
        teleuser=user,
        date_from=date_from,
        date_till=date_till,
        reason=reason,
        pause_insurance=pause
    )

@sync_to_async
def get_categories_async():
    return list(Category.objects.all())

@sync_to_async
def get_questions_for_category_async(category_name: str):
    try:
        cat = Category.objects.get(name=category_name)
    except Category.DoesNotExist:
        return []
    return list(Question.objects.filter(category=cat))

@sync_to_async
def save_user_question_async(user_id, username, category_name, question_text, responsible_id=None):
    try:
        cat = Category.objects.get(name=category_name)
    except Category.DoesNotExist:
        cat = None
    UserQuestion.objects.create(
        user_id=user_id,
        username=username,
        category=cat,
        question=question_text,
        responsible_id=responsible_id
    )


# ---------------------------
#  Group messages handler
# ---------------------------
@dp.message_handler(lambda message: message.chat.type in ["group", "supergroup"])
async def group_redirect(message: types.Message):
    text = message.text or ""
    if "@sayram_help_bot" in text:
        inline_kb = InlineKeyboardMarkup()
        bot_link = "https://t.me/sayram_help_bot"
        inline_kb.add(types.InlineKeyboardButton("Go to the bot's private messages", url=bot_link))
        await message.reply("To ask a question, please go to the bot's private messages:", reply_markup=inline_kb)


# ---------------------------
#  Inline Mode handler
# ---------------------------
@dp.inline_handler()
async def inline_query_echo(inline_query: types.InlineQuery):
    text = inline_query.query or "Empty question"
    result = InlineQueryResultArticle(
        id="1",
        title="Send this text",
        description=(text[:50] + "...") if len(text) > 50 else text,
        input_message_content=InputTextMessageContent(text)
    )
    await inline_query.answer([result], cache_time=1, is_personal=True)


# ---------------------------
#  /start, /help
# ---------------------------
@dp.message_handler(commands=['start', 'help'])
async def cmd_start(message: types.Message):
    user_id = message.from_user.id
    user_selected_category[user_id] = None
    user_state[user_id] = STATE_NONE

    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    existing_user = await get_teleuser_by_id(user_id)
    if not existing_user:
        kb.add("📋 Register")
    # Кнопка Time Off
    kb.add("Time Off")

    categories = await get_categories_async()
    for cat in categories:
        kb.add(cat.name)

    await message.answer(
        "Hello! Select category, press 'Time Off' or 'Register':",
        reply_markup=kb
    )

def generate_calendar(year, month, min_date=None):
    kb = InlineKeyboardMarkup(row_width=7)

    # 1) Строка с навигацией (название месяца + кнопки < >)
    row = []
    row.append(InlineKeyboardButton("<", callback_data=f"CALENDAR:{year}:{month}:PREV"))
    row.append(InlineKeyboardButton(f"{calendar.month_name[month]} {year}", callback_data="IGNORE"))
    row.append(InlineKeyboardButton(">", callback_data=f"CALENDAR:{year}:{month}:NEXT"))
    kb.row(*row)

    # 2) Заголовок дней недели
    week_days = ["Mo","Tu","We","Th","Fr","Sa","Su"]
    row = [InlineKeyboardButton(day, callback_data="IGNORE") for day in week_days]
    kb.row(*row)

    # 3) Перебираем дни месяца
    cal = calendar.Calendar(firstweekday=0)
    month_days = cal.itermonthdates(year, month)

    temp_row = []
    for d in month_days:
        if d.month != month:
            # Дни не из этого месяца - пустые
            btn = InlineKeyboardButton(" ", callback_data="IGNORE")
        else:
            # Проверяем min_date (если есть)
            if min_date and d < min_date:
                # Дата до min_date => неактивна
                btn = InlineKeyboardButton(str(d.day), callback_data="IGNORE")
            else:
                # Можно выбрать
                btn = InlineKeyboardButton(str(d.day),
                                           callback_data=f"CALENDAR:{d.year}:{d.month}:{d.day}:DAY")
        temp_row.append(btn)
        if len(temp_row) == 7:
            kb.row(*temp_row)
            temp_row = []
    if temp_row:
        kb.row(*temp_row)

    return kb




@dp.callback_query_handler(lambda c: c.data.startswith("CALENDAR"))
async def process_calendar_callback(callback_query: types.CallbackQuery):
    data = callback_query.data.split(":")
    # data = ["CALENDAR", "2023", "5", "NEXT"] ИЛИ ["CALENDAR", "2023", "5", "15", "DAY"]
    year = int(data[1])
    month = int(data[2])
    action = data[-1]  # "PREV", "NEXT" или "DAY"

    user_id = callback_query.from_user.id
    # ВАЖНО: инициализируем temp_user_data, если не было
    if user_id not in temp_user_data:
        temp_user_data[user_id] = {}

    if action == "PREV":
        month -= 1
        if month < 1:
            month = 12
            year -= 1
        kb = generate_calendar(year, month)
        await callback_query.message.edit_text("Select date:", reply_markup=kb)
        await callback_query.answer()

    elif action == "NEXT":
        month += 1
        if month > 12:
            month = 1
            year += 1
        kb = generate_calendar(year, month)
        await callback_query.message.edit_text("Select date:", reply_markup=kb)
        await callback_query.answer()

    elif action == "DAY":
        day = int(data[3])
        selected_date = date(year, month, day)

        user_id = callback_query.from_user.id
        st = user_state.get(user_id)

        if st == STATE_TIMEOFF_FROM:
            # user wants FROM date
            temp_user_data[user_id]["timeoff_from"] = selected_date
            # теперь переключаемся на TILL
            user_state[user_id] = STATE_TIMEOFF_TILL
            # Покажем новый календарь, например, на тот же месяц
            min_d = selected_date
            kb = generate_calendar(selected_date.year, selected_date.month, min_date=min_d)
            await callback_query.message.edit_text(
                f"FROM date chosen: {selected_date}\nNow select TILL date:",
                reply_markup=kb
            )
            await callback_query.answer()

        elif st == STATE_TIMEOFF_TILL:
            # user выбирает TILL
            temp_user_data[user_id]["timeoff_till"] = selected_date
            user_state[user_id] = STATE_TIMEOFF_REASON

            await callback_query.message.edit_text(
                f"TILL date chosen: {selected_date}\nPlease enter reason:",
                reply_markup=None
            )
            await callback_query.answer()

        else:
            await callback_query.answer("Unexpected state!", show_alert=True)



# ---------------------------
#  Main message handler
# ---------------------------
@dp.message_handler()
async def handle_message(message: types.Message):
    text = message.text.strip()
    user_id = message.from_user.id
    current_cat = user_selected_category.get(user_id)
    current_state = user_state.get(user_id, STATE_NONE)

    # --- STATE_INLINE_EDIT ---
    if current_state == STATE_INLINE_EDIT:
        pending = pending_question.pop(user_id, None)
        if not pending:
            await message.answer("No pending question found.")
            user_state[user_id] = STATE_NONE
            return

        final_text = message.text
        category_name = pending["category"]
        await send_question_directly(user_id, category_name, final_text, message)
        user_state[user_id] = STATE_NONE
        return

    # --- STATE_CONFIRM_PENDING ---
    if current_state == STATE_CONFIRM_PENDING:
        if text == "Send":
            p = pending_question.pop(user_id, None)
            if not p:
                await message.answer("No pending question found.")
                user_state[user_id] = STATE_NONE
                return
            await send_question_directly(user_id, p["category"], p["question"], message)
            return
        elif text == "Edit":
            user_state[user_id] = STATE_INLINE_EDIT
            old_text = pending_question[user_id]["question"]
            inline_kb = InlineKeyboardMarkup()
            inline_kb.add(
                InlineKeyboardButton(
                    "Edit in inline mode",
                    switch_inline_query_current_chat=old_text
                )
            )
            await message.answer("Click below to edit your question in inline mode.", reply_markup=inline_kb)
            return
        else:
            pending_question.pop(user_id, None)
            await message.answer("Pending question canceled.")
            user_state[user_id] = STATE_NONE

            kb = ReplyKeyboardMarkup(resize_keyboard=True)
            tu = await get_teleuser_by_id(user_id)
            if not tu:
                kb.add("📋 Register")
            kb.add("Time Off")
            cats = await get_categories_async()
            for c in cats:
                kb.add(c.name)
            await message.answer("Choose category:", reply_markup=kb)
            return

    # --- Registration flow ---
    if text == "📋 Register" or text.lower() == "register":
        existing_user = await get_teleuser_by_id(user_id)
        if existing_user:
            await message.answer("You are already registered!")
            return
        else:
            user_state[user_id] = STATE_REG_NAME
            temp_user_data[user_id] = {}
            await message.answer("Enter your name:", reply_markup=ReplyKeyboardRemove())
            return

    if current_state == STATE_REG_NAME:
        temp_user_data[user_id]["name"] = text
        user_state[user_id] = STATE_REG_NICKNAME
        await message.answer("Enter your nickname:")
        return

    if current_state == STATE_REG_NICKNAME:
        temp_user_data[user_id]["nickname"] = text
        user_state[user_id] = STATE_REG_TRUCK
        await message.answer("Enter your truck number (or 'no' if none):")
        return

    if current_state == STATE_REG_TRUCK:
        temp_user_data[user_id]["truck_number"] = text
        user_state[user_id] = STATE_REG_COMPANY
        # Показываем список компаний
        companies = await get_companies()
        kb = ReplyKeyboardMarkup(resize_keyboard=True)
        for comp in companies:
            kb.add(comp.name)
        await message.answer("Select your company:", reply_markup=kb)
        return

    if current_state == STATE_REG_COMPANY:
        # Проверяем, есть ли такая компания
        comp_name = text
        comp_obj = await sync_to_async(Company.objects.filter(name=comp_name).first)()
        if not comp_obj:
            await message.answer("Company not found. Please select from list.")
            return

        temp_user_data[user_id]["company_id"] = comp_obj.id
        data = temp_user_data[user_id]
        # Создаём TeleUser
        await create_teleuser(
            user_id,
            data["name"],
            data["nickname"],
            data["truck_number"],
            company_id=comp_obj.id
        )
        await message.answer("Registration complete!")
        user_state[user_id] = STATE_NONE
        temp_user_data[user_id] = {}

        # Если pending_question
        if user_id in pending_question:
            p = pending_question[user_id]
            cat = p["category"]
            qtxt = p["question"]

            kb = ReplyKeyboardMarkup(resize_keyboard=True)
            kb.add("Send", "Edit")
            kb.add("Cancel")

            await message.answer(
                f"You had a pending question in category '{cat}':\n\n{qtxt}\n"
                "Choose 'Send' or 'Edit' or 'Cancel'.",
                reply_markup=kb
            )
            user_state[user_id] = STATE_CONFIRM_PENDING
            return

        # Иначе меню
        kb = ReplyKeyboardMarkup(resize_keyboard=True)
        kb.add("Time Off")
        cats = await get_categories_async()
        for c in cats:
            kb.add(c.name)
        await message.answer("Now you can choose a category:", reply_markup=kb)
        return

    # --- Time Off flow ---
    if text == "Time Off":
        teleuser = await get_teleuser_by_id(user_id)
        if not teleuser:
            await message.answer("You are not registered. Please register first!")
            return

        if user_id not in temp_user_data:
            temp_user_data[user_id] = {}

        # Начинаем опрос дат
        user_state[user_id] = STATE_TIMEOFF_FROM
        today = date.today()
        kb = generate_calendar(today.year, today.month, min_date=today)
        await message.answer("Select FROM date:", reply_markup=kb)
        return

    if current_state == STATE_TIMEOFF_FROM:
        await message.answer("Please select FROM date from the calendar above.")
        return

    if current_state == STATE_TIMEOFF_TILL:
        await message.answer("Please select TILL date from the calendar above.")
        return

    if current_state == STATE_TIMEOFF_REASON:
        temp_user_data[user_id]["timeoff_reason"] = text
        user_state[user_id] = STATE_TIMEOFF_PAUSE
        kb = ReplyKeyboardMarkup(resize_keyboard=True)
        kb.add("Yes", "No")
        await message.answer("Pause Insurance and ELD?", reply_markup=kb)
        return

    if current_state == STATE_TIMEOFF_PAUSE:
        p_text = text.lower()
        pause_val = (p_text == "yes")
        temp_user_data[user_id]["timeoff_pause"] = pause_val

        # Создаём TimeOff
        data = temp_user_data[user_id]
        df = data["timeoff_from"]
        dt = data["timeoff_till"]
        reason = data["timeoff_reason"]

        teleuser = await get_teleuser_by_id(user_id)
        if not teleuser:
            await message.answer("You are not registered! Something is off.")
            user_state[user_id] = STATE_NONE
            return


        await create_timeoff(teleuser.id, df, dt, reason, pause_val)
        await message.answer("Your Time-Off request is saved!", reply_markup=ReplyKeyboardRemove())

        # Сброс
        user_state[user_id] = STATE_NONE
        temp_user_data[user_id] = {}

        # Возвращаем меню
        kb = ReplyKeyboardMarkup(resize_keyboard=True)
        kb.add("Time Off")
        cats = await get_categories_async()
        for c in cats:
            kb.add(c.name)
        await message.answer("Now you can choose a category:", reply_markup=kb)
        return

    # --- Another question flow ---
    if current_state == STATE_AWAITING_QUESTION and current_cat:
        teleuser = await get_teleuser_by_id(user_id)
        if not teleuser:
            pending_question[user_id] = {"category": current_cat, "question": text}
            kb = ReplyKeyboardMarkup(resize_keyboard=True)
            kb.add("📋 Register")
            kb.add("Time Off")
            cats = await get_categories_async()
            for cat in cats:
                kb.add(cat.name)
            await message.answer(
                "You are not registered yet. Please press 'Register' first!",
                reply_markup=kb
            )
            user_selected_category[user_id] = None
            user_state[user_id] = STATE_NONE
            return

        # User зарегистрирован, отправляем сразу
        await send_question_directly(user_id, current_cat, text, message)
        return

    # --- "Back" button ---
    if text == "🔙 Back":
        user_selected_category[user_id] = None
        user_state[user_id] = STATE_NONE
        kb = ReplyKeyboardMarkup(resize_keyboard=True)
        teleuser = await get_teleuser_by_id(user_id)
        if not teleuser:
            kb.add("📋 Register")
        kb.add("Time Off")
        cats = await get_categories_async()
        for c in cats:
            kb.add(c.name)
        await message.answer("You have returned to the list of categories.", reply_markup=kb)
        return

    # --- Trying to select category ---
    try:
        cat_obj = await sync_to_async(Category.objects.get)(name=text)
        user_selected_category[user_id] = text
        user_state[user_id] = STATE_NONE

        questions = await get_questions_for_category_async(text)
        kb = ReplyKeyboardMarkup(resize_keyboard=True)
        for q in questions:
            kb.add(q.question)
        kb.add("Another question")
        kb.add("🔙 Back")
        await message.answer(
            f"Category: <b>{text}</b>\nChoose a ready-made question or click Another question:",
            reply_markup=kb
        )
        return
    except Category.DoesNotExist:
        pass

    # --- If already chosen category, check ready questions ---
    if current_cat:
        questions = await get_questions_for_category_async(current_cat)
        found = None
        for q in questions:
            if text == q.question:
                found = q
                break
        if found:
            await message.answer(found.answer)
            return

        if text == "Another question":
            user_state[user_id] = STATE_AWAITING_QUESTION
            await message.answer("Please enter your question:", reply_markup=ReplyKeyboardRemove())
            return

        await message.answer("I did not understand your choice. Please select a ready question, click 'Another question' or 'Back'.")
        return

    # --- Otherwise ---
    await message.answer("Please choose a category or enter a command /start.")


# ---------------------------
#  Helper function to send question
# ---------------------------
async def send_question_directly(user_id: int, cat_name: str, question_text: str, message: types.Message):
    teleuser = await get_teleuser_by_id(user_id)
    if not teleuser:
        await message.answer("You are not registered!")
        user_state[user_id] = STATE_NONE
        return

    # "Name" is stored in teleuser.first_name
    name_val = teleuser.first_name or ""
    nick_val = teleuser.nickname or ""
    user_display = f"{name_val} ({nick_val}) - @{message.from_user.username or user_id}".strip()

    try:
        cat_obj = await sync_to_async(Category.objects.get)(name=cat_name)
        responsible_chat = cat_obj.responsible_chat
        responsible_topic_id = cat_obj.responsible_topic_id
    except Category.DoesNotExist:
        responsible_chat = None
        responsible_topic_id = None

    await save_user_question_async(
        user_id,
        message.from_user.username or "",
        cat_name,
        question_text,
        responsible_id=responsible_chat
    )

    forward_text = (
        f"New question from category <b>{cat_name}</b>\n"
        f"From user: {user_display}\n\n"
        f"Question text:\n{question_text}"
    )

    if responsible_chat:
        try:
            chat_id_for_sending = int(responsible_chat)
            if responsible_topic_id and responsible_topic_id.isdigit():
                tid = int(responsible_topic_id)
                await bot.send_message(
                    chat_id_for_sending,
                    text=forward_text,
                    message_thread_id=tid
                )
            else:
                await bot.send_message(chat_id_for_sending, forward_text)
        except Exception as e:
            await message.answer(f"Failed to send to specialists: {e}")

    await message.answer("Your question has been saved and forwarded to specialists. Thank you!")
    user_selected_category[user_id] = None
    user_state[user_id] = STATE_NONE

    # Show main menu
    cats = await get_categories_async()
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add("Time Off")
    for c in cats:
        kb.add(c.name)
    kb.add("🔙 Back")
    await message.answer("Choose category:", reply_markup=kb)


if __name__ == "__main__":
    executor.start_polling(dp, skip_updates=True)
