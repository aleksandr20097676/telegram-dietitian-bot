#!/usr/bin/env python3
"""
Telegram Dietitian Bot - Photo Food Analysis + Onboarding memory (DB facts)
Aiogram v3
"""

import asyncio
import logging
import base64
import re
from typing import Dict, Optional, Tuple

import httpx
from openai import AsyncOpenAI

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message
from aiogram.fsm.storage.memory import MemoryStorage

# Import configuration
from config import TELEGRAM_TOKEN, OPENAI_API_KEY, GPT_MODEL
from database import FOOD_DATABASE
from languages import detect_language, get_text

# DB helpers
from db import (
    init_db,
    upsert_user,
    add_message,
    get_recent_messages,
    set_fact,
    set_facts,
    get_all_facts,
)

# -------------------- logging --------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# -------------------- clients --------------------
http_client = httpx.AsyncClient(timeout=60.0)
openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY, http_client=http_client)

bot = Bot(token=TELEGRAM_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

# -------------------- helpers --------------------
ONBOARDING_ORDER = ["name", "goal", "body", "activity", "job"]


def _normalize_text(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip()).lower()


def _extract_three_numbers(text: str) -> Optional[Tuple[int, int, int]]:
    """
    Accepts:
      "109, 182, 49"
      "109 182 49"
      "109/182/49"
      "вес 109 рост 182 возраст 49"  (тоже вытащит)
    Returns (w, h, a) if 3 numbers found and plausible.
    """
    nums = re.findall(r"\d{1,3}", text or "")
    if len(nums) < 3:
        return None

    # берем первые три (пользователь может дописать лишнее)
    w, h, a = map(int, nums[:3])

    # грубая валидация диапазонов
    if not (30 <= w <= 350):
        return None
    if not (100 <= h <= 250):
        return None
    if not (10 <= a <= 100):
        return None

    return w, h, a


def _parse_goal(text: str) -> Optional[str]:
    t = _normalize_text(text)
    if any(x in t for x in ["похуд", "сброс", "сниз", "потер"]):
        return "lose_weight"
    if any(x in t for x in ["набрать", "массу", "bulk"]):
        return "gain_muscle"
    if any(x in t for x in ["поддерж", "держать", "maintain"]):
        return "maintain"
    # иногда человек пишет просто "похудеть"
    if t in ["похудеть", "похуд", "сбросить"]:
        return "lose_weight"
    return None


def _goal_human(goal: str, lang: str) -> str:
    if lang == "cs":
        return {"lose_weight": "zhubnout", "gain_muscle": "nabrat svaly", "maintain": "udržet váhu"}.get(goal, goal)
    if lang == "en":
        return {"lose_weight": "lose weight", "gain_muscle": "gain muscle", "maintain": "maintain weight"}.get(goal, goal)
    return {"lose_weight": "похудеть", "gain_muscle": "набрать мышечную массу", "maintain": "поддерживать форму"}.get(goal, goal)


def _parse_activity_and_job(text: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Expected something like:
      "средняя, водитель"
      "низкая офис"
      "высокая, стройка"
    Returns (activity, job) where activity in {low, medium, high}
    """
    t = _normalize_text(text)

    activity = None
    if any(x in t for x in ["низк", "low"]):
        activity = "low"
    elif any(x in t for x in ["средн", "medium", "mid"]):
        activity = "medium"
    elif any(x in t for x in ["высок", "high"]):
        activity = "high"

    # job: убираем слова активности и знаки, оставляем остальное
    job = t
    job = re.sub(r"(низкая|низкий|низко|low|средняя|средний|средне|medium|высокая|высокий|высоко|high)", "", job)
    job = job.replace(",", " ").strip()
    job = re.sub(r"\s+", " ", job).strip()
    if job == "":
        job = None

    return activity, job


async def _get_facts_safe(user_id: int) -> Dict[str, str]:
    try:
        facts = await get_all_facts(user_id)
        return facts or {}
    except Exception as e:
        logger.error(f"get_all_facts failed: {e}")
        return {}


def _next_missing(facts: Dict[str, str]) -> Optional[str]:
    for k in ONBOARDING_ORDER:
        if not facts.get(k):
            return k
    return None


def _prompt_for_missing(missing: str, lang: str) -> str:
    # коротко и понятно
    if missing == "name":
        return "Как тебя зовут? Напиши, пожалуйста, только имя." if lang == "ru" else (
            "Jak se jmenuješ? Napiš prosím jen jméno." if lang == "cs" else "What’s your name? Please type just your first name."
        )

    if missing == "goal":
        return "Какая цель? (похудеть / поддерживать / набрать мышечную массу)" if lang == "ru" else (
            "Jaký je cíl? (zhubnout / udržet / nabrat svaly)" if lang == "cs" else "What’s your goal? (lose weight / maintain / gain muscle)"
        )

    if missing == "body":
        return "Напиши одним сообщением: вес, рост, возраст. Например: 109, 182, 49" if lang == "ru" else (
            "Napiš v jedné zprávě: váha, výška, věk. Např.: 109, 182, 49" if lang == "cs" else
            "Type in one message: weight, height, age. Example: 109, 182, 49"
        )

    if missing == "activity":
        return "Какая у тебя активность? (низкая / средняя / высокая)" if lang == "ru" else (
            "Jaká je tvoje aktivita? (nízká / střední / vysoká)" if lang == "cs" else
            "What’s your activity level? (low / medium / high)"
        )

    if missing == "job":
        return "Чем занимаешься (работа)? Например: водитель / офис / стройка" if lang == "ru" else (
            "Čím se živíš (práce)? Např.: řidič / kancelář / stavba" if lang == "cs" else
            "What do you do for work? (driver / office / construction)"
        )

    return "Напиши ответ, пожалуйста." if lang == "ru" else "Please reply."


async def analyze_food_photo(photo_bytes: bytes, user_language: str) -> str:
    """
    Analyze food photo using OpenAI Vision (chat.completions with image_url)
    """
    try:
        base64_image = base64.b64encode(photo_bytes).decode("utf-8")

        db_lines = []
        for food_name, food_data in FOOD_DATABASE.items():
            db_lines.append(
                f"- {food_name}: {food_data['calories']} kcal per {food_data['portion']}, "
                f"P {food_data['protein']}g, C {food_data['carbs']}g, F {food_data['fat']}g"
            )
        db_description = "\n".join(db_lines)

        # ЖЁСТКАЯ инструкция: анализируем ЕДУ, никаких людей/идентификаций
        if user_language == "cs":
            prompt = (
                "Jsi dietolog. Analyzuj fotku JÍDLA a odhadni porce.\n"
                "NEidentifikuj osoby. Zaměř se pouze na jídlo.\n\n"
                "Použij tuto databázi (pokud se hodí, vyber nejbližší položky):\n"
                f"{db_description}\n\n"
                "Výstup:\n"
                "1) Co je na talíři (odhad)\n"
                "2) Odhad porcí v gramech\n"
                "3) Kalorie + B/S/T (protein/sacharidy/tuky)\n"
                "4) Krátké doporučení (1–2 věty)\n"
            )
        elif user_language == "en":
            prompt = (
                "You are a dietitian. Analyze the FOOD in the photo and estimate portions.\n"
                "Do NOT identify people. Focus only on the meal.\n\n"
                "Use this database if relevant (pick closest items):\n"
                f"{db_description}\n\n"
                "Output:\n"
                "1) What’s on the plate (estimate)\n"
                "2) Portion estimate in grams\n"
                "3) Calories + P/C/F\n"
                "4) Short recommendation (1–2 sentences)\n"
            )
        else:
            prompt = (
                "Ты диетолог. Проанализируй ЕДУ на фото и оцени порции.\n"
                "НЕ идентифицируй людей. Фокус только на блюде.\n\n"
                "Используй базу продуктов (если подходит — подбери ближайшие позиции):\n"
                f"{db_description}\n\n"
                "Вывод:\n"
                "1) Что на тарелке (оценка)\n"
                "2) Оценка порций в граммах\n"
                "3) Калории + Б/Ж/У\n"
                "4) Короткая рекомендация (1–2 предложения)\n"
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
                            "image_url": {"url": f"data:image/jpeg;base64,{base64_image}", "detail": "high"},
                        },
                    ],
                }
            ],
            max_tokens=900,
            temperature=0.4,
        )

        return (response.choices[0].message.content or "").strip() or get_text(user_language, "error_analysis")

    except Exception as e:
        logger.error(f"Error analyzing photo: {e}")
        return get_text(user_language, "error_analysis")


async def chat_reply(user_text: str, user_language: str, facts: Dict[str, str], history: list) -> str:
    """
    Chat reply with memory (facts) + short history.
    """
    try:
        name = facts.get("name")
        goal = facts.get("goal")
        w = facts.get("weight")
        h = facts.get("height")
        a = facts.get("age")
        activity = facts.get("activity")
        job = facts.get("job")

        profile_line = f"Имя: {name or '-'}, цель: {_goal_human(goal, 'ru') if goal else '-'}, вес: {w or '-'}, рост: {h or '-'}, возраст: {a or '-'}, активность: {activity or '-'}, работа: {job or '-'}"
        if user_language == "cs":
            profile_line = f"Jméno: {name or '-'}, cíl: {_goal_human(goal, 'cs') if goal else '-'}, váha: {w or '-'}, výška: {h or '-'}, věk: {a or '-'}, aktivita: {activity or '-'}, práce: {job or '-'}"
        if user_language == "en":
            profile_line = f"Name: {name or '-'}, goal: {_goal_human(goal, 'en') if goal else '-'}, weight: {w or '-'}, height: {h or '-'}, age: {a or '-'}, activity: {activity or '-'}, job: {job or '-'}"

        system_prompt_ru = (
            "Ты дружелюбный и умный диетолог.\n"
            "Отвечай коротко и по делу. 1–2 уточняющих вопроса максимум.\n"
            "Учитывай профиль пользователя и историю диалога.\n"
            "Если вопрос про еду — предлагай оценку порции и калории, "
            "а при необходимости — предложи прислать фото.\n\n"
            f"ПРОФИЛЬ:\n{profile_line}\n"
        )
        system_prompt_cs = (
            "Jsi přátelský a chytrý dietolog.\n"
            "Odpovídej stručně a věcně, max 1–2 doplňující otázky.\n"
            "Používej profil uživatele a krátkou historii.\n"
            "Když jde o jídlo, navrhni odhad porce a kalorie, a když je potřeba, nabídni fotku.\n\n"
            f"PROFIL:\n{profile_line}\n"
        )
        system_prompt_en = (
            "You are a friendly and smart dietitian.\n"
            "Be concise and useful. Ask at most 1–2 clarifying questions.\n"
            "Use the user profile and short chat history.\n"
            "If it’s about food, estimate portions and calories; if needed, suggest sending a photo.\n\n"
            f"PROFILE:\n{profile_line}\n"
        )

        system_prompt = system_prompt_ru
        if user_language == "cs":
            system_prompt = system_prompt_cs
        elif user_language == "en":
            system_prompt = system_prompt_en

        msgs = [{"role": "system", "content": system_prompt}]

        # история в формате [{"role": "...", "content": "..."}]
        for m in history[-10:]:
            r = m.get("role")
            c = m.get("content")
            if r in ("user", "assistant") and c:
                msgs.append({"role": r, "content": c})

        msgs.append({"role": "user", "content": user_text})

        resp = await openai_client.chat.completions.create(
            model=GPT_MODEL,
            messages=msgs,
            max_tokens=450,
            temperature=0.6,
        )

        return (resp.choices[0].message.content or "").strip() or get_text(user_language, "error_general")

    except Exception as e:
        logger.error(f"Error in chat_reply: {e}")
        return get_text(user_language, "error_general")


async def _ensure_user_in_db(message: Message, user_language: str):
    """
    Creates/updates user row (not facts).
    """
    try:
        await upsert_user(
            user_id=message.from_user.id,
            username=message.from_user.username,
            first_name=message.from_user.first_name,
            language=user_language,
        )
    except Exception as e:
        logger.error(f"upsert_user failed: {e}")


# -------------------- handlers --------------------
@dp.message(Command("start"))
async def cmd_start(message: Message):
    user_language = detect_language(message.from_user.language_code)
    await _ensure_user_in_db(message, user_language)

    facts = await _get_facts_safe(message.from_user.id)
    missing = _next_missing(facts)

    if missing:
        await message.answer(get_text(user_language, "welcome"))
        await message.answer(_prompt_for_missing(missing, user_language))
    else:
        # уже всё заполнено
        await message.answer(get_text(user_language, "welcome"))


@dp.message(Command("help"))
async def cmd_help(message: Message):
    user_language = detect_language(message.from_user.language_code)
    await message.answer(get_text(user_language, "help"))


@dp.message(F.photo)
async def handle_photo(message: Message):
    user_language = detect_language(message.from_user.language_code)
    await _ensure_user_in_db(message, user_language)

    try:
        status_msg = await message.answer(get_text(user_language, "analyzing"))

        photo = message.photo[-1]
        photo_file = await bot.get_file(photo.file_id)
        photo_bytes = await bot.download_file(photo_file.file_path)

        result = await analyze_food_photo(photo_bytes.read(), user_language)

        await status_msg.delete()
        await message.answer(result)

        # сохраняем историю
        await add_message(message.from_user.id, "user", "[photo]")
        await add_message(message.from_user.id, "assistant", result)

    except Exception as e:
        logger.error(f"Error handling photo: {e}")
        await message.answer(get_text(user_language, "error_general"))


@dp.message()
async def handle_text(message: Message):
    user_language = detect_language(message.from_user.language_code)
    await _ensure_user_in_db(message, user_language)

    user_id = message.from_user.id
    text_raw = (message.text or "").strip()

    # сохраняем входящее в историю
    try:
        await add_message(user_id, "user", text_raw)
    except Exception as e:
        logger.error(f"add_message(user) failed: {e}")

    facts = await _get_facts_safe(user_id)
    missing = _next_missing(facts)

    # 1) Онбординг (только пока не заполнено)
    if missing == "name":
        # простая логика: берем первое слово как имя
        name = text_raw.strip().split()[0][:40]
        await set_fact(user_id, "name", name)
        facts["name"] = name

        missing = _next_missing(facts)
        await message.answer(_prompt_for_missing(missing, user_language))
        return

    if missing == "goal":
        goal = _parse_goal(text_raw)
        if not goal:
            await message.answer(_prompt_for_missing("goal", user_language))
            return
        await set_fact(user_id, "goal", goal)
        facts["goal"] = goal

        missing = _next_missing(facts)
        await message.answer(_prompt_for_missing(missing, user_language))
        return

    if missing == "body":
        triple = _extract_three_numbers(text_raw)
        if not triple:
            await message.answer(_prompt_for_missing("body", user_language))
            return

        w, h, a = triple
        await set_facts(
            user_id,
            {"weight": str(w), "height": str(h), "age": str(a)},
        )
        facts["weight"], facts["height"], facts["age"] = str(w), str(h), str(a)

        missing = _next_missing(facts)
        await message.answer(_prompt_for_missing(missing, user_language))
        return

    if missing == "activity":
        act, job = _parse_activity_and_job(text_raw)
        if not act:
            await message.answer(_prompt_for_missing("activity", user_language))
            return
        await set_fact(user_id, "activity", act)
        facts["activity"] = act

        # если в этом же сообщении человек написал работу — сохраним сразу
        if job and not facts.get("job"):
            await set_fact(user_id, "job", job)
            facts["job"] = job

        missing = _next_missing(facts)
        if missing:
            await message.answer(_prompt_for_missing(missing, user_language))
        else:
            await message.answer(
                "Отлично. Теперь напиши, что нужно (план питания/калории/рацион), или пришли фото еды."
                if user_language == "ru" else
                ("Skvěle. Napiš, co potřebuješ (plán/kalorie/jídelníček), nebo pošli fotku jídla."
                 if user_language == "cs" else
                 "Great. Tell me what you need (meal plan/calories/diet), or send a food photo.")
            )
        return

    if missing == "job":
        job = _normalize_text(text_raw)
        if len(job) < 2:
            await message.answer(_prompt_for_missing("job", user_language))
            return
        await set_fact(user_id, "job", job)
        facts["job"] = job

        missing = _next_missing(facts)
        if missing:
            await message.answer(_prompt_for_missing(missing, user_language))
        else:
            await message.answer(
                "Отлично. Теперь напиши, что нужно (план питания/калории/рацион), или пришли фото еды."
                if user_language == "ru" else
                ("Skvěle. Napiš, co potřebuješ (plán/kalorie/jídelníček), nebo pošli fotku jídla."
                 if user_language == "cs" else
                 "Great. Tell me what you need (meal plan/calories/diet), or send a food photo.")
            )
        return

    # 2) Если онбординг завершён — обычный чат
    try:
        history = await get_recent_messages(user_id, limit=20)
    except Exception as e:
        logger.error(f"get_recent_messages failed: {e}")
        history = []

    reply = await chat_reply(text_raw, user_language, facts, history)
    await message.answer(reply)

    try:
        await add_message(user_id, "assistant", reply)
    except Exception as e:
        logger.error(f"add_message(assistant) failed: {e}")


# -------------------- main --------------------
async def main():
    logger.info("Starting Telegram Dietitian Bot...")
    logger.info(f"Using model: {GPT_MODEL}")

    await init_db()

    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()
        await http_client.aclose()


if __name__ == "__main__":
    asyncio.run(main())

