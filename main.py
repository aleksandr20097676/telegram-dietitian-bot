#!/usr/bin/env python3
"""
Telegram Dietitian Bot - Photo Food Analysis + Persistent onboarding (name/weight/height/age/activity/goal)
Python 3.8/3.9 compatible (NO `str | None`).
"""

import asyncio
import logging
import base64
import re
from typing import Optional, Dict, Any, List, Tuple

import httpx
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message
from aiogram.fsm.storage.memory import MemoryStorage
from openai import AsyncOpenAI

# Import configuration
from config import TELEGRAM_TOKEN, OPENAI_API_KEY, GPT_MODEL
from database import FOOD_DATABASE
from languages import detect_language, get_text

# DB helpers (your db.py from screenshots has these)
from db import (
    init_db,
    ensure_user,
    add_message,
    get_recent_messages,
    trim_messages,
    get_all_facts,
    get_fact,
    set_fact,
    set_facts,
)

# ---------------- Logging ----------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# ---------------- Clients ----------------
http_client = httpx.AsyncClient(timeout=60.0)
openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY, http_client=http_client)

bot = Bot(token=TELEGRAM_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# ---------------- Helpers: parsing ----------------

def _extract_ints(text: str) -> List[int]:
    # Extract standalone numbers like 114, 182, 49 from any separators
    return [int(x) for x in re.findall(r"\d{1,3}", text)]

def _is_probable_height(cm: int) -> bool:
    return 120 <= cm <= 230

def _is_probable_weight(kg: int) -> bool:
    return 30 <= kg <= 250

def _is_probable_age(age: int) -> bool:
    return 5 <= age <= 110

def parse_w_h_a(text: str) -> Optional[Tuple[int, int, int]]:
    """
    Accepts: "114,182,49" or "114 182 49" or "114/182/49" etc.
    Interprets as weight(kg), height(cm), age.
    """
    nums = _extract_ints(text)
    if len(nums) < 3:
        return None

    # Prefer first 3 numbers
    w, h, a = nums[0], nums[1], nums[2]
    if _is_probable_weight(w) and _is_probable_height(h) and _is_probable_age(a):
        return w, h, a

    # Try to find any triple in order that matches ranges
    for i in range(0, len(nums) - 2):
        w, h, a = nums[i], nums[i + 1], nums[i + 2]
        if _is_probable_weight(w) and _is_probable_height(h) and _is_probable_age(a):
            return w, h, a

    return None

def parse_single_number(text: str) -> Optional[int]:
    nums = _extract_ints(text)
    if not nums:
        return None
    return nums[0]

def normalize_name(text: str) -> str:
    # Keep it simple; strip weird chars
    t = text.strip()
    t = re.sub(r"\s+", " ", t)
    t = t.strip(".,!?:;\"'`")
    return t[:40]


# ---------------- Helpers: onboarding ----------------

ORDERED_FACTS = ["name", "goal", "weight_kg", "height_cm", "age", "activity"]

def profile_missing(facts: Dict[str, Any]) -> Optional[str]:
    """
    Returns key of first missing fact or None if all present.
    """
    for k in ORDERED_FACTS:
        v = facts.get(k)
        if v is None or str(v).strip() == "":
            return k
    return None

def onboarding_question(lang: str, missing_key: str) -> str:
    # You can later move these into languages.py, but keeping here is fastest.
    if lang == "cs":
        if missing_key == "name":
            return "Jak se jmenuješ? Napiš prosím jen své křestní jméno."
        if missing_key == "goal":
            return "Jaký máš cíl? (zhubnout / udržet váhu / nabrat svaly)"
        if missing_key in ("weight_kg", "height_cm", "age"):
            return "Napiš prosím jedním řádkem: váha, výška, věk. Např.: 114, 182, 49"
        if missing_key == "activity":
            return "Jaká je tvoje aktivita? (nízká / střední / vysoká) a co děláš v práci?"
        return "Napiš prosím potřebné údaje."
    if lang == "en":
        if missing_key == "name":
            return "What’s your name? Please type just your first name."
        if missing_key == "goal":
            return "What’s your goal? (lose weight / maintain / gain muscle)"
        if missing_key in ("weight_kg", "height_cm", "age"):
            return "Send in one message: weight, height, age. Example: 114, 182, 49"
        if missing_key == "activity":
            return "What’s your activity level? (low / medium / high) and what do you do for work?"
        return "Please provide the required details."
    # ru default
    if missing_key == "name":
        return "Как тебя зовут? Напиши, пожалуйста, только имя."
    if missing_key == "goal":
        return "Какая цель? (похудеть / поддерживать / набрать мышечную массу)"
    if missing_key in ("weight_kg", "height_cm", "age"):
        return "Напиши одним сообщением: вес, рост, возраст. Например: 114, 182, 49"
    if missing_key == "activity":
        return "Какая у тебя активность? (низкая / средняя / высокая) и чем занимаешься (работа)?"
    return "Напиши, пожалуйста, нужные данные."

def goal_from_text(text: str, lang: str) -> Optional[str]:
    t = (text or "").lower()

    # RU
    if any(x in t for x in ["похуд", "сброс", "снизить вес"]):
        return "lose_weight"
    if any(x in t for x in ["поддерж", "удерж", "сохран"]):
        return "maintain"
    if any(x in t for x in ["набрать", "масса", "мышц", "набор"]):
        return "gain_muscle"

    # CS
    if any(x in t for x in ["zhub", "shodit"]):
        return "lose_weight"
    if any(x in t for x in ["udrž", "držet"]):
        return "maintain"
    if any(x in t for x in ["nabrat", "sval"]):
        return "gain_muscle"

    # EN
    if any(x in t for x in ["lose", "cut", "slim"]):
        return "lose_weight"
    if any(x in t for x in ["maintain", "keep"]):
        return "maintain"
    if any(x in t for x in ["gain", "muscle", "bulk"]):
        return "gain_muscle"

    return None


# ---------------- AI: photo analysis ----------------

async def analyze_food_photo(photo_bytes: bytes, user_language: str) -> str:
    try:
        base64_image = base64.b64encode(photo_bytes).decode("utf-8")

        db_description = "Available food database:\n"
        for food_name, food_data in FOOD_DATABASE.items():
            db_description += (
                f"- {food_name}: {food_data['calories']} kcal per {food_data['portion']}, "
                f"Protein: {food_data['protein']}g, Carbs: {food_data['carbs']}g, Fat: {food_data['fat']}g\n"
            )

        prompt = get_text(user_language, "analysis_prompt").format(db_description=db_description)

        response = await openai_client.chat.completions.create(
            model=GPT_MODEL,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/jpeg;base64,{base64_image}", "detail": "high"},
                        },
                    ],
                }
            ],
            max_tokens=1000,
            temperature=0.7,
        )

        result = response.choices[0].message.content or ""
        logger.info("Photo analysis done (%s)", user_language)
        return result.strip() if result else get_text(user_language, "error_analysis")

    except Exception as e:
        logger.error("Error analyzing photo: %s", e)
        return get_text(user_language, "error_analysis")


# ---------------- AI: chat reply with context ----------------

def build_system_prompt(lang: str, facts: Dict[str, Any]) -> str:
    name = facts.get("name") or ""
    goal = facts.get("goal") or ""
    weight = facts.get("weight_kg")
    height = facts.get("height_cm")
    age = facts.get("age")
    activity = facts.get("activity") or ""

    if lang == "cs":
        return (
            "Jsi přátelský a chytrý dietolog. Mluv stručně a věcně.\n"
            f"Uživatel: jméno={name}, cíl={goal}, váha={weight}, výška={height}, věk={age}, aktivita={activity}.\n"
            "Pokud něco chybí, zeptej se jen na chybějící údaj.\n"
            "Dávej praktické kroky: jídelníček, kalorický cíl, tipy.\n"
            "Když je to vhodné, nabídni poslat fotku jídla."
        )
    if lang == "en":
        return (
            "You are a friendly and smart dietitian. Be concise and practical.\n"
            f"User facts: name={name}, goal={goal}, weight={weight}, height={height}, age={age}, activity={activity}.\n"
            "If something is missing, ask ONLY for the missing item.\n"
            "Give actionable steps: calories, plan, simple meals.\n"
            "If useful, suggest sending a food photo."
        )
    return (
        "Ты дружелюбный и умный диетолог. Отвечай кратко и по делу.\n"
        f"Данные пользователя: имя={name}, цель={goal}, вес={weight}, рост={height}, возраст={age}, активность={activity}.\n"
        "Если чего-то не хватает — спроси ТОЛЬКО недостающее.\n"
        "Дай практичный план: калории, питание, шаги.\n"
        "Если уместно — предложи прислать фото еды."
    )

async def chat_reply(user_text: str, user_language: str, facts: Dict[str, Any], history: List[Dict[str, str]]) -> str:
    try:
        system_prompt = build_system_prompt(user_language, facts)

        messages = [{"role": "system", "content": system_prompt}]

        # Add small history (already in OpenAI format: role/content)
        for m in history[-10:]:
            if "role" in m and "content" in m:
                messages.append({"role": m["role"], "content": m["content"]})

        messages.append({"role": "user", "content": user_text})

        resp = await openai_client.chat.completions.create(
            model=GPT_MODEL,
            messages=messages,
            max_tokens=450,
            temperature=0.7,
        )

        return (resp.choices[0].message.content or "").strip() or get_text(user_language, "error_general")

    except Exception as e:
        logger.error("Error in chat_reply: %s", e)
        return get_text(user_language, "error_general")


# ---------------- Handlers ----------------

@dp.message(Command("start"))
async def cmd_start(message: Message) -> None:
    user_language = detect_language(getattr(message.from_user, "language_code", None))

    # Ensure user exists in DB
    await ensure_user(
        user_id=message.from_user.id,
        username=message.from_user.username,
        first_name=message.from_user.first_name,
        language=user_language,
    )

    facts = await get_all_facts(message.from_user.id)
    missing = profile_missing(facts)

    if missing:
        await message.answer(get_text(user_language, "welcome"))
        await message.answer(onboarding_question(user_language, missing))
    else:
        # Already onboarded
        await message.answer(get_text(user_language, "greeting"))


@dp.message(Command("help"))
async def cmd_help(message: Message) -> None:
    user_language = detect_language(getattr(message.from_user, "language_code", None))
    await message.answer(get_text(user_language, "help"))


@dp.message(F.photo)
async def handle_photo(message: Message) -> None:
    user_language = detect_language(getattr(message.from_user, "language_code", None))

    await ensure_user(
        user_id=message.from_user.id,
        username=message.from_user.username,
        first_name=message.from_user.first_name,
        language=user_language,
    )

    facts = await get_all_facts(message.from_user.id)
    missing = profile_missing(facts)
    if missing:
        # If not onboarded, ask missing first
        await message.answer(onboarding_question(user_language, missing))
        return

    try:
        status_msg = await message.answer(get_text(user_language, "analyzing"))
        photo = message.photo[-1]
        photo_file = await bot.get_file(photo.file_id)
        photo_bytes = await bot.download_file(photo_file.file_path)

        result = await analyze_food_photo(photo_bytes.read(), user_language)

        try:
            await status_msg.delete()
        except Exception:
            pass

        await message.answer(result)

    except Exception as e:
        logger.error("Error handling photo: %s", e)
        await message.answer(get_text(user_language, "error_general"))


async def handle_onboarding_text(user_id: int, lang: str, text: str) -> Optional[str]:
    """
    Returns reply text if we handled onboarding, otherwise None.
    """
    facts = await get_all_facts(user_id)
    missing = profile_missing(facts)
    if not missing:
        return None

    t = (text or "").strip()

    # Step 1: name
    if missing == "name":
        name = normalize_name(t)
        if len(name) < 2:
            return onboarding_question(lang, "name")
        await set_fact(user_id, "name", name)
        facts = await get_all_facts(user_id)
        missing2 = profile_missing(facts)
        if missing2:
            return onboarding_question(lang, missing2)
        return get_text(lang, "greeting")

    # Step 2: goal
    if missing == "goal":
        g = goal_from_text(t, lang)
        if not g:
            return onboarding_question(lang, "goal")
        await set_fact(user_id, "goal", g)
        facts = await get_all_facts(user_id)
        missing2 = profile_missing(facts)
        if missing2:
            return onboarding_question(lang, missing2)
        return get_text(lang, "greeting")

    # Weight/height/age group: accept 3 numbers at once
    if missing in ("weight_kg", "height_cm", "age"):
        triple = parse_w_h_a(t)
        if triple:
            w, h, a = triple
            await set_facts(user_id, {"weight_kg": str(w), "height_cm": str(h), "age": str(a)})
            facts = await get_all_facts(user_id)
            missing2 = profile_missing(facts)
            if missing2:
                return onboarding_question(lang, missing2)
            # finished
            if lang == "cs":
                return "Super! Mám vše. Napiš, co chceš řešit, nebo pošli fotku jídla."
            if lang == "en":
                return "Great! I have everything. Tell me what you want to do, or send a food photo."
            return "Отлично! Всё записала. Напиши, что хочешь сделать, или пришли фото еды."

        # If user sends only 1 number, fill in missing sequentially
        n = parse_single_number(t)
        if n is None:
            return onboarding_question(lang, "weight_kg")

        # Decide which exactly missing among three
        w = facts.get("weight_kg")
        h = facts.get("height_cm")
        a = facts.get("age")

        if not w and _is_probable_weight(n):
            await set_fact(user_id, "weight_kg", str(n))
        elif not h and _is_probable_height(n):
            await set_fact(user_id, "height_cm", str(n))
        elif not a and _is_probable_age(n):
            await set_fact(user_id, "age", str(n))
        else:
            # Ask again with explicit format
            return onboarding_question(lang, "weight_kg")

        facts = await get_all_facts(user_id)
        missing2 = profile_missing(facts)
        if missing2:
            return onboarding_question(lang, missing2)
        if lang == "cs":
            return "Super! Mám vše. Napiš, co chceš řešit, nebo pošli fotku jídla."
        if lang == "en":
            return "Great! I have everything. Tell me what you want to do, or send a food photo."
        return "Отлично! Всё записала. Напиши, что хочешь сделать, или пришли фото еды."

    # Activity
    if missing == "activity":
        if len(t) < 3:
            return onboarding_question(lang, "activity")
        await set_fact(user_id, "activity", t[:120])
        facts = await get_all_facts(user_id)
        missing2 = profile_missing(facts)
        if missing2:
            return onboarding_question(lang, missing2)
        if lang == "cs":
            return "Perfektní. Teď mi napiš, co přesně chceš (jídelníček, kalorie, plán), nebo pošli fotku jídla."
        if lang == "en":
            return "Perfect. Now tell me what you want (meal plan, calories, plan), or send a food photo."
        return "Отлично. Теперь напиши, что именно нужно (план питания/калории/рацион), или пришли фото еды."

    return onboarding_question(lang, missing)


@dp.message()
async def handle_text(message: Message) -> None:
    user_language = detect_language(getattr(message.from_user, "language_code", None))
    user_id = message.from_user.id
    text_raw = message.text or ""
    text_norm = text_raw.strip()

    await ensure_user(
        user_id=user_id,
        username=message.from_user.username,
        first_name=message.from_user.first_name,
        language=user_language,
    )

    # Save message to DB
    try:
        await add_message(user_id, "user", text_norm)
        await trim_messages(user_id, keep_last=60)
    except Exception as e:
        logger.warning("DB add_message/trim failed: %s", e)

    # Fast greeting handling
    low = text_norm.lower()
    greetings = ["привет", "здравств", "hello", "hi", "ahoj", "čau"]
    if any(g in low for g in greetings):
        await message.answer(get_text(user_language, "greeting"))
        return

    # Onboarding first
    onboarding_reply = await handle_onboarding_text(user_id, user_language, text_norm)
    if onboarding_reply is not None:
        try:
            await add_message(user_id, "assistant", onboarding_reply)
            await trim_messages(user_id, keep_last=60)
        except Exception:
            pass
        await message.answer(onboarding_reply)
        return

    # Normal chat with context
    facts = await get_all_facts(user_id)

    try:
        history = await get_recent_messages(user_id, limit=20)
    except Exception:
        history = []

    reply = await chat_reply(text_norm, user_language, facts, history)

    try:
        await add_message(user_id, "assistant", reply)
        await trim_messages(user_id, keep_last=60)
    except Exception:
        pass

    await message.answer(reply)


# ---------------- Main ----------------

async def main() -> None:
    logger.info("Starting Telegram Dietitian Bot...")
    logger.info("Using %s for analysis/chat", GPT_MODEL)

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
