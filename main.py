#!/usr/bin/env python3
"""
Telegram Dietitian Bot - remembers user profile (name/weight/height/age/goal/activity)
and does NOT ask again unless profile is missing or user uses /reset.
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

# DB helpers (must exist in your db.py; based on your screenshots)
from db import (
    init_db,
    ensure_user,
    add_message,
    get_recent_messages,
    set_facts,
    get_all_facts,
)

# ---------------- LOGGING ----------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------- OPENAI ----------------
http_client = httpx.AsyncClient(timeout=60.0)
openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY, http_client=http_client)

# ---------------- TELEGRAM ----------------
bot = Bot(token=TELEGRAM_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# ---------------- HELPERS ----------------

def _clean_text(s: str) -> str:
    return (s or "").strip()

def _extract_three_numbers(text: str):
    """
    Accepts: "114, 182, 49" or "114 182 49" or "вес 114 рост 182 возраст 49"
    Returns tuple (weight_kg, height_cm, age) as ints or None
    """
    nums = re.findall(r"\d{1,3}", text)
    if len(nums) < 3:
        return None
    w, h, a = int(nums[0]), int(nums[1]), int(nums[2])

    # Basic sanity (so bot doesn't store nonsense)
    if not (30 <= w <= 300):
        return None
    if not (120 <= h <= 230):
        return None
    if not (10 <= a <= 100):
        return None

    return w, h, a

def _profile_missing(facts: dict) -> str | None:
    """
    Returns the next missing field key or None if profile is complete.
    We store everything in user_facts for simplicity.
    """
    required = ["name", "weight_kg", "height_cm", "age", "goal", "activity"]
    for k in required:
        v = (facts.get(k) or "").strip()
        if not v:
            return k
    return None

def _goal_from_text(text: str) -> str | None:
    t = text.lower()
    if any(x in t for x in ["похуд", "сброс", "сниз", "минус"]):
        return "похудеть"
    if any(x in t for x in ["набрать", "массу", "прибав", "плюс"]):
        return "набрать"
    if any(x in t for x in ["поддерж", "держать", "сохран"]):
        return "поддерживать"
    return None

def _activity_from_text(text: str) -> str | None:
    t = text.lower()
    if any(x in t for x in ["сидяч", "миним", "низк", "офис", "мало хожу"]):
        return "низкая"
    if any(x in t for x in ["средн", "умерен", "хожу", "2-3", "трен 1-3"]):
        return "средняя"
    if any(x in t for x in ["высок", "спорт", "трен 4-7", "тяжел", "физич"]):
        return "высокая"
    return None

async def _ask_next_question(message: Message, user_language: str, facts: dict):
    missing = _profile_missing(facts)
    if not missing:
        return

    if missing == "name":
        await message.answer("Как тебя зовут? Напиши просто имя 🙂")
        return

    if missing in ("weight_kg", "height_cm", "age"):
        await message.answer(
            "Напиши **тремя числами**: вес (кг), рост (см), возраст.\n"
            "Например: `114, 182, 49` или `114 182 49`"
        )
        return

    if missing == "goal":
        await message.answer(
            "Какая цель?\n"
            "1) похудеть\n"
            "2) набрать\n"
            "3) поддерживать\n"
            "Ответь одним словом."
        )
        return

    if missing == "activity":
        await message.answer(
            "Какая у тебя активность?\n"
            "1) низкая (сидячая работа)\n"
            "2) средняя (ходьба/тренировки 1–3 раза)\n"
            "3) высокая (физическая работа/тренировки 4–7 раз)\n"
            "Ответь: низкая / средняя / высокая."
        )
        return


# ---------------- GPT FUNCTIONS ----------------

async def analyze_food_photo(photo_bytes: bytes, user_language: str) -> str:
    try:
        base64_image = base64.b64encode(photo_bytes).decode("utf-8")

        db_description = "Available food database:\n"
        for food_name, food_data in FOOD_DATABASE.items():
            db_description += (
                f"- {food_name}: {food_data['calories']} kcal per {food_data['portion']}, "
                f"Protein: {food_data['protein']}g, Carbs: {food_data['carbs']}g, Fat: {food_data['fat']}g\n"
            )

        prompt = (
            "Ты диетолог. Определи еду на фото и оцени калории и БЖУ.\n"
            "Используй базу ниже как подсказку, но если еды там нет — оцени по опыту.\n\n"
            f"{db_description}\n"
            "Ответ дай кратко и по делу."
        )

        response = await openai_client.chat.completions.create(
            model=GPT_MODEL,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{base64_image}",
                                "detail": "high",
                            },
                        },
                    ],
                }
            ],
            max_tokens=800,
            temperature=0.5,
        )

        return response.choices[0].message.content.strip()

    except Exception as e:
        logger.error(f"Error analyzing photo: {e}")
        return get_text(user_language, "error_analysis")


async def chat_reply(user_id: int, user_text: str, user_language: str) -> str:
    """
    Uses: profile facts + recent messages context.
    """
    try:
        facts = await get_all_facts(user_id)

        profile_line = (
            f"Профиль пользователя: "
            f"имя={facts.get('name','')}, "
            f"вес={facts.get('weight_kg','')}кг, "
            f"рост={facts.get('height_cm','')}см, "
            f"возраст={facts.get('age','')}, "
            f"цель={facts.get('goal','')}, "
            f"активность={facts.get('activity','')}."
        )

        system_ru = (
            "Ты дружелюбный и умный диетолог. Общайся как человек. "
            "Отвечай коротко и по делу. "
            "Используй профиль пользователя и не переспрашивай то, что уже есть в профиле. "
            "Если чего-то нет — попроси конкретно недостающий пункт одним вопросом."
        )
        system_cs = (
            "Jsi přátelský a chytrý dietolog. Mluv jako člověk. "
            "Odpovídej stručně a věcně. "
            "Používej profil uživatele a neptej se znovu na údaje, které už máš. "
            "Pokud něco chybí, zeptej se jen na chybějící údaj."
        )
        system_en = (
            "You are a friendly and smart dietitian. Be concise and practical. "
            "Use the user profile and do not ask again for data already present. "
            "If something is missing, ask only for the missing item."
        )

        system_map = {"ru": system_ru, "cs": system_cs, "en": system_en}
        system_prompt = system_map.get(user_language, system_en)

        history = await get_recent_messages(user_id, limit=12)
        # history should be list of dicts: {"role": "user"/"assistant", "content": "..."}
        messages = [{"role": "system", "content": system_prompt + "\n" + profile_line}]

        # add history
        for m in history:
            r = m.get("role")
            c = m.get("content")
            if r in ("user", "assistant") and c:
                messages.append({"role": r, "content": c})

        # add current user message
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


# ---------------- HANDLERS ----------------

@dp.message(Command("start"))
async def cmd_start(message: Message):
    user_id = message.from_user.id
    user_language = detect_language(message.from_user.language_code)

    # Ensure user exists in DB
    await ensure_user(
        user_id=user_id,
        username=message.from_user.username,
        first_name=message.from_user.first_name,
        language=user_language,
    )

    facts = await get_all_facts(user_id)
    missing = _profile_missing(facts)

    if not missing:
        name = facts.get("name", "")
        await message.answer(f"Привет, {name}! 🙂 Я готов. Напиши вопрос или пришли фото еды.")
        return

    await message.answer("Привет! 🙂 Я AI-диетолог. Давай быстро настроим профиль, и я всё запомню.")
    await _ask_next_question(message, user_language, facts)


@dp.message(Command("profile"))
async def cmd_profile(message: Message):
    user_id = message.from_user.id
    facts = await get_all_facts(user_id)

    if not facts:
        await message.answer("Профиль пуст. Напиши /start")
        return

    await message.answer(
        "Вот что я запомнил:\n"
        f"Имя: {facts.get('name','—')}\n"
        f"Вес: {facts.get('weight_kg','—')} кг\n"
        f"Рост: {facts.get('height_cm','—')} см\n"
        f"Возраст: {facts.get('age','—')}\n"
        f"Цель: {facts.get('goal','—')}\n"
        f"Активность: {facts.get('activity','—')}\n\n"
        "Если нужно заново — /reset"
    )


@dp.message(Command("reset"))
async def cmd_reset(message: Message):
    user_id = message.from_user.id
    user_language = detect_language(message.from_user.language_code)

    # "Reset" by overwriting facts to empty values
    await set_facts(user_id, {
        "name": "",
        "weight_kg": "",
        "height_cm": "",
        "age": "",
        "goal": "",
        "activity": "",
    })

    await message.answer("Ок, сбросил профиль. Начнём заново 🙂")
    facts = await get_all_facts(user_id)
    await _ask_next_question(message, user_language, facts)


@dp.message(F.photo)
async def handle_photo(message: Message):
    user_id = message.from_user.id
    user_language = detect_language(message.from_user.language_code)

    # Ensure user exists
    await ensure_user(
        user_id=user_id,
        username=message.from_user.username,
        first_name=message.from_user.first_name,
        language=user_language,
    )

    # If profile missing, guide user first (optional)
    facts = await get_all_facts(user_id)
    missing = _profile_missing(facts)
    if missing:
        await message.answer("Сначала заполним профиль, чтобы расчёты были точнее 🙂")
        await _ask_next_question(message, user_language, facts)
        return

    try:
        status_msg = await message.answer(get_text(user_language, "analyzing"))

        photo = message.photo[-1]
        photo_file = await bot.get_file(photo.file_id)
        photo_bytes = await bot.download_file(photo_file.file_path)

        result = await analyze_food_photo(photo_bytes.read(), user_language)

        await status_msg.delete()
        await message.answer(result)

        # Save to history
        await add_message(user_id, "user", "[photo]")
        await add_message(user_id, "assistant", result)

    except Exception as e:
        logger.error(f"Error handling photo: {e}")
        await message.answer(get_text(user_language, "error_general"))


@dp.message()
async def handle_text(message: Message):
    user_id = message.from_user.id
    user_language = detect_language(message.from_user.language_code)
    text_raw = _clean_text(message.text)
    text_low = text_raw.lower()

    # Ensure user exists
    await ensure_user(
        user_id=user_id,
        username=message.from_user.username,
        first_name=message.from_user.first_name,
        language=user_language,
    )

    # Save user message to history early
    if text_raw:
        await add_message(user_id, "user", text_raw)

    facts = await get_all_facts(user_id)
    missing = _profile_missing(facts)

    # Greeting shortcut
    if any(x in text_low for x in ["привет", "здравств", "hello", "hi", "ahoj", "čau"]):
        if facts.get("name"):
            await message.answer(f"Привет, {facts.get('name')} 🙂")
        else:
            await message.answer("Привет 🙂")
        if missing:
            await _ask_next_question(message, user_language, facts)
        return

    # ---------------- ONBOARDING FLOW ----------------
    if missing:
        # 1) Name
        if missing == "name":
            name = text_raw.split()[0][:30]
            await set_facts(user_id, {"name": name})
            await message.answer(f"Отлично, {name}! 🙂")
            facts = await get_all_facts(user_id)
            await _ask_next_question(message, user_language, facts)
            return

        # 2) Numbers (weight,height,age)
        if missing in ("weight_kg", "height_cm", "age"):
            triple = _extract_three_numbers(text_raw)
            if not triple:
                await message.answer("Не вижу 3 корректных числа. Напиши так: `114, 182, 49`")
                return
            w, h, a = triple
            await set_facts(user_id, {"weight_kg": str(w), "height_cm": str(h), "age": str(a)})
            await message.answer(f"Принято ✅ Вес {w} кг, рост {h} см, возраст {a}.")
            facts = await get_all_facts(user_id)
            await _ask_next_question(message, user_language, facts)
            return

        # 3) Goal
        if missing == "goal":
            goal = _goal_from_text(text_raw) or text_low
            if goal not in ("похудеть", "набрать", "поддерживать"):
                await message.answer("Напиши одним словом: похудеть / набрать / поддерживать")
                return
            await set_facts(user_id, {"goal": goal})
            await message.answer("Ок ✅")
            facts = await get_all_facts(user_id)
            await _ask_next_question(message, user_language, facts)
            return

        # 4) Activity
        if missing == "activity":
            act = _activity_from_text(text_raw) or text_low
            if act not in ("низкая", "средняя", "высокая"):
                await message.answer("Ответь: низкая / средняя / высокая")
                return
            await set_facts(user_id, {"activity": act})
            await message.answer("Супер ✅ Я всё запомнил. Теперь можешь писать вопросы или присылать фото еды.")
            return

    # ---------------- NORMAL CHAT (PROFILE READY) ----------------
    reply = await chat_reply(user_id, text_raw, user_language)
    await message.answer(reply)
    await add_message(user_id, "assistant", reply)


async def main():
    logger.info("Starting Telegram Dietitian Bot...")
    logger.info(f"Using {GPT_MODEL} for analysis/chat")
    await init_db()

    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
