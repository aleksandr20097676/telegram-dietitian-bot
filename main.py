#!/usr/bin/env python3
"""
Telegram Dietitian Bot - Photo Food Analysis + Persistent onboarding + chat history
Uses OpenAI (chat.completions) + PostgreSQL (db.py) for user profile & memory.
"""

import asyncio
import logging
import base64
import re
from typing import Optional, Tuple

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

# DB helpers (PostgreSQL)
from db import (
    init_db,
    get_user,
    upsert_user,
    add_message,
    get_recent_messages,
    trim_messages,
    set_fact,
    get_fact,
)

# -------------------- logging --------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# -------------------- OpenAI client --------------------
http_client = httpx.AsyncClient(timeout=60.0)
openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY, http_client=http_client)

# -------------------- bot --------------------
bot = Bot(token=TELEGRAM_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# -------------------- helpers: text fallbacks --------------------
def _t(lang: str, key: str, fallback: str) -> str:
    """
    Safe get_text: if key doesn't exist in languages.py dicts, use fallback.
    """
    try:
        s = get_text(lang, key)
        if isinstance(s, str) and s.strip():
            return s
    except Exception:
        pass
    return fallback


def _lang(message: Message) -> str:
    return detect_language(getattr(message.from_user, "language_code", None))


async def _ensure_user_row(message: Message, user_language: str) -> None:
    """
    Ensure user exists in DB and store basic Telegram fields.
    """
    u = message.from_user
    try:
        await upsert_user(
            u.id,
            username=(u.username or None),
            first_name=(u.first_name or None),
            language=user_language,
        )
    except Exception as e:
        logger.error(f"ensure_user_row failed: {e}")


# -------------------- onboarding parsing --------------------
def parse_goal(text: str) -> Optional[str]:
    """
    Very simple goal detector.
    Returns one of: 'lose', 'gain', 'maintain' or None
    """
    t = (text or "").lower()

    lose_kw = ["похуд", "сброс", "сниз", "минус", "жир", "хочу похуд", "сушк", "похудеть"]
    gain_kw = ["набрат", "массу", "прибав", "поправ", "вес вверх", "набор", "набирать"]
    keep_kw = ["поддерж", "остав", "держать", "сохран", "текущ", "не менять", "maintain", "keep"]

    if any(k in t for k in lose_kw):
        return "lose"
    if any(k in t for k in gain_kw):
        return "gain"
    if any(k in t for k in keep_kw):
        return "maintain"

    # Czech/English quick support
    if any(k in t for k in ["zhubn", "hubn", "snížit váhu", "lose weight", "cut"]):
        return "lose"
    if any(k in t for k in ["nabrat", "přibrat", "gain weight", "bulk"]):
        return "gain"
    if any(k in t for k in ["udržet", "maintain"]):
        return "maintain"

    return None


def parse_profile_numbers(text: str) -> Tuple[Optional[int], Optional[int], Optional[int]]:
    """
    Extract (weight_kg, height_cm, age) from free text.
    Accepts patterns like:
      "вес 114 рост 182 возраст 49"
      "114 182 49"
      "рост 182 вес 114"
    """
    if not text:
        return None, None, None

    t = text.lower()

    # explicit labels
    w = None
    h = None
    a = None

    m = re.search(r"(вес|weight)\s*[:\-]?\s*(\d{2,3})", t)
    if m:
        w = int(m.group(2))

    m = re.search(r"(рост|height)\s*[:\-]?\s*(\d{2,3})", t)
    if m:
        h = int(m.group(2))

    m = re.search(r"(возраст|age)\s*[:\-]?\s*(\d{1,3})", t)
    if m:
        a = int(m.group(2))

    # if no labels, try to infer from numbers
    nums = [int(x) for x in re.findall(r"\b(\d{1,3})\b", t)]
    nums = [n for n in nums if 10 <= n <= 250]

    # heuristic:
    # height often 140-210, weight 40-200, age 10-100
    if (w is None or h is None or a is None) and nums:
        candidates_h = [n for n in nums if 140 <= n <= 210]
        candidates_w = [n for n in nums if 40 <= n <= 200]
        candidates_a = [n for n in nums if 10 <= n <= 100]

        if h is None and candidates_h:
            h = candidates_h[0]

        if w is None and candidates_w:
            # if we already picked height and it's in candidates_w, avoid it
            for n in candidates_w:
                if n != h:
                    w = n
                    break
            if w is None and candidates_w:
                w = candidates_w[0]

        if a is None and candidates_a:
            # avoid picking same as height/weight
            for n in candidates_a:
                if n != h and n != w:
                    a = n
                    break
            if a is None:
                a = candidates_a[0]

    # sanity clamp
    if w is not None and not (30 <= w <= 250):
        w = None
    if h is not None and not (120 <= h <= 230):
        h = None
    if a is not None and not (10 <= a <= 110):
        a = None

    return w, h, a


def is_greeting(text: str) -> bool:
    t = (text or "").strip().lower()
    greetings = ["привет", "здравств", "hello", "hi", "ahoj", "čau", "dobrý den"]
    return any(g in t for g in greetings)


# -------------------- OpenAI logic --------------------
async def analyze_food_photo(photo_bytes: bytes, user_language: str) -> str:
    """
    Analyze food photo using OpenAI Vision (chat.completions).
    """
    try:
        base64_image = base64.b64encode(photo_bytes).decode("utf-8")

        db_description = "Available food database:\n"
        for food_name, food_data in FOOD_DATABASE.items():
            db_description += (
                f"- {food_name}: {food_data['calories']} kcal per {food_data['portion']}, "
                f"Protein: {food_data['protein']}g, Carbs: {food_data['carbs']}g, Fat: {food_data['fat']}g\n"
            )

        prompt = _t(
            user_language,
            "analysis_prompt",
            "You are a nutrition expert. Use the database below if possible.\n\n{db_description}\n\n"
            "1) Identify food items in the photo.\n"
            "2) Estimate portion size.\n"
            "3) Provide calories and macros.\n"
            "4) Give short, practical advice.\n",
        ).format(db_description=db_description)

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
            max_tokens=1000,
            temperature=0.7,
        )

        return (response.choices[0].message.content or "").strip()

    except Exception as e:
        logger.error(f"Error analyzing photo: {e}")
        return _t(user_language, "error_analysis", "Не смогла распознать фото. Попробуйте ещё раз.")


def build_system_prompt(lang: str, profile: dict) -> str:
    """
    System prompt with profile context.
    """
    name = profile.get("name") or profile.get("first_name") or ""
    age = profile.get("age")
    height = profile.get("height_cm")
    weight = profile.get("weight_kg")
    goal = profile.get("goal")
    activity = profile.get("activity")

    goal_map_ru = {"lose": "похудеть", "gain": "набрать вес/массу", "maintain": "поддерживать текущий вес"}
    goal_map_cs = {"lose": "zhubnout", "gain": "přibrat / nabrat", "maintain": "udržet váhu"}
    goal_map_en = {"lose": "lose weight", "gain": "gain weight", "maintain": "maintain weight"}

    if lang == "cs":
        goal_txt = goal_map_cs.get(goal, goal or "")
        base = (
            "Jsi přátelský a chytrý dietolog. Odpovídej stručně a věcně. "
            "Zeptej se jen když něco opravdu chybí. "
            "Můžeš navrhnout jednoduchý plán jídelníčku a pohybu.\n"
        )
        prof = f"Profil uživatele: jméno={name}, věk={age}, výška_cm={height}, váha_kg={weight}, cíl={goal_txt}, aktivita={activity}.\n"
        return base + prof

    if lang == "en":
        goal_txt = goal_map_en.get(goal, goal or "")
        base = (
            "You are a friendly and smart dietitian. Keep answers concise and practical. "
            "Ask only if something is truly missing. "
            "You can suggest a simple nutrition and activity plan.\n"
        )
        prof = f"User profile: name={name}, age={age}, height_cm={height}, weight_kg={weight}, goal={goal_txt}, activity={activity}.\n"
        return base + prof

    # default ru
    goal_txt = goal_map_ru.get(goal, goal or "")
    base = (
        "Ты дружелюбный и умный диетолог. Отвечай коротко и по делу. "
        "Задавай вопросы только если реально не хватает данных. "
        "Можешь предложить простой план питания и активности.\n"
    )
    prof = f"Профиль пользователя: имя={name}, возраст={age}, рост_см={height}, вес_кг={weight}, цель={goal_txt}, активность={activity}.\n"
    return base + prof


async def chat_reply_with_history(user_id: int, user_text: str, user_language: str, profile: dict) -> str:
    """
    GPT reply with:
      - system prompt (profile)
      - last N messages from DB
      - current user message
    Then store both user+assistant messages in DB.
    """
    try:
        recent = []
        try:
            recent = await get_recent_messages(user_id, limit=20)
        except Exception as e:
            logger.error(f"get_recent_messages failed: {e}")

        system_prompt = build_system_prompt(user_language, profile)

        messages = [{"role": "system", "content": system_prompt}]
        # recent already like [{"role": "...", "content": "..."}]
        for m in recent:
            role = m.get("role")
            content = m.get("content")
            if role in ("user", "assistant") and isinstance(content, str) and content.strip():
                messages.append({"role": role, "content": content})

        messages.append({"role": "user", "content": user_text})

        resp = await openai_client.chat.completions.create(
            model=GPT_MODEL,
            messages=messages,
            max_tokens=450,
            temperature=0.7,
        )

        answer = (resp.choices[0].message.content or "").strip()

        # store history
        try:
            await add_message(user_id, "user", user_text)
            await add_message(user_id, "assistant", answer)
            await trim_messages(user_id, keep_last=60)
        except Exception as e:
            logger.error(f"store history failed: {e}")

        return answer

    except Exception as e:
        logger.error(f"Error in chat_reply_with_history: {e}")
        return _t(user_language, "error_general", "Что-то пошло не так. Попробуйте ещё раз.")


# -------------------- onboarding flow --------------------
async def get_stage(user_id: int) -> str:
    """
    stage stored in user_facts key='stage'
    Values: ask_goal, ask_profile, ask_activity, ready
    """
    try:
        s = await get_fact(user_id, "stage")
        if s:
            return str(s)
    except Exception:
        pass
    return ""


async def set_stage(user_id: int, stage: str) -> None:
    try:
        await set_fact(user_id, "stage", stage)
    except Exception as e:
        logger.error(f"set_stage failed: {e}")


def profile_missing(profile: dict) -> Tuple[bool, bool, bool, bool, bool]:
    """
    returns missing flags:
      goal, weight, height, age, activity
    """
    goal = not bool(profile.get("goal"))
    weight = profile.get("weight_kg") is None
    height = profile.get("height_cm") is None
    age = profile.get("age") is None
    activity = not bool(profile.get("activity"))
    return goal, weight, height, age, activity


async def ask_goal(message: Message, lang: str) -> None:
    txt = {
        "ru": "Отлично. Какая у вас цель: **похудеть**, **поддерживать вес** или **набрать**?",
        "cs": "Skvělé. Jaký je váš cíl: **zhubnout**, **udržet váhu**, nebo **přibrat**?",
        "en": "Great. What’s your goal: **lose weight**, **maintain**, or **gain**?",
    }.get(lang, "Какая цель: похудеть / поддерживать / набрать?")
    await message.answer(txt)


async def ask_profile(message: Message, lang: str) -> None:
    txt = {
        "ru": "Напишите одним сообщением: **вес (кг), рост (см), возраст**. Например: `вес 114 рост 182 возраст 49`",
        "cs": "Napište do jedné zprávy: **váha (kg), výška (cm), věk**. Např.: `váha 114 výška 182 věk 49`",
        "en": "Send in one message: **weight (kg), height (cm), age**. Example: `weight 114 height 182 age 49`",
    }.get(lang, "Вес/рост/возраст одним сообщением.")
    await message.answer(txt)


async def ask_activity(message: Message, lang: str) -> None:
    txt = {
        "ru": "Какая у вас физическая активность? (сидячая / средняя / высокая, или опишите кратко: шаги, тренировки, работа)",
        "cs": "Jaká je vaše fyzická aktivita? (sedavá / střední / vysoká, nebo krátce popište)",
        "en": "What’s your activity level? (low / moderate / high, or describe briefly)",
    }.get(lang, "Какая активность?")
    await message.answer(txt)


async def onboarding_router(message: Message, lang: str) -> Optional[str]:
    """
    Returns reply text if handled, else None to continue normal chat.
    """
    user_id = message.from_user.id

    profile = await get_user(user_id) or {}
    missing_goal, missing_weight, missing_height, missing_age, missing_activity = profile_missing(profile)

    stage = await get_stage(user_id)

    # If stage empty, derive from missing fields
    if not stage:
        if missing_goal:
            stage = "ask_goal"
            await set_stage(user_id, stage)
        elif missing_weight or missing_height or missing_age:
            stage = "ask_profile"
            await set_stage(user_id, stage)
        elif missing_activity:
            stage = "ask_activity"
            await set_stage(user_id, stage)
        else:
            stage = "ready"
            await set_stage(user_id, stage)

    text_raw = (message.text or "").strip()

    # Stage handlers
    if stage == "ask_goal":
        g = parse_goal(text_raw)
        if g:
            await upsert_user(user_id, goal=g)
            await set_stage(user_id, "ask_profile")
            await ask_profile(message, lang)
            return ""  # handled
        else:
            await ask_goal(message, lang)
            return ""

    if stage == "ask_profile":
        w, h, a = parse_profile_numbers(text_raw)
        # store what we have
        if w is not None:
            await upsert_user(user_id, weight_kg=float(w))
        if h is not None:
            await upsert_user(user_id, height_cm=int(h))
        if a is not None:
            await upsert_user(user_id, age=int(a))

        profile = await get_user(user_id) or {}
        missing_goal, missing_weight, missing_height, missing_age, missing_activity = profile_missing(profile)

        # ask only missing
        if missing_weight or missing_height or missing_age:
            parts = []
            if missing_weight:
                parts.append("вес (кг)" if lang == "ru" else ("váha (kg)" if lang == "cs" else "weight (kg)"))
            if missing_height:
                parts.append("рост (см)" if lang == "ru" else ("výška (cm)" if lang == "cs" else "height (cm)"))
            if missing_age:
                parts.append("возраст" if lang == "ru" else ("věk" if lang == "cs" else "age"))

            if lang == "cs":
                await message.answer("Не вижу: " + ", ".join(parts) + ". Napište prosím znovu.")
            elif lang == "en":
                await message.answer("I still need: " + ", ".join(parts) + ". Please send again.")
            else:
                await message.answer("Не вижу: " + ", ".join(parts) + ". Напишите ещё раз одним сообщением.")
            return ""

        # next stage
        await set_stage(user_id, "ask_activity")
        await ask_activity(message, lang)
        return ""

    if stage == "ask_activity":
        # store activity as text
        if text_raw:
            await upsert_user(user_id, activity=text_raw)
        await set_stage(user_id, "ready")

        profile = await get_user(user_id) or {}
        # final confirm
        if lang == "cs":
            msg = "Super, profil je hotový ✅ Teď mi můžete psát otázky nebo posílat fotky jídel."
        elif lang == "en":
            msg = "Great, your profile is saved ✅ Now ask me anything or send food photos."
        else:
            msg = "Отлично, анкету сохранила ✅ Теперь задавайте вопросы или присылайте фото еды."
        await message.answer(msg)
        return ""

    # ready -> not handled here
    return None


# -------------------- commands --------------------
@dp.message(Command("start"))
async def cmd_start(message: Message):
    user_language = _lang(message)
    await _ensure_user_row(message, user_language)

    user_id = message.from_user.id
    profile = await get_user(user_id) or {}

    # If profile incomplete -> start onboarding from where missing
    missing_goal, missing_weight, missing_height, missing_age, missing_activity = profile_missing(profile)

    # greet (use existing texts if present)
    await message.answer(_t(user_language, "welcome", "Привет! Я AI-диетолог. Помогу с питанием и подсчётом калорий."))

    if missing_goal:
        await set_stage(user_id, "ask_goal")
        await ask_goal(message, user_language)
        return

    if missing_weight or missing_height or missing_age:
        await set_stage(user_id, "ask_profile")
        await ask_profile(message, user_language)
        return

    if missing_activity:
        await set_stage(user_id, "ask_activity")
        await ask_activity(message, user_language)
        return

    await set_stage(user_id, "ready")


@dp.message(Command("help"))
async def cmd_help(message: Message):
    user_language = _lang(message)
    await message.answer(_t(user_language, "help", "Отправьте фото еды или напишите вопрос. Команда /start — начать заново."))


# -------------------- photo handler --------------------
@dp.message(F.photo)
async def handle_photo(message: Message):
    user_language = _lang(message)
    await _ensure_user_row(message, user_language)
    user_id = message.from_user.id

    # If onboarding not finished, politely ask to finish first
    stage = await get_stage(user_id)
    if stage and stage != "ready":
        # Let user finish onboarding first
        if stage == "ask_goal":
            await ask_goal(message, user_language)
        elif stage == "ask_profile":
            await ask_profile(message, user_language)
        elif stage == "ask_activity":
            await ask_activity(message, user_language)
        return

    try:
        status_msg = await message.answer(_t(user_language, "analyzing", "Анализирую фото..."))

        photo = message.photo[-1]
        photo_file = await bot.get_file(photo.file_id)
        photo_bytes = await bot.download_file(photo_file.file_path)

        result = await analyze_food_photo(photo_bytes.read(), user_language)

        await status_msg.delete()
        await message.answer(result)

        # store history: mark photo as user message
        try:
            await add_message(user_id, "user", "[PHOTO]")
            await add_message(user_id, "assistant", result)
            await trim_messages(user_id, keep_last=60)
        except Exception as e:
            logger.error(f"store photo history failed: {e}")

    except Exception as e:
        logger.error(f"Error handling photo: {e}")
        await message.answer(_t(user_language, "error_general", "Ошибка. Попробуйте ещё раз."))


# -------------------- text handler --------------------
@dp.message()
async def handle_text(message: Message):
    user_language = _lang(message)
    await _ensure_user_row(message, user_language)

    user_id = message.from_user.id
    text_raw = (message.text or "").strip()

    # greetings: simple response but still keep onboarding logic
    if is_greeting(text_raw):
        # If onboarding not ready, continue onboarding, else greeting text
        stage = await get_stage(user_id)
        if stage and stage != "ready":
            handled = await onboarding_router(message, user_language)
            if handled is not None:
                return
        await message.answer(_t(user_language, "greeting", "Привет! 😊 Я твой AI-диетолог. Какая у тебя цель?"))
        return

    # Onboarding first (prevents the "circle")
    handled = await onboarding_router(message, user_language)
    if handled is not None:
        return

    # Normal chat with memory
    profile = await get_user(user_id) or {}
    reply = await chat_reply_with_history(user_id, text_raw, user_language, profile)
    await message.answer(reply)


# -------------------- main --------------------
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
