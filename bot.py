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

from main.models import Category, Question, UserQuestion, TeleUser

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

STATE_REG_NAME = "REG_NAME"
STATE_REG_LASTNAME = "REG_LASTNAME"
STATE_REG_NICKNAME = "REG_NICKNAME"
STATE_REG_TRUCK = "REG_TRUCK"

# Новое состояние для inline-редактирования
STATE_INLINE_EDIT = "INLINE_EDIT"

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
def create_teleuser(telegram_id, first_name, last_name, nickname, truck_number):
    return TeleUser.objects.create(
        telegram_id=telegram_id,
        first_name=first_name,
        last_name=last_name,
        nickname=nickname,
        truck_number=truck_number
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
    # Только если упомянули бота
    if "@sayram_help_bot" in text:
        inline_kb = types.InlineKeyboardMarkup()
        bot_link = "https://t.me/sayram_help_bot"
        inline_kb.add(types.InlineKeyboardButton("Go to the bot's private messages", url=bot_link))
        await message.reply("To ask a question, please go to the bot's private messages:", reply_markup=inline_kb)

# ---------------------------
#  Inline Mode handler
# ---------------------------
@dp.inline_handler()
async def inline_query_echo(inline_query: types.InlineQuery):
    """
    Если пользователь нажал кнопку с switch_inline_query_current_chat,
    он попадает сюда. Возвращаем одну статью, которую можно «отправить» с изменённым текстом.
    """
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

    categories = await get_categories_async()
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    existing_user = await get_teleuser_by_id(user_id)
    if not existing_user:
        kb.add("📋 Register")
    for cat in categories:
        kb.add(cat.name)
    await message.answer("Hello! Select category or press 'Register': \n <b>Registration</b> takes 30 seconds and is required only once per ID.", reply_markup=kb)

# ---------------------------
#  Main message handler
# ---------------------------
@dp.message_handler()
async def handle_message(message: types.Message):
    text = message.text.strip()
    user_id = message.from_user.id
    current_cat = user_selected_category.get(user_id)
    current_state = user_state.get(user_id, STATE_NONE)

    # ---------------------------
    #  State: STATE_INLINE_EDIT
    # ---------------------------
    # Если пользователь уже нажал "Edit" (inline-кнопка), ждём финальное сообщение
    if current_state == STATE_INLINE_EDIT:
        # Пользователь отправляет отредактированный вопрос (inline result)
        # Приходит новое message, которое мы принимаем как окончательный текст вопроса
        pending = pending_question.pop(user_id, None)
        if not pending:
            await message.answer("No pending question found.")
            user_state[user_id] = STATE_NONE
            return

        final_text = message.text
        category_name = pending["category"]

        # Отправляем вопрос
        await send_question_directly(user_id, category_name, final_text, message)

        user_state[user_id] = STATE_NONE
        return

    # ---------------------------
    #  State: STATE_CONFIRM_PENDING
    # ---------------------------
    if current_state == STATE_CONFIRM_PENDING:
        if text == "Send":
            # Отправляем вопрос
            pending = pending_question.pop(user_id, None)
            if not pending:
                await message.answer("No pending question found.")
                user_state[user_id] = STATE_NONE
                return

            await send_question_directly(
                user_id,
                pending["category"],
                pending["question"],
                message
            )
            return

        elif text == "Edit":
            # Переходим к inline-редактированию
            user_state[user_id] = STATE_INLINE_EDIT
            old_text = pending_question[user_id]["question"]
            inline_kb = types.InlineKeyboardMarkup()
            inline_kb.add(
                types.InlineKeyboardButton(
                    "Edit in inline mode",
                    switch_inline_query_current_chat=old_text
                )
            )
            await message.answer("Click the button below to edit your question in inline mode.", reply_markup=inline_kb)
            return

        else:
            # «No» или что-то другое => отмена
            pending_question.pop(user_id, None)
            await message.answer("Pending question canceled.")
            user_state[user_id] = STATE_NONE
            # Показать меню
            categories = await get_categories_async()
            kb = ReplyKeyboardMarkup(resize_keyboard=True)
            existing_user = await get_teleuser_by_id(user_id)
            if not existing_user:
                kb.add("📋 Register")
            for cat in categories:
                kb.add(cat.name)
            await message.answer("Choose category:", reply_markup=kb)
            return

    # ---------------------------
    #  Registration flow
    # ---------------------------
    if text == "📋 Register" or text.lower() == "register":
        existing_user = await get_teleuser_by_id(user_id)
        if existing_user:
            await message.answer("You are already registered!")
            return
        else:
            user_state[user_id] = STATE_REG_NAME
            temp_user_data[user_id] = {}
            await message.answer("Enter your first name:", reply_markup=ReplyKeyboardRemove())
            return

    if current_state == STATE_REG_NAME:
        temp_user_data[user_id]["first_name"] = text
        user_state[user_id] = STATE_REG_LASTNAME
        await message.answer("Enter your last name:")
        return

    if current_state == STATE_REG_LASTNAME:
        temp_user_data[user_id]["last_name"] = text
        user_state[user_id] = STATE_REG_NICKNAME
        await message.answer("Enter your nickname:")
        return

    if current_state == STATE_REG_NICKNAME:
        temp_user_data[user_id]["nickname"] = text
        user_state[user_id] = STATE_REG_TRUCK
        await message.answer("Enter your truck number (or type 'no' if none):")
        return

    if current_state == STATE_REG_TRUCK:
        temp_user_data[user_id]["truck_number"] = text
        data = temp_user_data[user_id]
        await create_teleuser(
            user_id,
            data["first_name"],
            data["last_name"],
            data["nickname"],
            data["truck_number"]
        )
        await message.answer("Registration complete!")
        user_state[user_id] = STATE_NONE
        temp_user_data[user_id] = {}

        # Если есть pending question, предлагаем "Send"/"Edit"
        if user_id in pending_question:
            pending = pending_question[user_id]
            cat = pending["category"]
            question_txt = pending["question"]

            kb = ReplyKeyboardMarkup(resize_keyboard=True)
            kb.add("Send", "Edit")
            kb.add("Cancel")

            await message.answer(
                f"You had a pending question in category '{cat}':\n\n"
                f"{question_txt}\n"
                "Choose 'Send' to send immediately, or 'Edit' to rewrite in inline mode, or 'Cancel'.",
                reply_markup=kb
            )
            user_state[user_id] = STATE_CONFIRM_PENDING
            return

        # Иначе - меню категорий
        categories = await get_categories_async()
        kb = ReplyKeyboardMarkup(resize_keyboard=True)
        for c in categories:
            kb.add(c.name)
        await message.answer("Now you can choose a category:", reply_markup=kb)
        return

    # ---------------------------
    #  If we're awaiting question
    # ---------------------------
    if current_state == STATE_AWAITING_QUESTION and current_cat:
        teleuser = await get_teleuser_by_id(user_id)
        if not teleuser:
            # Сохраняем pending
            pending_question[user_id] = {"category": current_cat, "question": text}
            kb = ReplyKeyboardMarkup(resize_keyboard=True)
            kb.add("📋 Register")
            cats = await get_categories_async()
            for cat in cats:
                kb.add(cat.name)
            await message.answer(
                "You are not registered yet. Please press 'Register' first! \n <b>Registration</b> takes 30 seconds and is required only once per ID.",
                reply_markup=kb
            )
            user_selected_category[user_id] = None
            user_state[user_id] = STATE_NONE
            return

        # Если user зарегистрирован - отправляем сразу
        await send_question_directly(user_id, current_cat, text, message)
        return

    # ---------------------------
    #  If text == "🔙 Back"
    # ---------------------------
    if text == "🔙 Back":
        user_selected_category[user_id] = None
        user_state[user_id] = STATE_NONE
        cats = await get_categories_async()
        kb = ReplyKeyboardMarkup(resize_keyboard=True)
        existing_user = await get_teleuser_by_id(user_id)
        if not existing_user:
            kb.add("📋 Register")
        for c in cats:
            kb.add(c.name)
        await message.answer("You have returned to the list of categories.", reply_markup=kb)
        return

    # ---------------------------
    #  Check if user selected a category
    # ---------------------------
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

    # ---------------------------
    #  If there's a current_cat, check ready questions
    # ---------------------------
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
            # remove keyboard
            await message.answer("Please enter your question:", reply_markup=ReplyKeyboardRemove())
            return

        await message.answer("I did not understand your choice. Please select a ready question, click 'Another question' or 'Back'.")
        return

    # If none
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

    first_n = teleuser.first_name or ""
    last_n = teleuser.last_name or ""
    nick_n = teleuser.nickname or ""
    user_display = f"{first_n} {last_n} ({nick_n}) - @{message.from_user.username or user_id}".strip()

    # Сохраняем вопрос
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
                topic_id_for_sending = int(responsible_topic_id)
                await bot.send_message(
                    chat_id_for_sending,
                    text=forward_text,
                    message_thread_id=topic_id_for_sending
                )
            else:
                await bot.send_message(chat_id_for_sending, forward_text)
        except Exception as e:
            await message.answer(f"Failed to send to specialists: {e}")

    await message.answer("Your question has been saved and forwarded to specialists. Thank you!")
    user_selected_category[user_id] = None
    user_state[user_id] = STATE_NONE

    # Показываем меню категорий
    cats = await get_categories_async()
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    for c in cats:
        kb.add(c.name)
    kb.add("🔙 Back")
    await message.answer("Choose category:", reply_markup=kb)

# ---------------------------
#  Launch
# ---------------------------
if __name__ == "__main__":
    executor.start_polling(dp, skip_updates=True)
