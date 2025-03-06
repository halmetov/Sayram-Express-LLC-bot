import os
import django
from asgiref.sync import sync_to_async


os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'Saypress.settings')
django.setup()

import logging
from aiogram import Bot, Dispatcher, types, executor
from aiogram.types import ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from main.models import Category, Question, UserQuestion, TeleUser

logging.basicConfig(level=logging.INFO)

TOKEN = "7943795810:AAG0wun2bnwieW2K8Aefv9XHSXx2lFIJV8Y"
bot = Bot(token=TOKEN, parse_mode=types.ParseMode.HTML)
dp = Dispatcher(bot)


@dp.message_handler(lambda message: message.chat.type in ["group", "supergroup"])
async def group_redirect(message: types.Message):
    text = message.text or ""
    if f"@sayram_help_bot" in text :
        inline_kb = types.InlineKeyboardMarkup()
        bot_link = "https://t.me/sayram_help_bot"
        inline_kb.add(types.InlineKeyboardButton("Go to the bot's private messages", url=bot_link))
        await message.reply("To ask a question, please go to the bot's private messages:", reply_markup=inline_kb)


user_selected_category = {}
user_state = {}
STATE_NONE = "NONE"
STATE_AWAITING_QUESTION = "AWAITING_QUESTION"

STATE_REG_NAME = "REG_NAME"
STATE_REG_LASTNAME = "REG_LASTNAME"
STATE_REG_NICKNAME = "REG_NICKNAME"
STATE_REG_TRUCK = "REG_TRUCK"


temp_user_data = {}


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
    """
    Возвращает список всех категорий.
    """
    return list(Category.objects.all())

@sync_to_async
def get_questions_for_category_async(category_name: str):
    """
    Находит категорию по имени и возвращает список вопросов (FAQ) для неё.
    """
    try:
        cat = Category.objects.get(name=category_name)
    except Category.DoesNotExist:
        return []
    return list(Question.objects.filter(category=cat))

@sync_to_async
def save_user_question_async(user_id, username, category_name, question_text, responsible_id=None):
    """
    Сохраняет вопрос пользователя в модель UserQuestion.
    Если категория не найдена, сохраняет с category=None.
    """
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
            kb.add(KeyboardButton(cat.name))
        await message.answer("Hello! Select category or press 'Register':", reply_markup=kb)
    else:
        for cat in categories:
            kb.add(KeyboardButton(cat.name))

        await message.answer("Hello! Select category:", reply_markup=kb)




@dp.message_handler()
async def handle_message(message: types.Message):
    text = message.text
    user_id = message.from_user.id
    current_cat = user_selected_category.get(user_id, None)
    current_state = user_state.get(user_id, STATE_NONE)

    if text == "📋 Register":
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
        await message.answer("Enter your truck number if exists or text 'no':")
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
        categories = await get_categories_async()
        kb = ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
        for cat in categories:
            kb.add(cat.name)
        await message.answer("Now you can choose a category:", reply_markup=kb)
        return


    # Если бот ждёт ввода вопроса (после "Другой вопрос")
    if current_state == STATE_AWAITING_QUESTION and current_cat:

        teleuser = await get_teleuser_by_id(user_id)
        if not teleuser:
            kb = ReplyKeyboardMarkup(resize_keyboard=True)
            kb.add("📋 Register")
            categories = await get_categories_async()
            for cat in categories:
                kb.add(cat.name)
            await message.answer(
                "You are not registered yet. Please press 'Register' first!",
                reply_markup=kb
            )

            user_selected_category[user_id] = None
            user_state[user_id] = STATE_NONE
            return


        first_n = teleuser.first_name or ""
        last_n = teleuser.last_name or ""
        nick_n = teleuser.nickname or ""

        user_display = f"{first_n} {last_n} ({nick_n}) - @{message.from_user.username or user_id}".strip()


        category_obj = await sync_to_async(lambda: Category.objects.get(name=current_cat))()
        responsible_chat = category_obj.responsible_chat
        responsible_topic_id = category_obj.responsible_topic_id


        await save_user_question_async(
            user_id,
            message.from_user.username or "",
            current_cat,
            text,
            responsible_id=responsible_chat
        )
        forward_text = (
            f"New question from category <b>{current_cat}</b>\n"
            f"From user: {user_display}\n\n"
            f"Question text:\n{text}"
        )


        if responsible_chat:
            try:
                chat_id_for_sending = int(responsible_chat)
                if responsible_topic_id and responsible_topic_id.isdigit():
                    topic_id_for_sending = int(responsible_topic_id)
                    await bot.send_message(
                        chat_id=chat_id_for_sending,
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

        categories = await get_categories_async()
        kb = ReplyKeyboardMarkup(resize_keyboard=True)
        for cat in categories:
            kb.add(cat.name)
        kb.add(KeyboardButton("🔙 Back"))
        await message.answer("Choose category:", reply_markup=kb)
        return


    if text == "🔙 Back":
        user_selected_category[user_id] = None
        user_state[user_id] = STATE_NONE
        categories = await get_categories_async()
        kb = ReplyKeyboardMarkup(resize_keyboard=True)

        existing_user = await get_teleuser_by_id(user_id)
        if not existing_user:
            kb.add("📋 Register")

        for cat in categories:
            kb.add(KeyboardButton(cat.name))
        await message.answer("You have returned to the list of categories.:", reply_markup=kb)
        return


    try:
        category_obj = await sync_to_async(Category.objects.get)(name=text)
        user_selected_category[user_id] = text
        user_state[user_id] = STATE_NONE

        questions = await get_questions_for_category_async(text)
        kb = ReplyKeyboardMarkup(resize_keyboard=True)
        for q in questions:
            kb.add(KeyboardButton(q.question))
        kb.add(KeyboardButton("Another question"))
        kb.add(KeyboardButton("🔙 Back"))
        await message.answer(f"Category: <b>{text}</b>\nChoose a ready-made question or click Another question:", reply_markup=kb)
        return
    except Category.DoesNotExist:
        pass

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
            await message.answer("Please enter your question:")
            return

        await message.answer("I did not understand your choice. Please select a ready question, click «Another question» or «Back».")
        return

    await message.answer("Please choose a category or enter a command /start.")




if __name__ == "__main__":
    executor.start_polling(dp, skip_updates=True)
