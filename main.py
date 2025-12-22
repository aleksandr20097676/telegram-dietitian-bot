#!/usr/bin/env python3
"""
Telegram Dietitian Bot - УЛУЧШЕННАЯ ВЕРСИЯ
✅ Красивые inline кнопки
✅ Главное меню внизу экрана
✅ Карточки с результатами
✅ Приветствие и представление
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
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from config import TELEGRAM_TOKEN, OPENAI_API_KEY, GPT_MODEL
from database import FOOD_DATABASE
from languages import detect_language, get_text
from db import init_db, ensure_user_exists, set_fact, set_facts, get_fact


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
    waiting_whA = State()
    waiting_activity = State()

class WeightTracking(StatesGroup):
    waiting_weight = State()


# -------------------- helpers --------------------
def normalize_text(s: str) -> str:
    return (s or "").strip()


def parse_weight_height_age(text: str) -> Optional[Tuple[int, int, int]]:
    """Parse weight, height, age from text"""
    t = normalize_text(text)
    nums = re.findall(r"\d{1,3}", t)
    if len(nums) < 3:
        return None

    w = int(nums[0])
    h = int(nums[1])
    a = int(nums[2])

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
    """Returns prompt for missing data or None if complete"""
    name = await get_fact(user_id, "name")
    goal = await get_fact(user_id, "goal")
    weight = await get_fact(user_id, "weight_kg")
    height = await get_fact(user_id, "height_cm")
    age = await get_fact(user_id, "age")
    activity = await get_fact(user_id, "activity")

    if not name:
        return "name"
    if not goal:
        return "goal"
    if not (weight and height and age):
        return "wha"
    if not activity:
        return "activity"
    return None


def create_main_menu() -> ReplyKeyboardMarkup:
    """Создаёт главное меню внизу экрана"""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📸 Фото еды"), KeyboardButton(text="💬 Вопрос")],
            [KeyboardButton(text="📋 План питания"), KeyboardButton(text="💪 Тренировки")],
            [KeyboardButton(text="⚖️ Взвеситься"), KeyboardButton(text="📊 Мой прогресс")],
            [KeyboardButton(text="⚙️ Настройки")]
        ],
        resize_keyboard=True
    )


def format_food_card(food_name: str, calories: int, protein: float, fat: float, carbs: float, weight: int = 100) -> str:
    """Форматирует красивую карточку с результатами анализа"""
    card = (
        "╔═══════════════════════════╗\n"
        "║   📊 АНАЛИЗ БЛЮДА        ║\n"
        "╠═══════════════════════════╣\n"
        f"║ 🍽 {food_name}\n"
        f"║ ⚖️ Порция: ~{weight}г\n"
        "║                           ║\n"
        f"║ 🔥 Калории: {calories} ккал\n"
        f"║ 🥩 Белки: {protein}г\n"
        f"║ 🧈 Жиры: {fat}г\n"
        f"║ 🍞 Углеводы: {carbs}г\n"
        "╚═══════════════════════════╝"
    )
    return card


async def analyze_food_photo(photo_bytes: bytes, user_language: str) -> str:
    """Vision analysis for food photo with beautiful card"""
    try:
        base64_image = base64.b64encode(photo_bytes).decode("utf-8")

        db_description = "Примеры из базы продуктов:\n"
        count = 0
        for food_name, food_data in FOOD_DATABASE.items():
            if count >= 15:
                break
            db_description += (
                f"- {food_name}: {food_data['calories']} ккал/{food_data['portion']}, "
                f"Б:{food_data['protein']}г Ж:{food_data['fat']}г У:{food_data['carbs']}г\n"
            )
            count += 1

        system_prompt = (
            "Ты опытный диетолог-нутрициолог. Анализируй еду на фото.\n\n"
            "ФОРМАТ ОТВЕТА:\n"
            "1. Название блюда (одно слово или фраза)\n"
            "2. Вес порции в граммах\n"
            "3. Калории (только число)\n"
            "4. Белки в граммах (только число)\n"
            "5. Жиры в граммах (только число)\n"
            "6. Углеводы в граммах (только число)\n"
            "7. Краткий комментарий (1-2 предложения)\n\n"
            "Если на фото нет еды - сразу скажи что это не еда."
        )

        user_prompt = (
            f"{db_description}\n\n"
            "Проанализируй фото и ответь СТРОГО в формате:\n"
            "БЛЮДО: название\n"
            "ВЕС: число\n"
            "КАЛОРИИ: число\n"
            "БЕЛКИ: число\n"
            "ЖИРЫ: число\n"
            "УГЛЕВОДЫ: число\n"
            "КОММЕНТАРИЙ: текст"
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

        # Парсим ответ и создаём красивую карточку
        lines = result.split('\n')
        food_name = "Блюдо"
        weight = 100
        calories = 0
        protein = 0.0
        fat = 0.0
        carbs = 0.0
        comment = ""
        
        for line in lines:
            line_lower = line.lower()
            if 'блюдо:' in line_lower or 'dish:' in line_lower:
                food_name = line.split(':', 1)[1].strip()
            elif 'вес:' in line_lower or 'weight:' in line_lower:
                nums = re.findall(r'\d+', line)
                if nums:
                    weight = int(nums[0])
            elif 'калор' in line_lower or 'calor' in line_lower:
                nums = re.findall(r'\d+', line)
                if nums:
                    calories = int(nums[0])
            elif 'белк' in line_lower or 'protein' in line_lower:
                nums = re.findall(r'\d+\.?\d*', line)
                if nums:
                    protein = float(nums[0])
            elif 'жир' in line_lower or 'fat' in line_lower:
                nums = re.findall(r'\d+\.?\d*', line)
                if nums:
                    fat = float(nums[0])
            elif 'углевод' in line_lower or 'carb' in line_lower:
                nums = re.findall(r'\d+\.?\d*', line)
                if nums:
                    carbs = float(nums[0])
            elif 'комментарий:' in line_lower or 'comment:' in line_lower:
                comment = line.split(':', 1)[1].strip()
        
        # Создаём красивую карточку
        card = format_food_card(food_name, calories, protein, fat, carbs, weight)
        
        # Добавляем комментарий если есть
        if comment:
            card += f"\n\n💡 {comment}"
        
        return card

    except Exception as e:
        logger.error(f"Error analyzing photo: {e}", exc_info=True)
        return (
            "Произошла ошибка при анализе фото 😔\n"
            "Попробуй ещё раз или опиши блюдо словами - я посчитаю калории!"
        )


async def chat_reply(user_text: str, user_language: str, user_id: int) -> str:
    """Normal chat reply with user profile context"""
    try:
        name = await get_fact(user_id, "name") or ""
        goal = await get_fact(user_id, "goal") or ""
        weight = await get_fact(user_id, "weight_kg") or ""
        height = await get_fact(user_id, "height_cm") or ""
        age = await get_fact(user_id, "age") or ""
        activity = await get_fact(user_id, "activity") or ""
        job = await get_fact(user_id, "job") or ""

        profile = (
            f"Профиль: имя={name}, цель={goal}, "
            f"вес={weight}кг, рост={height}см, возраст={age}, "
            f"активность={activity}, работа={job}."
        )

        system_ru = (
            "Ты дружелюбный AI-диетолог.\n"
            "Стиль: короткие ответы (2-4 предложения), один вопрос максимум.\n"
            f"{profile}"
        )

        resp = await openai_client.chat.completions.create(
            model=GPT_MODEL,
            messages=[
                {"role": "system", "content": system_ru},
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
    """✅ Улучшенное приветствие с главным меню"""
    user_id = message.from_user.id
    await state.clear()

    user_language = detect_language(message.from_user.language_code)
    missing = await profile_missing(user_id)
    
    if missing is None:
        # Профиль заполнен - показываем главное меню
        name = await get_fact(user_id, "name") or "друг"
        menu = create_main_menu()
        
        await message.answer(
            f"С возвращением, {name}! 😊\n"
            f"Я готов помочь тебе с питанием. Чем займёмся сегодня?",
            reply_markup=menu
        )
        return

    # Профиль не заполнен - ПРИВЕТСТВИЕ без кнопок
    greeting = (
        "👋 Привет! Я твой AI-диетолог.\n\n"
        "🎯 Что я умею:\n"
        "• Анализировать фото еды и считать калории 📸\n"
        "• Составлять персональные планы питания 📋\n"
        "• Подбирать программы тренировок 💪\n"
        "• Создавать режим дня под твои цели ⏰\n"
        "• Помогать достичь желаемого веса 🎯\n\n"
        "Давай познакомимся и составим твой идеальный план! 😊"
    )
    
    await message.answer(greeting, reply_markup=ReplyKeyboardRemove())
    await asyncio.sleep(1.5)
    await message.answer("Как тебя зовут? Напиши, пожалуйста, только имя.")
    await state.set_state(Onboarding.waiting_name)


@dp.message(Command("help"))
async def cmd_help(message: Message):
    """Help command"""
    await message.answer(
        "📋 Команды:\n"
        "/start — начать или продолжить\n"
        "reset — сбросить анкету\n\n"
        "💬 Можно:\n"
        "• Задавать вопросы про питание\n"
        "• Присылать фото еды для анализа 📸\n"
        "• Присылать голосовые сообщения 🎤\n"
        "• Просить план питания или тренировок"
    )


# -------------------- onboarding: name --------------------
@dp.message(Onboarding.waiting_name, F.text)
async def onboarding_name(message: Message, state: FSMContext):
    """Collect user name"""
    if is_reset_command(message.text):
        user_id = message.from_user.id
        await ensure_user_exists(user_id)
        await set_facts(user_id, {
            "name": "", "goal": "", "weight_kg": "",
            "height_cm": "", "age": "", "activity": "", "job": "",
        })
        await state.clear()
        await message.answer("✅ Анкету сбросил! Напиши /start чтобы пройти заново.")
        return
    
    user_id = message.from_user.id
    await ensure_user_exists(user_id)
    name = normalize_text(message.text)
    
    if len(name) < 2 or len(name) > 30:
        await message.answer("Напиши, пожалуйста, только имя (2–30 символов).")
        return

    await set_fact(user_id, "name", name)
    
    # ✅ INLINE КНОПКИ для выбора цели
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🏃 Похудеть", callback_data="goal_lose"),
            InlineKeyboardButton(text="💪 Набрать", callback_data="goal_gain"),
        ],
        [
            InlineKeyboardButton(text="⚖️ Поддерживать", callback_data="goal_maintain")
        ]
    ])
    
    await message.answer(
        f"Отлично, {name}! Какая у тебя цель?",
        reply_markup=keyboard
    )
    await state.set_state(Onboarding.waiting_goal)


# -------------------- onboarding: goal (callback) --------------------
@dp.callback_query(Onboarding.waiting_goal)
async def onboarding_goal_callback(callback: Message, state: FSMContext):
    """Handle goal selection from inline buttons"""
    user_id = callback.from_user.id
    
    goal_map = {
        "goal_lose": "похудеть",
        "goal_gain": "набрать массу",
        "goal_maintain": "поддерживать"
    }
    
    goal = goal_map.get(callback.data, "поддерживать")
    await set_fact(user_id, "goal", goal)
    
    # Убираем кнопки
    await callback.message.edit_reply_markup(reply_markup=None)
    
    await callback.answer()
    await callback.message.answer(
        "Супер! Отличная цель! 🎯\n\n"
        "Теперь расскажи мне о себе:\n"
        "Напиши одним сообщением: вес (кг), рост (см), возраст\n\n"
        "Например: 114, 182, 49"
    )
    await state.set_state(Onboarding.waiting_whA)


# -------------------- onboarding: goal (text fallback) --------------------
@dp.message(Onboarding.waiting_goal, F.text)
async def onboarding_goal_text(message: Message, state: FSMContext):
    """Handle goal if user writes text instead of clicking button"""
    if is_reset_command(message.text):
        user_id = message.from_user.id
        await set_facts(user_id, {
            "name": "", "goal": "", "weight_kg": "",
            "height_cm": "", "age": "", "activity": "", "job": "",
        })
        await state.clear()
        await message.answer("✅ Анкету сбросил! Напиши /start чтобы пройти заново.")
        return
    
    user_id = message.from_user.id
    goal = normalize_text(message.text).lower()

    if "пох" in goal or "lose" in goal or goal == "1":
        goal_norm = "похудеть"
    elif "удерж" in goal or "maintain" in goal or goal == "3":
        goal_norm = "поддерживать"
    elif "наб" in goal or "gain" in goal or "мыш" in goal or goal == "2":
        goal_norm = "набрать массу"
    else:
        goal_norm = normalize_text(message.text)

    await set_fact(user_id, "goal", goal_norm)

    await message.answer(
        "Супер! Отличная цель! 🎯\n\n"
        "Теперь расскажи мне о себе:\n"
        "Напиши одним сообщением: вес (кг), рост (см), возраст\n\n"
        "Например: 114, 182, 49"
    )
    await state.set_state(Onboarding.waiting_whA)


# -------------------- onboarding: weight/height/age --------------------
@dp.message(Onboarding.waiting_whA, F.text)
async def onboarding_wha(message: Message, state: FSMContext):
    """Collect weight, height, age"""
    if is_reset_command(message.text):
        user_id = message.from_user.id
        await set_facts(user_id, {
            "name": "", "goal": "", "weight_kg": "",
            "height_cm": "", "age": "", "activity": "", "job": "",
        })
        await state.clear()
        await message.answer("✅ Анкету сбросил! Напиши /start чтобы пройти заново.")
        return
    
    user_id = message.from_user.id
    parsed = parse_weight_height_age(message.text)
    
    if parsed is None:
        await message.answer("Не вижу все данные. Напиши ещё раз одним сообщением: вес, рост, возраст.")
        return

    w, h, a = parsed
    await set_facts(user_id, {
        "weight_kg": str(w),
        "height_cm": str(h),
        "age": str(a),
    })

    # ✅ INLINE КНОПКИ для выбора активности
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🛋 Низкая", callback_data="activity_low"),
            InlineKeyboardButton(text="🚶 Средняя", callback_data="activity_medium"),
        ],
        [
            InlineKeyboardButton(text="🏃 Высокая", callback_data="activity_high")
        ]
    ])
    
    await message.answer(
        "Отлично! Последний вопрос:\n\n"
        "Какая у тебя физическая активность?",
        reply_markup=keyboard
    )
    await state.set_state(Onboarding.waiting_activity)


# -------------------- onboarding: activity (callback) --------------------
@dp.callback_query(Onboarding.waiting_activity)
async def onboarding_activity_callback(callback: Message, state: FSMContext):
    """Handle activity selection from inline buttons"""
    user_id = callback.from_user.id
    
    activity_map = {
        "activity_low": "низкая",
        "activity_medium": "средняя",
        "activity_high": "высокая"
    }
    
    activity = activity_map.get(callback.data, "средняя")
    await set_facts(user_id, {"activity": activity, "job": ""})
    
    # Убираем кнопки
    await callback.message.edit_reply_markup(reply_markup=None)
    
    await state.clear()
    
    # Показываем главное меню
    menu = create_main_menu()
    
    await callback.answer()
    await callback.message.answer(
        "Отлично! Теперь я знаю о тебе всё необходимое! 🎉\n\n"
        "Что могу для тебя сделать:\n"
        "📸 Пришли фото еды - я посчитаю калории\n"
        "💬 Задай вопрос о питании\n"
        "📋 Попроси составить план питания\n"
        "💪 Подберу программу тренировок\n\n"
        "С чего начнём?",
        reply_markup=menu
    )


# -------------------- onboarding: activity (text fallback) --------------------
@dp.message(Onboarding.waiting_activity, F.text)
async def onboarding_activity_text(message: Message, state: FSMContext):
    """Handle activity if user writes text instead of clicking button"""
    if is_reset_command(message.text):
        user_id = message.from_user.id
        await set_facts(user_id, {
            "name": "", "goal": "", "weight_kg": "",
            "height_cm": "", "age": "", "activity": "", "job": "",
        })
        await state.clear()
        await message.answer("✅ Анкету сбросил! Напиши /start чтобы пройти заново.")
        return
    
    user_id = message.from_user.id
    text = normalize_text(message.text)
    t = text.lower()
    
    activity = ""
    job = ""
    
    if "низ" in t or "low" in t:
        activity = "низкая"
    elif "сред" in t or "moderate" in t:
        activity = "средняя"
    elif "выс" in t or "high" in t:
        activity = "высокая"
    
    if "," in text:
        parts = text.split(",", 1)
        if not activity:
            activity = parts[0].strip()
        job = parts[1].strip()
    else:
        job_match = re.sub(r'(низкая|средняя|высокая|low|moderate|high)', '', t, flags=re.IGNORECASE).strip()
        job = job_match if job_match else ""
        if not activity:
            activity = text.split()[0] if text.split() else "средняя"

    await set_facts(user_id, {
        "activity": activity or "средняя",
        "job": job,
    })

    await state.clear()
    
    # Показываем главное меню
    menu = create_main_menu()
    
    await message.answer(
        "Отлично! Теперь я знаю о тебе всё необходимое! 🎉\n\n"
        "Что могу для тебя сделать:\n"
        "📸 Пришли фото еды - я посчитаю калории\n"
        "💬 Задай вопрос о питании\n"
        "📋 Попроси составить план питания\n"
        "💪 Подберу программу тренировок\n\n"
        "С чего начнём?",
        reply_markup=menu
    )


# -------------------- voice handler --------------------
@dp.message(F.voice)
async def handle_voice(message: Message, state: FSMContext):
    """Handle voice messages with Whisper API"""
    user_language = detect_language(message.from_user.language_code)
    user_id = message.from_user.id
    
    status_msg = await message.answer("🎤 Слушаю...")

    try:
        voice = message.voice
        file = await bot.get_file(voice.file_id)
        
        buf = BytesIO()
        await bot.download_file(file.file_path, destination=buf)
        
        buf.seek(0)
        buf.name = "voice.ogg"
        
        transcription = await openai_client.audio.transcriptions.create(
            model="whisper-1",
            file=buf,
            language="ru"
        )
        
        recognized_text = transcription.text.strip()
        
        await status_msg.delete()
        
        if not recognized_text:
            await message.answer("Не удалось распознать речь. Попробуй ещё раз 🙂")
            return
        
        await message.answer(f"📝 Распознал: \"{recognized_text}\"")
        
        # Process as text - check for reset
        if is_reset_command(recognized_text):
            await set_facts(user_id, {
                "name": "", "goal": "", "weight_kg": "",
                "height_cm": "", "age": "", "activity": "", "job": "",
            })
            await state.clear()
            await message.answer("✅ Анкету сбросил! Напиши /start чтобы пройти заново.")
            return
        
        # Check if in onboarding
        current_state = await state.get_state()
        if current_state == Onboarding.waiting_name.state:
            name = normalize_text(recognized_text)
            if len(name) < 2 or len(name) > 30:
                await message.answer("Напиши, пожалуйста, только имя (2–30 символов).")
                return
            await set_fact(user_id, "name", name)
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [
                    InlineKeyboardButton(text="🏃 Похудеть", callback_data="goal_lose"),
                    InlineKeyboardButton(text="💪 Набрать", callback_data="goal_gain"),
                ],
                [
                    InlineKeyboardButton(text="⚖️ Поддерживать", callback_data="goal_maintain")
                ]
            ])
            await message.answer(f"Отлично, {name}! Какая у тебя цель?", reply_markup=keyboard)
            await state.set_state(Onboarding.waiting_goal)
            return
        
        # Not in onboarding - check profile
        missing = await profile_missing(user_id)
        if missing is not None:
            await message.answer("Сначала давай познакомимся! Напиши /start")
            return
        
        # Quick greetings
        low = recognized_text.lower()
        if any(x in low for x in ["привет", "здрав", "hello", "hi"]):
            name = await get_fact(user_id, "name") or "друг"
            await message.answer(f"Привет, {name}! 😊 Чем помочь?")
            return
        
        # Normal chat
        reply = await chat_reply(recognized_text, user_language, user_id)
        await message.answer(reply)
        
    except Exception as e:
        logger.error(f"Error handling voice: {e}", exc_info=True)
        try:
            await status_msg.delete()
        except:
            pass
        await message.answer("Не смог обработать голосовое 😔 Попробуй ещё раз!")


# -------------------- photo handler --------------------
@dp.message(F.photo)
async def handle_photo(message: Message, state: FSMContext):
    """Handle photo messages - analyze food with beautiful card"""
    user_language = detect_language(message.from_user.language_code)
    user_id = message.from_user.id

    # Check if onboarding complete
    missing = await profile_missing(user_id)
    if missing is not None:
        await message.answer("Сначала давай познакомимся! 🙂 Напиши /start")
        return

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
        await message.answer("Не смог обработать фото 😔 Попробуй ещё раз!")


# -------------------- menu button handlers --------------------
@dp.message(F.text.in_(["📸 Фото еды"]))
async def menu_photo(message: Message):
    """Handle photo button from menu"""
    await message.answer(
        "📸 Отлично! Сфотографируй свою еду и пришли мне.\n"
        "Я проанализирую и посчитаю калории, БЖУ."
    )


@dp.message(F.text.in_(["💬 Вопрос"]))
async def menu_question(message: Message):
    """Handle question button from menu"""
    await message.answer(
        "💬 Задавай любой вопрос о питании!\n"
        "Можешь писать текстом или голосовым сообщением 🎤"
    )


@dp.message(F.text.in_(["📋 План питания"]))
async def menu_meal_plan(message: Message):
    """Handle meal plan button from menu"""
    user_id = message.from_user.id
    name = await get_fact(user_id, "name") or "друг"
    goal = await get_fact(user_id, "goal") or "поддерживать вес"
    
    await message.answer(
        f"{name}, составляю персональный план питания для твоей цели: {goal}...\n"
        "Это займёт пару секунд ⏳"
    )
    
    # Генерируем план через GPT
    reply = await chat_reply(
        f"Составь мне план питания на день с учётом моей цели: {goal}. "
        "Распиши завтрак, обед, ужин и перекусы.",
        "ru",
        user_id
    )
    
    await message.answer(f"📋 Твой план питания:\n\n{reply}")


@dp.message(F.text.in_(["💪 Тренировки"]))
async def menu_workout(message: Message):
    """Handle workout button from menu"""
    user_id = message.from_user.id
    name = await get_fact(user_id, "name") or "друг"
    goal = await get_fact(user_id, "goal") or "поддерживать форму"
    activity = await get_fact(user_id, "activity") or "средняя"
    
    await message.answer(
        f"{name}, подбираю программу тренировок для твоей цели: {goal}...\n"
        "Учитываю твою активность ⏳"
    )
    
    # Генерируем программу через GPT
    reply = await chat_reply(
        f"Составь мне программу тренировок на неделю. "
        f"Моя цель: {goal}. Активность: {activity}. "
        "Распиши упражнения по дням.",
        "ru",
        user_id
    )
    
    await message.answer(f"💪 Твоя программа тренировок:\n\n{reply}")


@dp.message(F.text.in_(["📊 Мой прогресс"]))
async def menu_progress(message: Message):
    """Handle progress button from menu - show weight history"""
    user_id = message.from_user.id
    name = await get_fact(user_id, "name") or "друг"
    current_weight = await get_fact(user_id, "weight_kg") or "?"
    goal = await get_fact(user_id, "goal") or "?"
    
    # Получаем историю взвешиваний
    import json
    weight_history_str = await get_fact(user_id, "weight_history")
    
    if not weight_history_str:
        # Нет истории - показываем базовую инфу
        progress = (
            f"📊 Твой прогресс, {name}:\n\n"
            f"⚖️ Текущий вес: {current_weight} кг\n"
            f"🎯 Цель: {goal}\n\n"
            "💡 Нажми '⚖️ Взвеситься' чтобы начать отслеживать прогресс!"
        )
        await message.answer(progress)
        return
    
    try:
        # Парсим историю
        history = json.loads(weight_history_str)
        
        if not history or len(history) == 0:
            progress = (
                f"📊 Твой прогресс, {name}:\n\n"
                f"⚖️ Текущий вес: {current_weight} кг\n"
                f"🎯 Цель: {goal}\n\n"
                "💡 Нажми '⚖️ Взвеситься' чтобы начать отслеживать прогресс!"
            )
            await message.answer(progress)
            return
        
        # Сортируем по дате
        history.sort(key=lambda x: x['date'])
        
        # Формируем красивый прогресс
        first_weight = history[0]['weight']
        last_weight = history[-1]['weight']
        total_diff = first_weight - last_weight
        
        progress_text = f"📊 Твой прогресс, {name}:\n\n"
        
        # Показываем последние 5 взвешиваний
        recent = history[-5:] if len(history) > 5 else history
        
        for i, entry in enumerate(recent):
            date = entry['date']
            weight = entry['weight']
            
            # Вычисляем разницу с предыдущим
            if i > 0:
                prev_weight = recent[i-1]['weight']
                diff = prev_weight - weight
                if diff > 0:
                    diff_str = f"⬇️ -{diff:.1f}кг"
                elif diff < 0:
                    diff_str = f"⬆️ +{abs(diff):.1f}кг"
                else:
                    diff_str = "="
            else:
                diff_str = "старт"
            
            progress_text += f"{date}  ●━━  {weight} кг  {diff_str}\n"
        
        # Итоговая статистика
        progress_text += f"\n🎯 Цель: {goal}\n"
        
        if total_diff > 0:
            progress_text += f"💪 Всего скинул: {total_diff:.1f} кг 🔥\n"
        elif total_diff < 0:
            progress_text += f"📈 Набрал: {abs(total_diff):.1f} кг\n"
        else:
            progress_text += f"⚖️ Вес стабилен\n"
        
        # Прогресс-бар (если худеем)
        if total_diff > 0:
            days = len(history)
            progress_text += f"📅 За {days} {'день' if days == 1 else 'дней' if days < 5 else 'дней'}\n"
        
        await message.answer(progress_text)
        
    except Exception as e:
        logger.error(f"Error parsing weight history: {e}")
        progress = (
            f"📊 Твой прогресс, {name}:\n\n"
            f"⚖️ Текущий вес: {current_weight} кг\n"
            f"🎯 Цель: {goal}\n\n"
            "💡 Нажми '⚖️ Взвеситься' чтобы обновить вес!"
        )
        await message.answer(progress)


@dp.message(F.text.in_(["⚖️ Взвеситься"]))
async def menu_weigh_in(message: Message, state: FSMContext):
    """Handle weigh-in button from menu"""
    await message.answer(
        "⚖️ Взвешивание\n\n"
        "Напиши свой текущий вес в килограммах.\n"
        "Например: 101"
    )
    await state.set_state(WeightTracking.waiting_weight)


@dp.message(WeightTracking.waiting_weight, F.text)
async def process_weight_input(message: Message, state: FSMContext):
    """Process weight input and save to history"""
    user_id = message.from_user.id
    text = normalize_text(message.text)
    
    # Парсим вес
    try:
        # Извлекаем число из текста
        nums = re.findall(r'\d+\.?\d*', text)
        if not nums:
            await message.answer("Не вижу вес. Напиши число, например: 101")
            return
        
        new_weight = float(nums[0])
        
        # Проверка на разумность
        if new_weight < 30 or new_weight > 350:
            await message.answer("Кажется, это нереальный вес. Попробуй ещё раз.")
            return
        
        # Получаем старый вес для сравнения
        old_weight_str = await get_fact(user_id, "weight_kg")
        old_weight = float(old_weight_str) if old_weight_str else new_weight
        
        # Обновляем текущий вес
        await set_fact(user_id, "weight_kg", str(new_weight))
        
        # Добавляем в историю
        import json
        from datetime import datetime
        
        weight_history_str = await get_fact(user_id, "weight_history")
        
        if weight_history_str:
            try:
                history = json.loads(weight_history_str)
            except:
                history = []
        else:
            # Первое взвешивание - добавляем начальный вес если он был
            history = []
            if old_weight_str and old_weight != new_weight:
                # Добавляем старый вес как начальную точку (вчера)
                from datetime import timedelta
                yesterday = (datetime.now() - timedelta(days=1)).strftime("%d.%m")
                history.append({
                    'date': yesterday,
                    'weight': old_weight
                })
        
        # Добавляем новое взвешивание
        today = datetime.now().strftime("%d.%m")
        
        # Проверяем есть ли уже запись на сегодня
        today_exists = False
        for i, entry in enumerate(history):
            if entry['date'] == today:
                history[i]['weight'] = new_weight
                today_exists = True
                break
        
        if not today_exists:
            history.append({
                'date': today,
                'weight': new_weight
            })
        
        # Сохраняем историю
        await set_fact(user_id, "weight_history", json.dumps(history))
        
        # Вычисляем разницу
        diff = old_weight - new_weight
        
        # Красивое сообщение
        if abs(diff) < 0.1:
            result = (
                f"⚖️ Вес зафиксирован: {new_weight} кг\n\n"
                f"Вес стабилен! Так держать! 💪"
            )
        elif diff > 0:
            result = (
                f"⚖️ Вес зафиксирован: {new_weight} кг\n\n"
                f"⬇️ -{diff:.1f} кг с прошлого раза!\n"
                f"Отличная работа! 🔥"
            )
        else:
            result = (
                f"⚖️ Вес зафиксирован: {new_weight} кг\n\n"
                f"⬆️ +{abs(diff):.1f} кг с прошлого раза"
            )
        
        # Добавляем прогресс если есть история
        if len(history) > 1:
            first_weight = history[0]['weight']
            total_diff = first_weight - new_weight
            if abs(total_diff) > 0.1:
                if total_diff > 0:
                    result += f"\n\n💪 Всего скинул: {total_diff:.1f} кг!"
                else:
                    result += f"\n\n📈 Всего набрал: {abs(total_diff):.1f} кг"
        
        result += "\n\nНажми '📊 Мой прогресс' чтобы увидеть динамику!"
        
        await state.clear()
        await message.answer(result)
        
    except Exception as e:
        logger.error(f"Error processing weight: {e}")
        await message.answer("Произошла ошибка. Попробуй ещё раз!")
        await state.clear()


@dp.message(F.text.in_(["⚙️ Настройки"]))
async def menu_settings(message: Message):
    """Handle settings button from menu"""
    user_id = message.from_user.id
    name = await get_fact(user_id, "name") or "?"
    goal = await get_fact(user_id, "goal") or "?"
    weight = await get_fact(user_id, "weight_kg") or "?"
    height = await get_fact(user_id, "height_cm") or "?"
    age = await get_fact(user_id, "age") or "?"
    activity = await get_fact(user_id, "activity") or "?"
    
    settings = (
        f"⚙️ Твои настройки:\n\n"
        f"👤 Имя: {name}\n"
        f"🎯 Цель: {goal}\n"
        f"⚖️ Вес: {weight} кг\n"
        f"📏 Рост: {height} см\n"
        f"🎂 Возраст: {age} лет\n"
        f"🏃 Активность: {activity}\n\n"
        "Чтобы изменить данные, напиши:\nreset"
    )
    
    await message.answer(settings)


# -------------------- default text handler --------------------
@dp.message(F.text)
async def handle_text(message: Message, state: FSMContext):
    """Handle all other text messages"""
    if is_reset_command(message.text):
        user_id = message.from_user.id
        await set_facts(user_id, {
            "name": "", "goal": "", "weight_kg": "",
            "height_cm": "", "age": "", "activity": "", "job": "",
        })
        await state.clear()
        await message.answer(
            "✅ Анкету сбросил! Напиши /start чтобы пройти заново.",
            reply_markup=ReplyKeyboardRemove()
        )
        return
    
    user_language = detect_language(message.from_user.language_code)
    user_id = message.from_user.id
    text = normalize_text(message.text)

    # Don't process if in onboarding or weight tracking state
    current_state = await state.get_state()
    if current_state in {
        Onboarding.waiting_name.state,
        Onboarding.waiting_goal.state,
        Onboarding.waiting_whA.state,
        Onboarding.waiting_activity.state,
        WeightTracking.waiting_weight.state,
    }:
        return

    # Check profile complete - if missing, START onboarding immediately!
    missing = await profile_missing(user_id)
    if missing is not None:
        # Start onboarding right away instead of asking to type /start
        greeting = (
            "👋 Привет! Я твой AI-диетолог.\n\n"
            "🎯 Что я умею:\n"
            "• Анализировать фото еды и считать калории 📸\n"
            "• Составлять персональные планы питания 📋\n"
            "• Подбирать программы тренировок 💪\n"
            "• Создавать режим дня под твои цели ⏰\n"
            "• Помогать достичь желаемого веса 🎯\n\n"
            "Давай познакомимся и составим твой идеальный план! 😊"
        )
        
        await message.answer(greeting, reply_markup=ReplyKeyboardRemove())
        await asyncio.sleep(1)
        await message.answer("Как тебя зовут? Напиши, пожалуйста, только имя.")
        await state.set_state(Onboarding.waiting_name)
        return

    # Quick greetings
    low = text.lower()
    if any(x in low for x in ["привет", "здрав", "hello", "hi", "ahoj"]):
        name = await get_fact(user_id, "name") or "друг"
        menu = create_main_menu()
        await message.answer(f"Привет, {name}! 😊 Чем помочь?", reply_markup=menu)
        return

    # Normal chat
    reply = await chat_reply(text, user_language, user_id)
    await message.answer(reply)


# -------------------- run --------------------
async def main():
    logger.info("🚀 Starting Dietitian Bot...")
    logger.info(f"📊 GPT Model: {GPT_MODEL}")

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
