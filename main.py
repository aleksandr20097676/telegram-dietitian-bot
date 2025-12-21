#!/usr/bin/env python3
"""
Telegram Dietitian Bot - Photo Food Analysis
Uses OpenAI for food recognition and calorie calculation
"""

import asyncio
import logging
import base64
import re
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message
from aiogram.fsm.storage.memory import MemoryStorage
import httpx
from openai import AsyncOpenAI

# Import configuration
from config import TELEGRAM_TOKEN, OPENAI_API_KEY, GPT_MODEL
from database import FOOD_DATABASE
from languages import detect_language, get_text
from db import init_db, get_user, upsert_user, add_message, get_recent_messages

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Initialize OpenAI client
http_client = httpx.AsyncClient(timeout=60.0)
openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY, http_client=http_client)

# Initialize bot and dispatcher
bot = Bot(token=TELEGRAM_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# -----------------------------
# Helpers (onboarding + parsing)
# -----------------------------

def _clean_text(s: str) -> str:
    return (s or "").strip()

def parse_three_numbers(text: str):
    """
    Берём первые три числа из текста:
    1-е = вес, 2-е = рост, 3-е = возраст
    Поддерживает: "114,182,49" / "114 182 49" / "вес 114 рост 182 возраст 49" / "114/182/49"
    """
    nums = re.findall(r"\d+", text or "")
    if len(nums) < 3:
        return None
    w, h, a = int(nums[0]), int(nums[1]), int(nums[2])
    return w, h, a

def normalize_goal(text: str):
    t = (text or "").lower()
    if any(x in t for x in ["похуд", "сброс", "минус", "fat loss", "lose"]):
        return "похудеть"
    if any(x in t for x in ["набрат", "масса", "набор", "gain"]):
        return "набрать"
    if any(x in t for x in ["удерж", "поддерж", "maintenance"]):
        return "удержание"
    return None

def normalize_activity(text: str):
    t = (text or "").lower().strip()
    # Можно ответить цифрой
    if t in ["1", "2", "3", "4"]:
        return t
    # Или словами
    if any(x in t for x in ["сидяч", "офис", "мало", "почти нет"]):
        return "1"
    if any(x in t for x in ["немного", "ходьба", "5", "6", "7", "8", "тыс"]):
        return "2"
    if any(x in t for x in ["трен", "спорт", "зал", "3 раза", "4 раза"]):
        return "3"
    if any(x in t for x in ["тяж", "стройка", "физ", "каждый день", "работа"]):
        return "4"
    return None

async def ensure_user_row(message: Message, user_language: str):
    """
    Обновляем базовые поля пользователя в БД (если есть такая таблица).
    """
    try:
        await upsert_user(
            message.from_user.id,
            username=message.from_user.username,
            first_name=message.from_user.first_name,
            language=user_language,
        )
    except Exception as e:
        logger.warning(f"ensure_user_row upsert_user failed: {e}")

async def onboarding_stage(user: dict) -> str:
    """
    Определяем, какой шаг анкеты нужен прямо сейчас, исходя из того, что уже есть в БД.
    Если что-то не записалось — бот не будет 'ходить по кругу', а спросит конкретно.
    """
    if not user or not user.get("name"):
        return "ask_name"
    if not user.get("goal"):
        return "ask_goal"
    if not (user.get("weight_kg") and user.get("height_cm") and user.get("age")):
        return "ask_profile"
    if not user.get("activity"):
        return "ask_activity"
    return "ready"

# -----------------------------
# OpenAI features
# -----------------------------

async def analyze_food_photo(photo_bytes: bytes, user_language: str) -> str:
    try:
        base64_image = base64.b64encode(photo_bytes).decode("utf-8")

        db_description = "Available food database:\n"
        for food_name, food_data in FOOD_DATABASE.items():
            db_description += f"- {food_name}: {food_data['calories']} kcal per {food_data['portion']}, "
            db_description += f"Protein: {food_data['protein']}g, Carbs: {food_data['carbs']}g, Fat: {food_data['fat']}g\n"

        prompt = get_text(user_language, "analysis_prompt").format(db_description=db_description)

        response = await openai_client.chat.completions.create(
            model=GPT_MODEL,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url",
                     "image_url": {"url": f"data:image/jpeg;base64,{base64_image}", "detail": "high"}}
                ]
            }],
            max_tokens=1000,
            temperature=0.7
        )

        result = response.choices[0].message.content
        logger.info(f"Analysis completed for {user_language} language")
        return result

    except Exception as e:
        logger.error(f"Error analyzing photo: {e}")
        return get_text(user_language, "error_analysis")

async def chat_reply(user_id: int, user_text: str, user_language: str) -> str:
    """
    Обычный чат, но с контекстом профиля + последние сообщения.
    """
    try:
        user = await get_user(user_id)
        profile_line = ""
        if user:
            profile_line = (
                f"Профиль пользователя: имя={user.get('name')}, "
                f"цель={user.get('goal')}, вес={user.get('weight_kg')}, рост={user.get('height_cm')}, возраст={user.get('age')}, "
                f"активность={user.get('activity')}.\n"
            )

        system_ru = (
            "Ты дружелюбный и умный диетолог. Общайся как человек: "
            "задай 1-2 уточняющих вопроса, предложи план, отвечай коротко и по делу. "
            "Без воды. Если уместно — предложи прислать фото еды для точного подсчёта.\n"
            + profile_line
        )
        system_cs = (
            "Jsi přátelský a chytrý dietolog. Mluv jako člověk: "
            "polož 1–2 doplňující otázky, navrhni plán, odpovídej stručně a věcně. "
            "Když se hodí, nabídni poslat fotku jídla pro přesnější výpočet.\n"
            + profile_line
        )
        system_en = (
            "You are a friendly and smart dietitian. Talk like a human: "
            "ask 1–2 clarifying questions, suggest a plan, keep it concise and useful. "
            "If relevant, suggest sending a food photo for accurate calculation.\n"
            + profile_line
        )

        system_map = {"ru": system_ru, "cs": system_cs, "en": system_en}
        system_prompt = system_map.get(user_language, system_en)

        history = []
        try:
            history = await get_recent_messages(user_id, limit=12)
        except Exception as e:
            logger.warning(f"get_recent_messages failed: {e}")

        messages = [{"role": "system", "content": system_prompt}]
        if history:
            # ожидается [{"role": "...", "content": "..."}]
            messages.extend(history[-12:])
        messages.append({"role": "user", "content": user_text})

        resp = await openai_client.chat.completions.create(
            model=GPT_MODEL,
            messages=messages,
            max_tokens=400,
            temperature=0.7,
        )

        return resp.choices[0].message.content.strip()

    except Exception as e:
        logger.error(f"Error in chat_reply: {e}")
        return get_text(user_language, "error_general")

# -----------------------------
# Handlers
# -----------------------------

@dp.message(Command("start"))
async def cmd_start(message: Message):
    user_language = detect_language(message.from_user.language_code)
    await ensure_user_row(message, user_language)

    # Принудительно начинаем с имени
    await upsert_user(message.from_user.id, name=None)  # сброс имени, если хочешь заново
    await message.answer("Привет! 😊 Я твой AI-диетолог.\nКак тебя зовут?")

@dp.message(Command("help"))
async def cmd_help(message: Message):
    user_language = detect_language(message.from_user.language_code)
    await message.answer(get_text(user_language, "help"))

@dp.message(F.photo)
async def handle_photo(message: Message):
    user_language = detect_language(message.from_user.language_code)
    await ensure_user_row(message, user_language)

    try:
        status_msg = await message.answer(get_text(user_language, "analyzing"))
        photo = message.photo[-1]
        photo_file = await bot.get_file(photo.file_id)
        photo_bytes = await bot.download_file(photo_file.file_path)

        result = await analyze_food_photo(photo_bytes.read(), user_language)
        await status_msg.delete()
        await message.answer(result)

    except Exception as e:
        logger.error(f"Error handling photo: {e}")
        await message.answer(get_text(user_language, "error_general"))

@dp.message()
async def handle_text(message: Message):
    user_language = detect_language(message.from_user.language_code)
    await ensure_user_row(message, user_language)

    user_id = message.from_user.id
    text_raw = _clean_text(message.text)
    text_low = text_raw.lower()

    # Подтягиваем пользователя из БД, чтобы понимать какой шаг
    user = None
    try:
        user = await get_user(user_id)
    except Exception as e:
        logger.warning(f"get_user failed: {e}")

    stage = await onboarding_stage(user or {})

    # Если человек пишет "привет" и анкета не готова — всё равно начинаем анкету
    greetings = ["привет", "здравств", "hello", "hi", "ahoj", "čau"]
    if any(g in text_low for g in greetings) and stage != "ready":
        # Если имени нет — спросим имя
        if stage == "ask_name":
            await message.answer("Привет! 😊 Как тебя зовут?")
            return

    # --- Шаг 1: имя ---
    if stage == "ask_name":
        name = text_raw.strip()
        # если человек прислал только числа/мусор, переспросим
        if len(name) < 2 or re.fullmatch(r"[\d\W_]+", name or ""):
            await message.answer("Напиши, пожалуйста, имя (например: Саша).")
            return

        await upsert_user(user_id, name=name, language=user_language)
        await message.answer(
            f"Отлично, {name}! Какая цель?\n"
            "1) Похудеть\n2) Набрать\n3) Удержание\n\n"
            "Можно просто написать: похудеть / набрать / удержание"
        )
        return

    # --- Шаг 2: цель ---
    if stage == "ask_goal":
        goal = normalize_goal(text_raw)
        if not goal:
            await message.answer("Напиши цель одним словом: похудеть / набрать / удержание.")
            return
        await upsert_user(user_id, goal=goal)
        await message.answer(
            "Супер. Теперь пришли ТРИ числа: вес, рост, возраст.\n"
            "Пример: 114, 182, 49\n"
            "Можно через пробел или запятую — как угодно."
        )
        return

    # --- Шаг 3: профиль (вес/рост/возраст) ---
    if stage == "ask_profile":
        parsed = parse_three_numbers(text_raw)
        if not parsed:
            nums = re.findall(r"\d+", text_raw or "")
            if len(nums) == 0:
                await message.answer("Мне нужны 3 числа: вес, рост, возраст. Например: 114, 182, 49")
                return
            if len(nums) == 1:
                await message.answer("Я вижу только одно число. Нужно 3: вес, рост, возраст. Пример: 114, 182, 49")
                return
            if len(nums) == 2:
                await message.answer("Я вижу два числа. Нужно 3: вес, рост, возраст. Пример: 114, 182, 49")
                return

        weight_kg, height_cm, age = parsed

        # Небольшая защита от бредовых значений
        if weight_kg < 30 or weight_kg > 300:
            await message.answer("Вес выглядит странно. Напиши ещё раз 3 числа: вес, рост, возраст (пример: 114, 182, 49)")
            return
        if height_cm < 120 or height_cm > 230:
            await message.answer("Рост выглядит странно. Напиши ещё раз 3 числа: вес, рост, возраст (пример: 114, 182, 49)")
            return
        if age < 10 or age > 100:
            await message.answer("Возраст выглядит странно. Напиши ещё раз 3 числа: вес, рост, возраст (пример: 114, 182, 49)")
            return

        await upsert_user(user_id, weight_kg=weight_kg, height_cm=height_cm, age=age)

        await message.answer(
            "Принято ✅\n"
            "Теперь активность (можно цифрой 1–4):\n"
            "1) сидячая\n"
            "2) немного ходьбы (5–8 тыс шагов)\n"
            "3) тренировки 3–4 раза/нед\n"
            "4) тяжёлая физическая работа"
        )
        return

    # --- Шаг 4: активность ---
    if stage == "ask_activity":
        act = normalize_activity(text_raw)
        if not act:
            await message.answer("Выбери активность цифрой 1–4 (или напиши словами: сидячая / ходьба / тренировки / тяжёлая).")
            return
        await upsert_user(user_id, activity=act)

        await message.answer("Отлично! Анкета готова ✅\nМожешь написать, что ел(а) сегодня, или пришли фото еды — посчитаю калории.")
        return

    # --- READY: обычный чат + сохранение истории ---
    try:
        await add_message(user_id, "user", text_raw)
    except Exception as e:
        logger.warning(f"add_message user failed: {e}")

    reply = await chat_reply(user_id, text_raw, user_language)

    try:
        await add_message(user_id, "assistant", reply)
    except Exception as e:
        logger.warning(f"add_message assistant failed: {e}")

    await message.answer(reply)

async def main():
    logger.info("Starting Telegram Dietitian Bot...")
    logger.info(f"Using {GPT_MODEL} for food analysis")

    await init_db()
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()
        await http_client.aclose()

if __name__ == "__main__":
    asyncio.run(main())
