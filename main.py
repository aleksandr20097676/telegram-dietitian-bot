#!/usr/bin/env python3
"""
Telegram Dietitian Bot - Photo Food Analysis + Onboarding (saved to DB)

ИСПРАВЛЕНО:
- System prompt для фото анализа - более мягкий и эффективный
- Парсинг активности и работы исправлен
- Упрощена логика обработки сообщений
- Сохранен весь диалог онбординга как в скринах
"""

import asyncio
import logging
import base64
import re
from io import BytesIO
from typing import Optional, Tuple

import httpx
from openai import AsyncOpenAI

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message

from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

# Your project modules
from config import TELEGRAM_TOKEN, OPENAI_API_KEY, GPT_MODEL
from database import FOOD_DATABASE
from languages import detect_language, get_text

# db.py functions
from db import init_db, set_fact, set_facts, get_fact


# -------------------- logging --------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("dietitian-bot")


# -------------------- OpenAI client --------------------
http_client = httpx.AsyncClient(timeout=60.0)
openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY, http_client=http_client)


# -------------------- aiogram --------------------
bot = Bot(token=TELEGRAM_TOKEN)
dp = Dispatcher(storage=MemoryStorage())


# -------------------- FSM states --------------------
class Onboarding(StatesGroup):
    waiting_name = State()
    waiting_goal = State()
    waiting_whA = State()       # weight,height,age
    waiting_activity = State()  # activity + job


# -------------------- helpers --------------------
def normalize_text(s: str) -> str:
    return (s or "").strip()


def parse_weight_height_age(text: str) -> Optional[Tuple[int, int, int]]:
    """
    Accepts:
      "114, 182, 49"
      "114 182 49"
      "114/182/49"
      "вес 114 рост 182 возраст 49"
    Returns (weight, height, age) if valid.
    """
    t = normalize_text(text)
    nums = re.findall(r"\d{1,3}", t)
    if len(nums) < 3:
        return None

    w = int(nums[0])
    h = int(nums[1])
    a = int(nums[2])

    # sanity checks
    if not (30 <= w <= 350):
        return None
    if not (120 <= h <= 230):
        return None
    if not (10 <= a <= 100):
        return None

    return (w, h, a)


def is_reset_command(text: str) -> bool:
    """Check if user wants to reset profile"""
    t = normalize_text(text).lower()
    return t in {"reset", "/reset", "сброс", "заново", "начать заново"}


async def profile_missing(user_id: int) -> Optional[str]:
    """
    Returns a prompt string for what is missing OR None if profile is complete.
    """
    name = await get_fact(user_id, "name")
    goal = await get_fact(user_id, "goal")
    weight = await get_fact(user_id, "weight_kg")
    height = await get_fact(user_id, "height_cm")
    age = await get_fact(user_id, "age")
    activity = await get_fact(user_id, "activity")

    if not name:
        return "Как тебя зовут? Напиши, пожалуйста, только имя."
    if not goal:
        return "Какая цель? (похудеть / поддерживать / набрать мышечную массу)"
    if not (weight and height and age):
        return "Напиши одним сообщением: вес, рост, возраст. Например: 114, 182, 49"
    if not activity:
        return "Какая у тебя активность? (низкая / средняя / высокая) и чем занимаешься (работа)?"
    return None


async def analyze_food_photo(photo_bytes: bytes, user_language: str) -> str:
    """
    Vision analysis for food photo.
    ИСПРАВЛЕНО: Более мягкий system prompt который не блокирует анализ.
    """
    try:
        base64_image = base64.b64encode(photo_bytes).decode("utf-8")

        # Small DB description for reference
        db_description = "Примеры из базы продуктов:\n"
        count = 0
        for food_name, food_data in FOOD_DATABASE.items():
            if count >= 15:  # Limit examples
                break
            db_description += (
                f"- {food_name}: {food_data['calories']} ккал/{food_data['portion']}, "
                f"Б:{food_data['protein']}г Ж:{food_data['fat']}г У:{food_data['carbs']}г\n"
            )
            count += 1

        # ✅ ИСПРАВЛЕННЫЙ system prompt - позитивный и конкретный
        system_prompt = (
            "Ты опытный диетолог-нутрициолог. Твоя задача - помочь пользователю понять "
            "питательную ценность еды на фотографии.\n\n"
            "ВАЖНО: Анализируй только еду и напитки. Игнорируй фон, посуду, людей.\n\n"
            "Если на фото НЕТ еды или напитков - вежливо попроси описать блюдо словами."
        )

        user_prompt = (
            f"{db_description}\n\n"
            "📸 Проанализируй еду на фотографии:\n"
            "1. Определи ЧТО за блюдо/продукты\n"
            "2. Оцени примерный вес каждого компонента (граммы)\n"
            "3. Рассчитай калории и БЖУ (белки/жиры/углеводы)\n\n"
            "Если не уверен в каком-то компоненте - предложи 2-3 варианта и задай "
            "ОДИН уточняющий вопрос.\n\n"
            "Формат ответа: краткий, дружелюбный, по делу."
        )

        resp = await openai_client.chat.completions.create(
            model=GPT_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": user_prompt},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}
                        },
                    ],
                },
            ],
            max_tokens=1000,
            temperature=0.3,
        )

        result = (resp.choices[0].message.content or "").strip()
        if not result:
            return "Не смог проанализировать фото. Попробуй другое фото или опиши блюдо словами."

        return result

    except Exception as e:
        logger.error(f"Error analyzing photo: {e}", exc_info=True)
        return (
            "Произошла ошибка при анализе фото 😔\n"
            "Попробуй ещё раз или опиши блюдо словами - я посчитаю калории!"
        )


async def chat_reply(user_text: str, user_language: str, user_id: int) -> str:
    """
    Normal chat reply with user profile context.
    """
    try:
        name = await get_fact(user_id, "name") or ""
        goal = await get_fact(user_id, "goal") or ""
        weight = await get_fact(user_id, "weight_kg") or ""
        height = await get_fact(user_id, "height_cm") or ""
        age = await get_fact(user_id, "age") or ""
        activity = await get_fact(user_id, "activity") or ""
        job = await get_fact(user_id, "job") or ""

        profile = (
            f"Профиль пользователя: имя={name}, цель={goal}, "
            f"вес={weight}кг, рост={height}см, возраст={age} лет, "
            f"активность={activity}, работа={job}."
        )

        system_ru = (
            "Ты дружелюбный и опытный AI-диетолог.\n\n"
            "Стиль общения:\n"
            "- Короткие ответы (2-4 предложения)\n"
            "- Один уточняющий вопрос максимум\n"
            "- Используй смайлы умеренно 🙂\n"
            "- НЕ переспрашивай данные из профиля\n\n"
            "Когда уместно - предлагай прислать фото еды для точного подсчёта калорий.\n\n"
            f"{profile}"
        )

        system_cs = (
            "Jsi přátelský a zkušený AI-dietolog.\n"
            "Odpovídej stručně (2-4 věty). Neptej se znovu na data z profilu.\n"
            f"{profile}"
        )

        system_en = (
            "You are a friendly and experienced AI dietitian.\n"
            "Keep answers concise (2-4 sentences). Don't ask again for profile data.\n"
            f"{profile}"
        )

        system_map = {"ru": system_ru, "cs": system_cs, "en": system_en}
        system_prompt = system_map.get(user_language, system_ru)

        resp = await openai_client.chat.completions.create(
            model=GPT_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_text},
            ],
            max_tokens=500,
            temperature=0.7,
        )
        return (resp.choices[0].message.content or "").strip()

    except Exception as e:
        logger.error(f"Error in chat_reply: {e}", exc_info=True)
        return "Произошла ошибка. Попробуй переформулировать вопрос 🙂"


# -------------------- /start command --------------------
@dp.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    """Handle /start command - begin or resume onboarding"""
    user_id = message.from_user.id
    await state.clear()

    # Check if profile is complete
    missing = await profile_missing(user_id)
    
    if missing is None:
        # Profile complete - welcome back
        name = await get_fact(user_id, "name") or "друг"
        await message.answer(
            f"Привет, {name}! 😊 Я твой AI-диетолог.\n"
            f"Как дела? Я твой AI-диетолог. Хочешь похудеть, набрать форму "
            f"или просто разобраться с питанием?"
        )
        return

    # Profile incomplete - start onboarding
    await message.answer(
        "Привет! 😊 Как дела? Я твой AI-диетолог. "
        "Хочешь похудеть, набрать форму или просто разобраться с питанием?"
    )
    
    await message.answer(missing)

    # Set correct state based on what's missing
    if "как тебя зовут" in missing.lower():
        await state.set_state(Onboarding.waiting_name)
    elif "какая цель" in missing.lower():
        await state.set_state(Onboarding.waiting_goal)
    elif "вес, рост, возраст" in missing.lower():
        await state.set_state(Onboarding.waiting_whA)
    else:
        await state.set_state(Onboarding.waiting_activity)


@dp.message(Command("help"))
async def cmd_help(message: Message):
    """Help command"""
    await message.answer(
        "📋 Команды:\n"
        "/start — начать или продолжить\n"
        "reset — сбросить анкету и пройти заново\n\n"
        "💬 Можно:\n"
        "- Задавать вопросы про питание\n"
        "- Присылать фото еды для анализа\n"
        "- Просить план питания или тренировок"
    )


# -------------------- reset handler --------------------
@dp.message(F.text)
async def check_reset(message: Message, state: FSMContext, skip_handlers: list = []):
    """
    Check for reset command FIRST before any other text processing.
    Uses handler priority to run first.
    """
    if not message.text or not is_reset_command(message.text):
        return  # Not a reset, continue to other handlers
    
    # User wants to reset
    user_id = message.from_user.id
    
    # Wipe profile data
    await set_facts(user_id, {
        "name": "",
        "goal": "",
        "weight_kg": "",
        "height_cm": "",
        "age": "",
        "activity": "",
        "job": "",
    })
    
    await state.clear()
    await message.answer(
        "✅ Анкету сбросил!\n"
        "Напиши /start чтобы пройти заново."
    )
    
    # Stop propagation to other handlers
    raise StopIteration


# -------------------- photo handler --------------------
@dp.message(F.photo)
async def handle_photo(message: Message, state: FSMContext):
    """Handle photo messages - analyze food"""
    user_language = detect_language(message.from_user.language_code)
    user_id = message.from_user.id

    # If onboarding not complete -> redirect to onboarding
    missing = await profile_missing(user_id)
    if missing is not None:
        await message.answer(
            "Сначала давай познакомимся! 🙂\n\n" + missing
        )
        
        # Set appropriate state
        if "как тебя зовут" in missing.lower():
            await state.set_state(Onboarding.waiting_name)
        elif "какая цель" in missing.lower():
            await state.set_state(Onboarding.waiting_goal)
        elif "вес, рост, возраст" in missing.lower():
            await state.set_state(Onboarding.waiting_whA)
        else:
            await state.set_state(Onboarding.waiting_activity)
        return

    # Profile complete - analyze photo
    status_msg = await message.answer("🔍 Анализирую фото...")

    try:
        photo = message.photo[-1]
        file = await bot.get_file(photo.file_id)

        buf = BytesIO()
        await bot.download_file(file.file_path, destination=buf)
        photo_bytes = buf.getvalue()

        result = await analyze_food_photo(photo_bytes, user_language)
        
        await status_msg.delete()
        await message.answer(result)

    except Exception as e:
        logger.error(f"Error handling photo: {e}", exc_info=True)
        try:
            await status_msg.delete()
        except:
            pass
        await message.answer(
            "Не смог обработать фото 😔\n"
            "Попробуй ещё раз или опиши блюдо словами!"
        )


# -------------------- onboarding: name --------------------
@dp.message(Onboarding.waiting_name, F.text)
async def onboarding_name(message: Message, state: FSMContext):
    """Collect user name"""
    if is_reset_command(message.text):
        return  # Let reset handler deal with it
    
    user_id = message.from_user.id
    name = normalize_text(message.text)
    
    if len(name) < 2 or len(name) > 30:
        await message.answer("Напиши, пожалуйста, только имя (2–30 символов).")
        return

    await set_fact(user_id, "name", name)
    
    await message.answer(
        f"Отлично, {name}! Какая цель?\n"
        "1) Похудеть\n"
        "2) Набрать\n"
        "3) Удержание\n\n"
        "Можно просто написать: похудеть / набрать / удержание"
    )
    await state.set_state(Onboarding.waiting_goal)


# -------------------- onboarding: goal --------------------
@dp.message(Onboarding.waiting_goal, F.text)
async def onboarding_goal(message: Message, state: FSMContext):
    """Collect user goal"""
    if is_reset_command(message.text):
        return
    
    user_id = message.from_user.id
    goal = normalize_text(message.text).lower()

    # Normalize goal
    if "пох" in goal or goal == "1":
        goal_norm = "похудеть"
    elif "удерж" in goal or "поддерж" in goal or goal == "3":
        goal_norm = "поддерживать"
    elif "наб" in goal or "мыш" in goal or goal == "2":
        goal_norm = "набрать мышечную массу"
    else:
        goal_norm = normalize_text(message.text)

    await set_fact(user_id, "goal", goal_norm)

    await message.answer(
        "Отлично, что вы решили заняться собой! "
        "Можете рассказать мне немного о своём росте, весе, уровне физической активности "
        "и какой результат хотите достичь? Это поможет составить более точный план."
    )
    
    await message.answer(
        "Напишите одним сообщением: вес (кг), рост (см), возраст. "
        "Например: вес 114 рост 182 возраст 49"
    )
    
    await state.set_state(Onboarding.waiting_whA)


# -------------------- onboarding: weight/height/age --------------------
@dp.message(Onboarding.waiting_whA, F.text)
async def onboarding_wha(message: Message, state: FSMContext):
    """Collect weight, height, age"""
    if is_reset_command(message.text):
        return
    
    user_id = message.from_user.id
    parsed = parse_weight_height_age(message.text)
    
    if parsed is None:
        await message.answer(
            "Не вижу: возраст. Напишите ещё раз одним сообщением."
        )
        return

    w, h, a = parsed
    await set_facts(user_id, {
        "weight_kg": str(w),
        "height_cm": str(h),
        "age": str(a),
    })

    await message.answer(
        "Какую цель вы хотите достичь: снизить вес, поддерживать текущий "
        "или набрать? Также расскажите немного о вашей физической активности."
    )
    
    await message.answer(
        "Какая у тебя активность? (низкая / средняя / высокая) "
        "и чем занимаешься (работа)?"
    )
    
    await state.set_state(Onboarding.waiting_activity)


# -------------------- onboarding: activity --------------------
@dp.message(Onboarding.waiting_activity, F.text)
async def onboarding_activity(message: Message, state: FSMContext):
    """Collect activity level and job"""
    if is_reset_command(message.text):
        return
    
    user_id = message.from_user.id
    text = normalize_text(message.text)

    # ✅ ИСПРАВЛЕН парсинг активности и работы
    t = text.lower()
    activity = ""
    job = ""
    
    # Detect activity level
    if "низ" in t:
        activity = "низкая"
    elif "сред" in t:
        activity = "средняя"
    elif "выс" in t:
        activity = "высокая"
    
    # Extract job - everything after comma or after activity word
    if "," in text:
        parts = text.split(",", 1)
        if not activity:
            activity = parts[0].strip()
        job = parts[1].strip()
    else:
        # Try to find job after activity keywords
        job_match = re.sub(r'(низкая|средняя|высокая)', '', t, flags=re.IGNORECASE).strip()
        job = job_match if job_match else ""
        
        if not activity:
            # If no activity detected, use first word as activity
            activity = text.split()[0] if text.split() else "средняя"

    await set_facts(user_id, {
        "activity": activity or "средняя",
        "job": job,
    })

    name = await get_fact(user_id, "name") or ""
    
    await state.clear()
    
    await message.answer(
        f"Отлично. Теперь напиши, что именно нужно (план питания/калории/рацион), "
        f"или пришли фото еды для анализа. Удачи!"
    )


# -------------------- default text handler --------------------
@dp.message(F.text)
async def handle_text(message: Message, state: FSMContext):
    """Handle all other text messages"""
    if is_reset_command(message.text):
        return  # Already handled by reset handler
    
    user_language = detect_language(message.from_user.language_code)
    user_id = message.from_user.id
    text = normalize_text(message.text)

    # If currently in onboarding state, don't process here
    current_state = await state.get_state()
    if current_state in {
        Onboarding.waiting_name.state,
        Onboarding.waiting_goal.state,
        Onboarding.waiting_whA.state,
        Onboarding.waiting_activity.state,
    }:
        # Let the onboarding handlers deal with it
        return

    # Ensure profile is complete
    missing = await profile_missing(user_id)
    if missing is not None:
        await message.answer(missing)
        
        # Set appropriate state
        if "как тебя зовут" in missing.lower():
            await state.set_state(Onboarding.waiting_name)
        elif "какая цель" in missing.lower():
            await state.set_state(Onboarding.waiting_goal)
        elif "вес, рост, возраст" in missing.lower():
            await state.set_state(Onboarding.waiting_whA)
        else:
            await state.set_state(Onboarding.waiting_activity)
        return

    # Quick greetings response
    low = text.lower()
    if any(x in low for x in ["привет", "здрав", "hello", "hi", "ahoj", "čau"]):
        name = await get_fact(user_id, "name") or "друг"
        await message.answer(
            f"Привет, {name}! 😊 Как дела? Я твой AI-диетолог. "
            f"Хочешь похудеть, набрать форму или просто разобраться с питанием?"
        )
        return

    # Normal chat using GPT
    reply = await chat_reply(text, user_language, user_id)
    await message.answer(reply)


# -------------------- run --------------------
async def main():
    logger.info("🚀 Starting Dietitian Bot...")
    logger.info(f"📊 GPT Model: {GPT_MODEL} (must support vision for photo analysis)")

    await init_db()
    logger.info("✅ Database initialized")

    try:
        logger.info("🤖 Bot is polling...")
        await dp.start_polling(bot)
    finally:
        logger.info("🛑 Shutting down...")
        try:
            await bot.session.close()
        except:
            pass
        try:
            await http_client.aclose()
        except:
            pass


if __name__ == "__main__":
    asyncio.run(main())




