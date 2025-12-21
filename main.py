#!/usr/bin/env python3
"""
Telegram Dietitian Bot - Photo Food Analysis + Onboarding (saved to DB)

- Aiogram v3
- Stores user profile once (name/goal/weight/height/age/activity/job) in db.py "facts"
- Parses weight/height/age from: "114, 182, 49" or "114 182 49" or "114/182/49"
- Photo analysis works with vision-capable OpenAI model (set GPT_MODEL in config.py)
- Python 3.9 compatible (NO `str | None`)
"""

import asyncio
import logging
import base64
import re
from io import BytesIO
from typing import Optional, Tuple, Dict

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

# db.py functions (as in your screenshots)
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
      "вес 114 рост 182 возраст 49" (вытянет 3 числа)
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

def is_yes_no_reset(text: str) -> bool:
    t = normalize_text(text).lower()
    return t in {"reset", "/reset", "сброс", "заново", "начать заново"}

async def profile_missing(user_id: int) -> Optional[str]:
    """
    Returns a prompt string for what is missing OR None if profile is OK.
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
        return "Напиши одним сообщением: вес, рост, возраст. Например: 109, 182, 49"
    if not activity:
        return "Какая у тебя активность? (низкая/средняя/высокая) и чем занимаешься (работа)?"
    return None


async def analyze_food_photo(photo_bytes: bytes, user_language: str) -> str:
    """
    Vision analysis for food photo.
    IMPORTANT: GPT_MODEL must be a vision-capable model (e.g., 'gpt-4o-mini').
    """
    try:
        base64_image = base64.b64encode(photo_bytes).decode("utf-8")

        # small DB description
        db_description = "Food database examples:\n"
        for food_name, food_data in FOOD_DATABASE.items():
            db_description += (
                f"- {food_name}: {food_data['calories']} kcal per {food_data['portion']}, "
                f"P:{food_data['protein']}g C:{food_data['carbs']}g F:{food_data['fat']}g\n"
            )

        system_prompt = (
            "Ты диетолог. Анализируй ТОЛЬКО еду на фото. "
            "Не описывай людей, лица, личности, бренды, текст на предметах. "
            "Если еды не видно — попроси пользователя описать блюдо словами."
        )

        user_prompt = (
            f"{db_description}\n\n"
            "Определи, что за еда на фото. Оцени примерный вес порций, калории и БЖУ.\n"
            "Если не уверен — предложи 2-3 варианта и задай 1 уточняющий вопрос.\n"
            "Ответ дай кратко и по делу."
        )

        resp = await openai_client.chat.completions.create(
            model=GPT_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": user_prompt},
                        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}},
                    ],
                },
            ],
            max_tokens=900,
            temperature=0.2,
        )

        result = (resp.choices[0].message.content or "").strip()
        if not result:
            return get_text(user_language, "error_analysis")

        low = result.lower()
        if "не могу" in low and ("фото" in low or "изображ" in low):
            # fallback
            return (
                "Я не смог уверенно распознать еду на фото. "
                "Напиши, пожалуйста, что это и примерно сколько (граммы/ложки/кусочки) — "
                "и я посчитаю калории и БЖУ."
            )

        return result

    except Exception as e:
        logger.error(f"Error analyzing photo: {e}")
        return get_text(user_language, "error_analysis")


async def chat_reply(user_text: str, user_language: str, user_id: int) -> str:
    """
    Normal chat reply, but includes saved profile facts as context.
    """
    try:
        name = await get_fact(user_id, "name") or ""
        goal = await get_fact(user_id, "goal") or ""
        weight = await get_fact(user_id, "weight_kg") or ""
        height = await get_fact(user_id, "height_cm") or ""
        age = await get_fact(user_id, "age") or ""
        activity = await get_fact(user_id, "activity") or ""
        job = await get_fact(user_id, "job") or ""

        profile = f"Профиль пользователя: имя={name}, цель={goal}, вес={weight}, рост={height}, возраст={age}, активность={activity}, работа={job}."

        system_ru = (
            "Ты дружелюбный и умный диетолог. Общайся как человек: "
            "коротко и по делу, 1-2 уточняющих вопроса только если нужно. "
            "Не спрашивай повторно то, что уже есть в профиле. "
            "Если уместно — предложи прислать фото еды для точного подсчёта.\n"
            + profile
        )

        system_cs = (
            "Jsi přátelský a chytrý dietolog. Odpovídej stručně a věcně. "
            "Neznovu se neptej na údaje, které už máš v profilu. "
            "Když je to vhodné, navrhni poslat fotku jídla.\n"
        )

        system_en = (
            "You are a friendly smart dietitian. Be concise and helpful. "
            "Do not ask again what is already in the profile. "
            "Suggest sending a food photo when relevant.\n"
        )

        system_map = {"ru": system_ru, "cs": system_cs, "en": system_en}
        system_prompt = system_map.get(user_language, system_ru)

        resp = await openai_client.chat.completions.create(
            model=GPT_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_text},
            ],
            max_tokens=450,
            temperature=0.6,
        )
        return (resp.choices[0].message.content or "").strip()

    except Exception as e:
        logger.error(f"Error in chat_reply: {e}")
        return get_text(user_language, "error_general")


# -------------------- commands --------------------
@dp.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    user_language = detect_language(message.from_user.language_code)
    user_id = message.from_user.id

    # If profile incomplete -> start onboarding where missing
    missing = await profile_missing(user_id)
    if missing is None:
        await state.clear()
        await message.answer("Привет! Я тебя помню 🙂 Напиши вопрос или пришли фото еды.")
        return

    await message.answer("👋 Привет! Я твой персональный диетолог-бот.")
    await message.answer(missing)

    # set correct state based on what missing
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
    await message.answer(
        "Команды:\n"
        "/start — начать\n"
        "reset — сбросить анкету и пройти заново\n\n"
        "Можно писать вопросы или присылать фото еды."
    )


# -------------------- reset --------------------
@dp.message(F.text)
async def reset_if_needed(message: Message, state: FSMContext):
    """
    This handler runs for any text first, and if user says reset -> wipes facts.
    Then we stop processing (return) by setting a flag in state and checking later.
    """
    if not message.text:
        return

    if is_yes_no_reset(message.text):
        user_id = message.from_user.id
        # wipe only onboarding facts
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
        await message.answer("Ок, анкету сбросил. Напиши /start и пройдём заново.")
        # Mark handled to avoid double reply in other handlers
        await state.update_data(_handled=True)


def _handled_flag(data: Dict) -> bool:
    return bool(data.get("_handled"))


# -------------------- photo handler --------------------
@dp.message(F.photo)
async def handle_photo(message: Message, state: FSMContext):
    data = await state.get_data()
    if _handled_flag(data):
        return

    user_language = detect_language(message.from_user.language_code)
    user_id = message.from_user.id

    # if onboarding not complete -> ask missing first (no photo analysis yet)
    missing = await profile_missing(user_id)
    if missing is not None:
        await message.answer(missing)
        if "как тебя зовут" in missing.lower():
            await state.set_state(Onboarding.waiting_name)
        elif "какая цель" in missing.lower():
            await state.set_state(Onboarding.waiting_goal)
        elif "вес, рост, возраст" in missing.lower():
            await state.set_state(Onboarding.waiting_whA)
        else:
            await state.set_state(Onboarding.waiting_activity)
        return

    status_msg = await message.answer(get_text(user_language, "analyzing") if hasattr(get_text, "__call__") else "Анализирую фото...")

    try:
        photo = message.photo[-1]
        file = await bot.get_file(photo.file_id)

        buf = BytesIO()
        # aiogram can download by file_path
        await bot.download_file(file.file_path, destination=buf)
        photo_bytes = buf.getvalue()

        result = await analyze_food_photo(photo_bytes, user_language)
        await status_msg.delete()
        await message.answer(result)

    except Exception as e:
        logger.error(f"Error handling photo: {e}")
        try:
            await status_msg.delete()
        except Exception:
            pass
        await message.answer(get_text(user_language, "error_general"))


# -------------------- onboarding handlers --------------------
@dp.message(Onboarding.waiting_name, F.text)
async def onboarding_name(message: Message, state: FSMContext):
    data = await state.get_data()
    if _handled_flag(data):
        return

    user_id = message.from_user.id
    name = normalize_text(message.text)
    if len(name) < 2 or len(name) > 30:
        await message.answer("Напиши, пожалуйста, только имя (2–30 символов).")
        return

    await set_fact(user_id, "name", name)
    await message.answer("Какая цель? (похудеть / поддерживать / набрать мышечную массу)")
    await state.set_state(Onboarding.waiting_goal)


@dp.message(Onboarding.waiting_goal, F.text)
async def onboarding_goal(message: Message, state: FSMContext):
    data = await state.get_data()
    if _handled_flag(data):
        return

    user_id = message.from_user.id
    goal = normalize_text(message.text).lower()

    # normalize
    if "пох" in goal:
        goal_norm = "похудеть"
    elif "поддерж" in goal:
        goal_norm = "поддерживать"
    elif "наб" in goal or "мыш" in goal:
        goal_norm = "набрать мышечную массу"
    else:
        goal_norm = normalize_text(message.text)

    await set_fact(user_id, "goal", goal_norm)

    await message.answer("Напиши одним сообщением: вес, рост, возраст. Например: 109, 182, 49")
    await state.set_state(Onboarding.waiting_whA)


@dp.message(Onboarding.waiting_whA, F.text)
async def onboarding_wha(message: Message, state: FSMContext):
    data = await state.get_data()
    if _handled_flag(data):
        return

    user_id = message.from_user.id
    parsed = parse_weight_height_age(message.text)
    if parsed is None:
        await message.answer("Не понял формат. Напиши так: 109, 182, 49 (вес, рост, возраст)")
        return

    w, h, a = parsed
    await set_facts(user_id, {
        "weight_kg": str(w),
        "height_cm": str(h),
        "age": str(a),
    })

    await message.answer("Какая у тебя активность? (низкая/средняя/высокая) и чем занимаешься (работа)?")
    await state.set_state(Onboarding.waiting_activity)


@dp.message(Onboarding.waiting_activity, F.text)
async def onboarding_activity(message: Message, state: FSMContext):
    data = await state.get_data()
    if _handled_flag(data):
        return

    user_id = message.from_user.id
    text = normalize_text(message.text)

    # very simple parse: first word activity, rest job
    t = text.lower()
    activity = ""
    if "низ" in t:
        activity = "низкая"
    elif "сред" in t:
        activity = "средняя"
    elif "выс" in t:
        activity = "высокая"
    else:
        activity = text.split(",")[0].strip() if text else ""

    job = ""
    if "," in text:
        job = text.split(",", 1)[1].strip()
    else:
        # try after activity word
        job = text

    await set_facts(user_id, {
        "activity": activity,
        "job": job,
    })

    await state.clear()
    await message.answer("Отлично. Теперь напиши, что тебе нужно (план питания/калории/рацион), или пришли фото еды.")


# -------------------- default text handler --------------------
@dp.message(F.text)
async def handle_text(message: Message, state: FSMContext):
    data = await state.get_data()
    if _handled_flag(data):
        return

    user_language = detect_language(message.from_user.language_code)
    user_id = message.from_user.id
    text = normalize_text(message.text)

    # If in onboarding state, let onboarding handlers work (do nothing here)
    current_state = await state.get_state()
    if current_state in {
        Onboarding.waiting_name.state,
        Onboarding.waiting_goal.state,
        Onboarding.waiting_whA.state,
        Onboarding.waiting_activity.state,
    }:
        return

    # ensure profile is complete; if not -> start onboarding step
    missing = await profile_missing(user_id)
    if missing is not None:
        await message.answer(missing)
        if "как тебя зовут" in missing.lower():
            await state.set_state(Onboarding.waiting_name)
        elif "какая цель" in missing.lower():
            await state.set_state(Onboarding.waiting_goal)
        elif "вес, рост, возраст" in missing.lower():
            await state.set_state(Onboarding.waiting_whA)
        else:
            await state.set_state(Onboarding.waiting_activity)
        return

    # greetings quick reply
    low = text.lower()
    if any(x in low for x in ["привет", "здрав", "hello", "hi", "ahoj", "čau"]):
        name = await get_fact(user_id, "name") or ""
        await message.answer(f"Привет, {name}! 🙂 Чем помочь? Можешь спросить про план/калории или прислать фото еды.")
        return

    reply = await chat_reply(text, user_language, user_id)
    await message.answer(reply)


# -------------------- run --------------------
async def main():
    logger.info("Starting bot...")
    logger.info(f"GPT_MODEL = {GPT_MODEL} (must support vision for photos)")

    await init_db()

    try:
        await dp.start_polling(bot)
    finally:
        try:
            await bot.session.close()
        except Exception:
            pass
        try:
            await http_client.aclose()
        except Exception:
            pass


if __name__ == "__main__":
    asyncio.run(main())




