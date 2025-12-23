#!/usr/bin/env python3
"""
Telegram Dietitian Bot - ФИНАЛЬНАЯ ВЕРСИЯ
✅ Выбор языка при старте
✅ Улучшенное распознавание фото
✅ Серьёзные рекомендации (80%) + шутка (20%)
✅ Эмодзи только при фото
✅ Полная поддержка 3 языков
"""

import asyncio
import logging
import base64
import re
import json
from io import BytesIO
from typing import Optional, Tuple
from datetime import datetime, timedelta

import httpx
from openai import AsyncOpenAI

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove, CallbackQuery
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from config import TELEGRAM_TOKEN, OPENAI_API_KEY, GPT_MODEL
from database import FOOD_DATABASE
from languages import detect_language, get_text
from db import init_db, ensure_user_exists, set_fact, set_facts, get_fact, delete_all_facts


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
class LanguageSelection(StatesGroup):
    waiting_language = State()

class Onboarding(StatesGroup):
    waiting_name = State()
    waiting_goal = State()
    waiting_whA = State()
    waiting_activity = State()

class WeightTracking(StatesGroup):
    waiting_weight = State()


# -------------------- multilingual texts --------------------
TEXTS = {
    "ru": {
        "choose_language": "Выбери язык / Choose language / Vyberte jazyk:",
        "greeting": (
            "👋 Привет! Я твой AI-диетолог.\n\n"
            "🎯 Что я умею:\n"
            "• Анализировать фото еды и считать калории 📸\n"
            "• Составлять персональные планы питания 📋\n"
            "• Подбирать программы тренировок 💪\n"
            "• Создавать режим дня под твои цели ⏰\n"
            "• Помогать достичь желаемого веса 🎯\n\n"
            "Давай познакомимся и составим твой идеальный план! 😊"
        ),
        "ask_name": "Как тебя зовут? Напиши, пожалуйста, только имя.",
        "welcome_back": "С возвращением, {name}! 😊\nЯ готов помочь тебе с питанием. Чем займёмся сегодня?",
        "ask_goal": "Отлично, {name}! Какая у тебя цель?",
        "goal_lose": "🏃 Похудеть",
        "goal_gain": "💪 Набрать",
        "goal_maintain": "⚖️ Поддерживать",
        "goal_accepted": (
            "Супер! Отличная цель! 🎯\n\n"
            "Теперь расскажи мне о себе:\n"
            "Напиши одним сообщением: вес (кг), рост (см), возраст\n\n"
            "Например: 114, 182, 49"
        ),
        "ask_activity": "Отлично! Последний вопрос:\n\nКакая у тебя физическая активность?",
        "activity_low": "🛋 Низкая",
        "activity_medium": "🚶 Средняя",
        "activity_high": "🏃 Высокая",
        "onboarding_complete": (
            "Отлично! Теперь я знаю о тебе всё необходимое! 🎉\n\n"
            "Что могу для тебя сделать:\n"
            "📸 Пришли фото еды - я посчитаю калории\n"
            "💬 Задай вопрос о питании\n"
            "📋 Попроси составить план питания\n"
            "💪 Подберу программу тренировок\n\n"
            "С чего начнём?"
        ),
        "analyzing_1": "🔍 Смотрю на твою еду...",
        "analyzing_2": "🤔 Хм, интересненько...",
        "analyzing_3": "💭 Думаю-думаю...",
        "analyzing_done": "✨ Готово! Вот что думаю:",
    },
    "cs": {
        "choose_language": "Výběr jazyka / Choose language / Выбери язык:",
        "greeting": (
            "👋 Ahoj! Jsem tvůj AI dietolog.\n\n"
            "🎯 Co umím:\n"
            "• Analyzovat fotky jídla a počítat kalorie 📸\n"
            "• Vytvářet osobní jídelní plány 📋\n"
            "• Navrhovat tréninky 💪\n"
            "• Vytvářet denní režim podle tvých cílů ⏰\n"
            "• Pomoci dosáhnout požadované váhy 🎯\n\n"
            "Pojďme se seznámit a vytvořit tvůj ideální plán! 😊"
        ),
        "ask_name": "Jak se jmenuješ? Napiš prosím jen jméno.",
        "welcome_back": "Vítej zpět, {name}! 😊\nJsem připraven pomoci s tvým stravováním. Co dnes budeme dělat?",
        "ask_goal": "Skvělé, {name}! Jaký je tvůj cíl?",
        "goal_lose": "🏃 Zhubnout",
        "goal_gain": "💪 Nabrat",
        "goal_maintain": "⚖️ Udržovat",
        "goal_accepted": (
            "Super! Výborný cíl! 🎯\n\n"
            "Teď mi řekni o sobě:\n"
            "Napiš v jedné zprávě: váha (kg), výška (cm), věk\n\n"
            "Například: 114, 182, 49"
        ),
        "ask_activity": "Výborně! Poslední otázka:\n\nJaká je tvá fyzická aktivita?",
        "activity_low": "🛋 Nízká",
        "activity_medium": "🚶 Střední",
        "activity_high": "🏃 Vysoká",
        "onboarding_complete": (
            "Skvělé! Teď o tobě vím vše potřebné! 🎉\n\n"
            "Co pro tebe můžu udělat:\n"
            "📸 Pošli fotku jídla - spočítám kalorie\n"
            "💬 Zeptej se na výživu\n"
            "📋 Požádej o jídelní plán\n"
            "💪 Navrhnu tréninkový program\n\n"
            "Čím začneme?"
        ),
        "analyzing_1": "🔍 Dívám se na tvoje jídlo...",
        "analyzing_2": "🤔 Hmm, zajímavé...",
        "analyzing_3": "💭 Přemýšlím...",
        "analyzing_done": "✨ Hotovo! Tady je co si myslím:",
    },
    "en": {
        "choose_language": "Choose language / Выбери язык / Vyberte jazyk:",
        "greeting": (
            "👋 Hi! I'm your AI dietitian.\n\n"
            "🎯 What I can do:\n"
            "• Analyze food photos and count calories 📸\n"
            "• Create personalized meal plans 📋\n"
            "• Design workout programs 💪\n"
            "• Build daily schedules for your goals ⏰\n"
            "• Help you reach your target weight 🎯\n\n"
            "Let's get to know each other and create your perfect plan! 😊"
        ),
        "ask_name": "What's your name? Please write just your first name.",
        "welcome_back": "Welcome back, {name}! 😊\nI'm ready to help with your nutrition. What shall we work on today?",
        "ask_goal": "Great, {name}! What's your goal?",
        "goal_lose": "🏃 Lose weight",
        "goal_gain": "💪 Gain muscle",
        "goal_maintain": "⚖️ Maintain",
        "goal_accepted": (
            "Awesome! Great goal! 🎯\n\n"
            "Now tell me about yourself:\n"
            "Write in one message: weight (kg), height (cm), age\n\n"
            "For example: 114, 182, 49"
        ),
        "ask_activity": "Perfect! Last question:\n\nWhat's your physical activity level?",
        "activity_low": "🛋 Low",
        "activity_medium": "🚶 Moderate",
        "activity_high": "🏃 High",
        "onboarding_complete": (
            "Excellent! Now I know everything I need! 🎉\n\n"
            "What I can do for you:\n"
            "📸 Send food photo - I'll count calories\n"
            "💬 Ask about nutrition\n"
            "📋 Request a meal plan\n"
            "💪 Get a workout program\n\n"
            "Where shall we start?"
        ),
        "analyzing_1": "🔍 Looking at your food...",
        "analyzing_2": "🤔 Hmm, interesting...",
        "analyzing_3": "💭 Thinking...",
        "analyzing_done": "✨ Done! Here's what I think:",
    }
}


def get_text_lang(lang: str, key: str, **kwargs) -> str:
    """Get text in specified language"""
    texts = TEXTS.get(lang, TEXTS["ru"])
    text = texts.get(key, TEXTS["ru"].get(key, ""))
    return text.format(**kwargs) if kwargs else text


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
    return t in {"reset", "/reset", "сброс", "заново", "начать заново", "resetovat"}


async def clear_user_data(user_id: int):
    """Полностью очищает данные пользователя - УДАЛЯЕТ из БД!"""
    try:
        # Удаляем ВСЕ факты из user_facts таблицы
        await delete_all_facts(user_id)
    except Exception as e:
        logger.error(f"Error clearing user data: {e}")
        # Если функция не найдена (старая версия db.py), пробуем старый способ
        # НО с пометкой что это не сработает полностью
        facts_to_clear = [
            "language", "name", "goal", "weight_kg", "height_cm", 
            "age", "activity", "job", "weight_history"
        ]
        for fact_key in facts_to_clear:
            try:
                await set_fact(user_id, fact_key, "")
            except:
                pass


async def profile_missing(user_id: int) -> Optional[str]:
    """Returns prompt for missing data or None if complete"""
    name = await get_fact(user_id, "name")
    goal = await get_fact(user_id, "goal")
    weight = await get_fact(user_id, "weight_kg")
    height = await get_fact(user_id, "height_cm")
    age = await get_fact(user_id, "age")
    activity = await get_fact(user_id, "activity")
    language = await get_fact(user_id, "language")

    # Проверяем не только None, но и пустые строки!
    if not language or language == "":
        return "language"
    if not name or name == "":
        return "name"
    if not goal or goal == "":
        return "goal"
    if not weight or weight == "" or not height or height == "" or not age or age == "":
        return "wha"
    if not activity or activity == "":
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


async def analyze_food_photo(photo_bytes: bytes, user_id: int) -> str:
    """
    Vision analysis with improved recognition and 80/20 recommendations
    80% serious detailed advice + 20% playful alternative at the end
    """
    try:
        # Получаем профиль пользователя
        name = await get_fact(user_id, "name") or "друг"
        goal = await get_fact(user_id, "goal") or "поддерживать вес"
        weight = await get_fact(user_id, "weight_kg") or "?"
        activity = await get_fact(user_id, "activity") or "средняя"
        user_lang = await get_fact(user_id, "language") or "ru"
        
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

        # Определяем язык промпта
        lang_map = {
            "ru": "русском",
            "cs": "чешском", 
            "en": "английском"
        }
        response_lang = lang_map.get(user_lang, "русском")

        system_prompt = (
            f"Ты дружелюбный AI-диетолог. Отвечай ТОЛЬКО на {response_lang} языке!\n\n"
            f"ПРОФИЛЬ ПОЛЬЗОВАТЕЛЯ:\n"
            f"- Имя: {name}\n"
            f"- Цель: {goal}\n"
            f"- Текущий вес: {weight} кг\n"
            f"- Активность: {activity}\n\n"
            f"ВАЖНО: Если не уверен что именно на фото:\n"
            f"- Напиши что видишь частично\n"
            f"- Перечисли что определил\n"
            f"- Попроси уточнить остальное\n"
            f"- НЕ ВЫДАВАЙ нули и пустые данные!\n\n"
            f"ФОРМАТ ОТВЕТА:\n"
            f"1. Название блюда (или 'Частично определено')\n"
            f"2. Вес порции в граммах (или 0 если не определил)\n"
            f"3. Калории (или 0 если не уверен)\n"
            f"4. Белки, жиры, углеводы (или 0 если не уверен)\n"
            f"5. РЕКОМЕНДАЦИИ (ВАЖНО!):\n"
            f"   80% - Детальные серьёзные советы (5-7 предложений):\n"
            f"     • Подходит ли для цели?\n"
            f"     • Что хорошо/плохо в блюде?\n"
            f"     • Конкретные изменения (уменьшить/добавить)\n"
            f"     • Детали по БЖУ и калориям\n"
            f"   20% - В КОНЦЕ короткая игривая альтернатива:\n"
            f"     • 'Или можешь съесть всё и пробежать 2км! 😉'\n"
            f"     • Одна фраза, легко и с юмором\n\n"
            f"Если НЕ видишь еду четко - напиши: 'Я вижу [что видишь], но не уверен в [чём не уверен]. Можете уточнить или сфотографировать при лучшем освещении?'"
        )

        user_prompt = (
            f"{db_description}\n\n"
            f"Проанализируй фото и ответь на {response_lang} языке в формате:\n"
            f"БЛЮДО: название (или что видишь)\n"
            f"ВЕС: число\n"
            f"КАЛОРИИ: число\n"
            f"БЕЛКИ: число\n"
            f"ЖИРЫ: число\n"
            f"УГЛЕВОДЫ: число\n"
            f"РЕКОМЕНДАЦИИ: [80% детальных советов + 20% игривая альтернатива в конце]"
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
            max_tokens=1500,
            temperature=0.6,
        )

        result = (resp.choices[0].message.content or "").strip()
        
        if not result:
            return "Не смог проанализировать фото. Попробуй другое фото или опиши блюдо словами."

        # Парсим ответ
        lines = result.split('\n')
        food_name = "Блюдо"
        weight = 100
        calories = 0
        protein = 0.0
        fat = 0.0
        carbs = 0.0
        recommendations = ""
        
        for line in lines:
            line_lower = line.lower()
            if 'блюдо:' in line_lower or 'dish:' in line_lower or 'jídlo:' in line_lower:
                food_name = line.split(':', 1)[1].strip()
            elif 'вес:' in line_lower or 'weight:' in line_lower or 'váha:' in line_lower:
                nums = re.findall(r'\d+', line)
                if nums:
                    weight = int(nums[0])
            elif 'калор' in line_lower or 'calor' in line_lower or 'kalor' in line_lower:
                nums = re.findall(r'\d+', line)
                if nums:
                    calories = int(nums[0])
            elif 'белк' in line_lower or 'protein' in line_lower or 'bílk' in line_lower:
                nums = re.findall(r'\d+\.?\d*', line)
                if nums:
                    protein = float(nums[0])
            elif 'жир' in line_lower or 'fat' in line_lower or 'tuk' in line_lower:
                nums = re.findall(r'\d+\.?\d*', line)
                if nums:
                    fat = float(nums[0])
            elif 'углевод' in line_lower or 'carb' in line_lower or 'sacharid' in line_lower:
                nums = re.findall(r'\d+\.?\d*', line)
                if nums:
                    carbs = float(nums[0])
            elif 'рекоменд' in line_lower or 'recommend' in line_lower or 'doporuč' in line_lower:
                recommendations = line.split(':', 1)[1].strip() if ':' in line else ""
        
        # Собираем рекомендации если не нашли
        if not recommendations:
            rec_started = False
            rec_lines = []
            for line in lines:
                ll = line.lower()
                if 'рекоменд' in ll or 'recommend' in ll or 'doporuč' in ll:
                    rec_started = True
                    if ':' in line:
                        rec_lines.append(line.split(':', 1)[1].strip())
                    continue
                if rec_started and line.strip():
                    rec_lines.append(line.strip())
            recommendations = '\n'.join(rec_lines)
        
        # ВАЖНО: Проверка если не распознал - ПЕРЕД созданием карточки!
        if calories == 0 and protein == 0 and fat == 0 and carbs == 0:
            # Не распознал - показываем полный ответ GPT (там должны быть вопросы)
            return f"🤔 Хм, давай разберёмся:\n\n{result}"
        
        # Если распознал хотя бы частично - создаём карточку
        card = format_food_card(food_name, calories, protein, fat, carbs, weight)
        
        # Добавляем рекомендации
        if recommendations:
            card += f"\n\n💡 Рекомендации:\n\n{recommendations}"
        
        return card

    except Exception as e:
        logger.error(f"Error analyzing photo: {e}", exc_info=True)
        return (
            "Произошла ошибка при анализе фото 😔\n"
            "Попробуй ещё раз или опиши блюдо словами!"
        )


async def chat_reply(user_text: str, user_id: int) -> str:
    """Normal chat reply WITHOUT thinking emojis"""
    try:
        name = await get_fact(user_id, "name") or ""
        goal = await get_fact(user_id, "goal") or ""
        weight = await get_fact(user_id, "weight_kg") or ""
        height = await get_fact(user_id, "height_cm") or ""
        age = await get_fact(user_id, "age") or ""
        activity = await get_fact(user_id, "activity") or ""
        job = await get_fact(user_id, "job") or ""
        user_lang = await get_fact(user_id, "language") or "ru"

        # Определяем язык ответа
        lang_map = {
            "ru": "русском",
            "cs": "чешском",
            "en": "английском"
        }
        response_lang = lang_map.get(user_lang, "русском")

        profile = (
            f"Профиль: имя={name}, цель={goal}, "
            f"вес={weight}кг, рост={height}см, возраст={age}, "
            f"активность={activity}, работа={job}."
        )

        system_prompt = (
            f"Ты дружелюбный AI-диетолог. Отвечай ТОЛЬКО на {response_lang} языке!\n"
            f"Стиль: короткие ответы (2-4 предложения), БЕЗ эмодзи 'думаю/размышляю'.\n"
            f"{profile}"
        )

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


# -------------------- /start with language selection --------------------
@dp.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    """Start with language selection"""
    user_id = message.from_user.id
    await state.clear()

    missing = await profile_missing(user_id)
    
    # Если профиль заполнен полностью - показываем главное меню
    if missing is None:
        user_lang = await get_fact(user_id, "language") or "ru"
        name = await get_fact(user_id, "name") or "друг"
        menu = create_main_menu()
        
        welcome = get_text_lang(user_lang, "welcome_back", name=name)
        await message.answer(welcome, reply_markup=menu)
        return

    # Если нет языка - показываем выбор языка
    if missing == "language":
        # Кнопки выбора языка
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [
                InlineKeyboardButton(text="🇷🇺 Русский", callback_data="lang_ru"),
                InlineKeyboardButton(text="🇨🇿 Čeština", callback_data="lang_cs"),
            ],
            [
                InlineKeyboardButton(text="🇬🇧 English", callback_data="lang_en")
            ]
        ])
        
        await message.answer(
            "Выбери язык / Choose language / Vyberte jazyk:",
            reply_markup=keyboard
        )
        await state.set_state(LanguageSelection.waiting_language)
        return
    
    # Если язык есть но профиль не заполнен - продолжаем onboarding
    user_lang = await get_fact(user_id, "language") or "ru"
    
    if missing == "name":
        greeting = get_text_lang(user_lang, "greeting")
        await message.answer(greeting, reply_markup=ReplyKeyboardRemove())
        await asyncio.sleep(1)
        
        ask_name = get_text_lang(user_lang, "ask_name")
        await message.answer(ask_name)
        await state.set_state(Onboarding.waiting_name)


@dp.callback_query(LanguageSelection.waiting_language)
async def language_selected(callback: CallbackQuery, state: FSMContext):
    """Handle language selection"""
    user_id = callback.from_user.id
    
    lang_map = {
        "lang_ru": "ru",
        "lang_cs": "cs",
        "lang_en": "en"
    }
    
    selected_lang = lang_map.get(callback.data, "ru")
    await set_fact(user_id, "language", selected_lang)
    
    # Убираем кнопки
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.answer()
    
    # Показываем приветствие на выбранном языке
    greeting = get_text_lang(selected_lang, "greeting")
    await callback.message.answer(greeting, reply_markup=ReplyKeyboardRemove())
    await asyncio.sleep(1)
    
    ask_name = get_text_lang(selected_lang, "ask_name")
    await callback.message.answer(ask_name)
    await state.set_state(Onboarding.waiting_name)


@dp.message(Command("help"))
async def cmd_help(message: Message):
    """Help command"""
    user_id = message.from_user.id
    user_lang = await get_fact(user_id, "language") or "ru"
    
    help_text = {
        "ru": (
            "📋 Команды:\n"
            "/start — начать или продолжить\n"
            "reset — сбросить анкету\n\n"
            "💬 Можно:\n"
            "• Задавать вопросы про питание\n"
            "• Присылать фото еды для анализа 📸\n"
            "• Просить план питания или тренировок"
        ),
        "cs": (
            "📋 Příkazy:\n"
            "/start — začít nebo pokračovat\n"
            "reset — resetovat profil\n\n"
            "💬 Můžeš:\n"
            "• Ptát se na výživu\n"
            "• Poslat fotku jídla na analýzu 📸\n"
            "• Požádat o jídelní plán nebo trénink"
        ),
        "en": (
            "📋 Commands:\n"
            "/start — start or continue\n"
            "reset — reset profile\n\n"
            "💬 You can:\n"
            "• Ask about nutrition\n"
            "• Send food photos for analysis 📸\n"
            "• Request meal plans or workouts"
        )
    }
    
    await message.answer(help_text.get(user_lang, help_text["ru"]))


# -------------------- onboarding: name --------------------
@dp.message(Onboarding.waiting_name, F.text)
async def onboarding_name(message: Message, state: FSMContext):
    """Collect user name"""
    if is_reset_command(message.text):
        user_id = message.from_user.id
        await clear_user_data(user_id)
        await state.clear()
        await message.answer("✅ Сброшено! Напиши /start чтобы начать заново.", reply_markup=ReplyKeyboardRemove())
        return
    
    user_id = message.from_user.id
    user_lang = await get_fact(user_id, "language") or "ru"
    await ensure_user_exists(user_id)
    name = normalize_text(message.text)
    
    if len(name) < 2 or len(name) > 30:
        await message.answer("Please write just your name (2–30 characters).")
        return

    await set_fact(user_id, "name", name)
    
    # Кнопки для выбора цели
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text=get_text_lang(user_lang, "goal_lose"), 
                callback_data="goal_lose"
            ),
            InlineKeyboardButton(
                text=get_text_lang(user_lang, "goal_gain"),
                callback_data="goal_gain"
            ),
        ],
        [
            InlineKeyboardButton(
                text=get_text_lang(user_lang, "goal_maintain"),
                callback_data="goal_maintain"
            )
        ]
    ])
    
    ask_goal = get_text_lang(user_lang, "ask_goal", name=name)
    await message.answer(ask_goal, reply_markup=keyboard)
    await state.set_state(Onboarding.waiting_goal)


# -------------------- onboarding: goal --------------------
@dp.callback_query(Onboarding.waiting_goal)
async def onboarding_goal_callback(callback: CallbackQuery, state: FSMContext):
    """Handle goal selection"""
    user_id = callback.from_user.id
    user_lang = await get_fact(user_id, "language") or "ru"
    
    goal_map = {
        "ru": {
            "goal_lose": "похудеть",
            "goal_gain": "набрать массу",
            "goal_maintain": "поддерживать"
        },
        "cs": {
            "goal_lose": "zhubnout",
            "goal_gain": "nabrat",
            "goal_maintain": "udržovat"
        },
        "en": {
            "goal_lose": "lose weight",
            "goal_gain": "gain muscle",
            "goal_maintain": "maintain"
        }
    }
    
    goals = goal_map.get(user_lang, goal_map["ru"])
    goal = goals.get(callback.data, goals["goal_maintain"])
    await set_fact(user_id, "goal", goal)
    
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.answer()
    
    goal_accepted = get_text_lang(user_lang, "goal_accepted")
    await callback.message.answer(goal_accepted)
    await state.set_state(Onboarding.waiting_whA)


# -------------------- onboarding: fallback text for goal --------------------
@dp.message(Onboarding.waiting_goal, F.text)
async def onboarding_goal_text(message: Message, state: FSMContext):
    """Handle goal if user writes instead of clicking"""
    if is_reset_command(message.text):
        user_id = message.from_user.id
        await clear_user_data(user_id)
        await state.clear()
        await message.answer("✅ Сброшено! Напиши /start чтобы начать заново.", reply_markup=ReplyKeyboardRemove())
        return
    
    user_id = message.from_user.id
    user_lang = await get_fact(user_id, "language") or "ru"
    goal_text = normalize_text(message.text).lower()
    
    # Определяем цель из текста
    goal = "поддерживать"
    if any(x in goal_text for x in ["похуд", "сброс", "lose", "zhubn"]):
        goal = {"ru": "похудеть", "cs": "zhubnout", "en": "lose weight"}.get(user_lang, "похудеть")
    elif any(x in goal_text for x in ["наб", "мыш", "gain", "nabr"]):
        goal = {"ru": "набрать массу", "cs": "nabrat", "en": "gain muscle"}.get(user_lang, "набрать массу")
    elif any(x in goal_text for x in ["удерж", "поддерж", "maintain", "udržov"]):
        goal = {"ru": "поддерживать", "cs": "udržovat", "en": "maintain"}.get(user_lang, "поддерживать")

    await set_fact(user_id, "goal", goal)
    
    goal_accepted = get_text_lang(user_lang, "goal_accepted")
    await message.answer(goal_accepted)
    await state.set_state(Onboarding.waiting_whA)


# -------------------- onboarding: weight/height/age --------------------
@dp.message(Onboarding.waiting_whA, F.text)
async def onboarding_wha(message: Message, state: FSMContext):
    """Collect weight, height, age"""
    if is_reset_command(message.text):
        user_id = message.from_user.id
        await clear_user_data(user_id)
        await state.clear()
        await message.answer("✅ Сброшено! Напиши /start чтобы начать заново.", reply_markup=ReplyKeyboardRemove())
        return
    
    user_id = message.from_user.id
    user_lang = await get_fact(user_id, "language") or "ru"
    parsed = parse_weight_height_age(message.text)
    
    if parsed is None:
        await message.answer("Please write all data in one message.")
        return

    w, h, a = parsed
    await set_facts(user_id, {
        "weight_kg": str(w),
        "height_cm": str(h),
        "age": str(a),
    })

    # Кнопки для выбора активности
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(
                text=get_text_lang(user_lang, "activity_low"),
                callback_data="activity_low"
            ),
            InlineKeyboardButton(
                text=get_text_lang(user_lang, "activity_medium"),
                callback_data="activity_medium"
            ),
        ],
        [
            InlineKeyboardButton(
                text=get_text_lang(user_lang, "activity_high"),
                callback_data="activity_high"
            )
        ]
    ])
    
    ask_activity = get_text_lang(user_lang, "ask_activity")
    await message.answer(ask_activity, reply_markup=keyboard)
    await state.set_state(Onboarding.waiting_activity)


# -------------------- onboarding: activity --------------------
@dp.callback_query(Onboarding.waiting_activity)
async def onboarding_activity_callback(callback: CallbackQuery, state: FSMContext):
    """Handle activity selection"""
    user_id = callback.from_user.id
    user_lang = await get_fact(user_id, "language") or "ru"
    
    activity_map = {
        "ru": {"activity_low": "низкая", "activity_medium": "средняя", "activity_high": "высокая"},
        "cs": {"activity_low": "nízká", "activity_medium": "střední", "activity_high": "vysoká"},
        "en": {"activity_low": "low", "activity_medium": "moderate", "activity_high": "high"}
    }
    
    activities = activity_map.get(user_lang, activity_map["ru"])
    activity = activities.get(callback.data, activities["activity_medium"])
    await set_facts(user_id, {"activity": activity, "job": ""})
    
    await callback.message.edit_reply_markup(reply_markup=None)
    await state.clear()
    
    menu = create_main_menu()
    await callback.answer()
    
    complete_msg = get_text_lang(user_lang, "onboarding_complete")
    await callback.message.answer(complete_msg, reply_markup=menu)


# -------------------- onboarding: activity text fallback --------------------
@dp.message(Onboarding.waiting_activity, F.text)
async def onboarding_activity_text(message: Message, state: FSMContext):
    """Handle activity if user writes instead of clicking"""
    if is_reset_command(message.text):
        user_id = message.from_user.id
        await clear_user_data(user_id)
        await state.clear()
        await message.answer("✅ Сброшено! Напиши /start чтобы начать заново.", reply_markup=ReplyKeyboardRemove())
        return
    
    user_id = message.from_user.id
    user_lang = await get_fact(user_id, "language") or "ru"
    text = normalize_text(message.text)
    t = text.lower()
    
    activity = "средняя"
    if any(x in t for x in ["низ", "low", "nízk"]):
        activity = {"ru": "низкая", "cs": "nízká", "en": "low"}.get(user_lang, "низкая")
    elif any(x in t for x in ["сред", "moderate", "střed"]):
        activity = {"ru": "средняя", "cs": "střední", "en": "moderate"}.get(user_lang, "средняя")
    elif any(x in t for x in ["выс", "high", "vysok"]):
        activity = {"ru": "высокая", "cs": "vysoká", "en": "high"}.get(user_lang, "высокая")

    await set_facts(user_id, {"activity": activity, "job": ""})
    await state.clear()
    
    menu = create_main_menu()
    complete_msg = get_text_lang(user_lang, "onboarding_complete")
    await message.answer(complete_msg, reply_markup=menu)


# -------------------- photo handler with emoji reactions --------------------
@dp.message(F.photo)
async def handle_photo(message: Message, state: FSMContext):
    """Handle photo with animated emoji reactions"""
    user_id = message.from_user.id
    user_lang = await get_fact(user_id, "language") or "ru"

    missing = await profile_missing(user_id)
    if missing is not None:
        await message.answer("Please complete registration first! Write /start")
        return

    # Анимированные эмодзи (ТОЛЬКО ПРИ ФОТО!)
    status_msg = await message.answer(get_text_lang(user_lang, "analyzing_1"))
    await asyncio.sleep(1)
    
    try:
        await status_msg.edit_text(get_text_lang(user_lang, "analyzing_2"))
        await asyncio.sleep(0.8)
        
        await status_msg.edit_text(get_text_lang(user_lang, "analyzing_3"))
        
        photo = message.photo[-1]
        file = await bot.get_file(photo.file_id)

        buf = BytesIO()
        await bot.download_file(file.file_path, destination=buf)
        photo_bytes = buf.getvalue()

        result = await analyze_food_photo(photo_bytes, user_id)
        
        await status_msg.edit_text(get_text_lang(user_lang, "analyzing_done"))
        await asyncio.sleep(0.5)
        await status_msg.delete()
        
        await message.answer(result)

    except Exception as e:
        logger.error(f"Error handling photo: {e}", exc_info=True)
        try:
            await status_msg.delete()
        except:
            pass
        await message.answer("Could not process photo 😔 Try again!")


# -------------------- voice handler --------------------
@dp.message(F.voice)
async def handle_voice(message: Message, state: FSMContext):
    """Handle voice messages"""
    user_id = message.from_user.id
    user_lang = await get_fact(user_id, "language") or "ru"
    
    status_msg = await message.answer("🎤 Listening...")

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
            language=user_lang if user_lang != "cs" else "cs"
        )
        
        recognized_text = transcription.text.strip()
        
        await status_msg.delete()
        
        if not recognized_text:
            await message.answer("Could not recognize speech. Try again 🙂")
            return
        
        await message.answer(f"📝 Recognized: \"{recognized_text}\"")
        
        if is_reset_command(recognized_text):
            await clear_user_data(user_id)
            await state.clear()
            await message.answer("✅ Сброшено! Напиши /start чтобы начать заново.", reply_markup=ReplyKeyboardRemove())
            return
        
        # Handle based on current state
        current_state = await state.get_state()
        if current_state == Onboarding.waiting_name.state:
            name = normalize_text(recognized_text)
            if len(name) < 2 or len(name) > 30:
                await message.answer("Please write just your name (2–30 characters).")
                return
            await set_fact(user_id, "name", name)
            
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text=get_text_lang(user_lang, "goal_lose"),
                        callback_data="goal_lose"
                    ),
                    InlineKeyboardButton(
                        text=get_text_lang(user_lang, "goal_gain"),
                        callback_data="goal_gain"
                    ),
                ],
                [
                    InlineKeyboardButton(
                        text=get_text_lang(user_lang, "goal_maintain"),
                        callback_data="goal_maintain"
                    )
                ]
            ])
            await message.answer(
                get_text_lang(user_lang, "ask_goal", name=name),
                reply_markup=keyboard
            )
            await state.set_state(Onboarding.waiting_goal)
            return
        
        # Not in onboarding
        missing = await profile_missing(user_id)
        if missing is not None:
            await message.answer("Please complete registration! Write /start")
            return
        
        # Quick greetings
        low = recognized_text.lower()
        if any(x in low for x in ["привет", "здрав", "hello", "hi", "ahoj"]):
            name = await get_fact(user_id, "name") or "друг"
            await message.answer(f"Hi, {name}! 😊 How can I help?")
            return
        
        # Normal chat (NO thinking emojis!)
        reply = await chat_reply(recognized_text, user_id)
        await message.answer(reply)
        
    except Exception as e:
        logger.error(f"Error handling voice: {e}", exc_info=True)
        try:
            await status_msg.delete()
        except:
            pass
        await message.answer("Could not process voice 😔 Try again!")


# -------------------- weight tracking --------------------
@dp.message(F.text.in_(["⚖️ Взвеситься"]))
async def menu_weigh_in(message: Message, state: FSMContext):
    """Handle weigh-in button"""
    await message.answer(
        "⚖️ Weigh-in\n\n"
        "Write your current weight in kilograms.\n"
        "Example: 101\n\n"
        "I'll remember and show your progress! 📊"
    )
    await state.set_state(WeightTracking.waiting_weight)


@dp.message(WeightTracking.waiting_weight, F.text)
async def process_weight_input(message: Message, state: FSMContext):
    """Process weight input"""
    user_id = message.from_user.id
    text = normalize_text(message.text)
    
    try:
        nums = re.findall(r'\d+\.?\d*', text)
        if not nums:
            await message.answer("Please write a number, e.g.: 101")
            return
        
        new_weight = float(nums[0])
        
        if new_weight < 30 or new_weight > 350:
            await message.answer("This doesn't seem like a realistic weight. Try again.")
            return
        
        old_weight_str = await get_fact(user_id, "weight_kg")
        old_weight = float(old_weight_str) if old_weight_str else new_weight
        
        await set_fact(user_id, "weight_kg", str(new_weight))
        
        # Add to history
        weight_history_str = await get_fact(user_id, "weight_history")
        
        if weight_history_str:
            try:
                history = json.loads(weight_history_str)
            except:
                history = []
        else:
            history = []
            if old_weight_str and old_weight != new_weight:
                yesterday = (datetime.now() - timedelta(days=1)).strftime("%d.%m")
                history.append({'date': yesterday, 'weight': old_weight})
        
        today = datetime.now().strftime("%d.%m")
        
        today_exists = False
        for i, entry in enumerate(history):
            if entry['date'] == today:
                history[i]['weight'] = new_weight
                today_exists = True
                break
        
        if not today_exists:
            history.append({'date': today, 'weight': new_weight})
        
        await set_fact(user_id, "weight_history", json.dumps(history))
        
        diff = old_weight - new_weight
        
        # Beautiful message with emojis
        if abs(diff) < 0.1:
            result = (
                f"⚖️ Weight recorded: {new_weight} kg\n\n"
                f"Weight stable! 👍\n"
                f"Keep it up! 💪"
            )
        elif diff > 0:
            emoji = "🔥" if diff >= 2 else "✨"
            result = (
                f"⚖️ Weight recorded: {new_weight} kg\n\n"
                f"⬇️ -{diff:.1f} kg since last time!\n"
                f"Great work! {emoji}"
            )
        else:
            result = (
                f"⚖️ Weight recorded: {new_weight} kg\n\n"
                f"⬆️ +{abs(diff):.1f} kg since last time\n"
                f"No worries, keep going! 💪"
            )
        
        if len(history) > 1:
            first_weight = history[0]['weight']
            total_diff = first_weight - new_weight
            if abs(total_diff) > 0.1:
                if total_diff > 0:
                    emoji = "🔥🔥🔥" if total_diff >= 10 else "🔥🔥" if total_diff >= 5 else "🔥"
                    result += f"\n\n💪 Total lost: {total_diff:.1f} kg! {emoji}"
                else:
                    result += f"\n\n📈 Total gained: {abs(total_diff):.1f} kg"
        
        result += "\n\n📊 Press 'My Progress' to see dynamics!"
        
        await state.clear()
        await message.answer(result)
        
    except Exception as e:
        logger.error(f"Error processing weight: {e}", exc_info=True)
        await message.answer("Error occurred. Try again!")
        await state.clear()


# -------------------- menu buttons --------------------
@dp.message(F.text.in_(["📸 Фото еды"]))
async def menu_photo(message: Message):
    await message.answer("📸 Great! Take a photo of your food and send it to me.\nI'll analyze and count calories!")


@dp.message(F.text.in_(["💬 Вопрос"]))
async def menu_question(message: Message):
    await message.answer("💬 Ask any nutrition question!\nYou can write or send a voice message 🎤")


@dp.message(F.text.in_(["📋 План питания"]))
async def menu_meal_plan(message: Message):
    user_id = message.from_user.id
    name = await get_fact(user_id, "name") or "friend"
    goal = await get_fact(user_id, "goal") or "maintain"
    
    await message.answer(f"{name}, creating a personalized meal plan for your goal: {goal}...\nThis will take a moment ⏳")
    
    reply = await chat_reply(f"Create a meal plan for the day considering my goal: {goal}. Include breakfast, lunch, dinner, and snacks.", user_id)
    await message.answer(f"📋 Your meal plan:\n\n{reply}")


@dp.message(F.text.in_(["💪 Тренировки"]))
async def menu_workout(message: Message):
    user_id = message.from_user.id
    name = await get_fact(user_id, "name") or "friend"
    goal = await get_fact(user_id, "goal") or "maintain"
    
    await message.answer(f"{name}, creating a workout program for your goal: {goal}...\nConsidering your activity ⏳")
    
    reply = await chat_reply(f"Create a weekly workout program. My goal: {goal}. List exercises by day.", user_id)
    await message.answer(f"💪 Your workout program:\n\n{reply}")


@dp.message(F.text.in_(["📊 Мой прогресс"]))
async def menu_progress(message: Message):
    user_id = message.from_user.id
    name = await get_fact(user_id, "name") or "friend"
    current_weight = await get_fact(user_id, "weight_kg") or "?"
    goal = await get_fact(user_id, "goal") or "?"
    
    weight_history_str = await get_fact(user_id, "weight_history")
    
    if not weight_history_str:
        progress = (
            f"📊 Your progress, {name}:\n\n"
            f"⚖️ Current weight: {current_weight} kg\n"
            f"🎯 Goal: {goal}\n\n"
            "💡 Press '⚖️ Weigh In' to start tracking progress!"
        )
        await message.answer(progress)
        return
    
    try:
        history = json.loads(weight_history_str)
        
        if not history or len(history) == 0:
            progress = (
                f"📊 Your progress, {name}:\n\n"
                f"⚖️ Current weight: {current_weight} kg\n"
                f"🎯 Goal: {goal}\n\n"
                "💡 Press '⚖️ Weigh In' to start tracking!"
            )
            await message.answer(progress)
            return
        
        history.sort(key=lambda x: x['date'])
        
        first_weight = history[0]['weight']
        last_weight = history[-1]['weight']
        total_diff = first_weight - last_weight
        
        progress_text = f"📊 Your progress, {name}:\n\n"
        
        recent = history[-5:] if len(history) > 5 else history
        
        for i, entry in enumerate(recent):
            date = entry['date']
            weight = entry['weight']
            
            if i > 0:
                prev_weight = recent[i-1]['weight']
                diff = prev_weight - weight
                if diff > 0:
                    diff_str = f"⬇️ -{diff:.1f}kg"
                elif diff < 0:
                    diff_str = f"⬆️ +{abs(diff):.1f}kg"
                else:
                    diff_str = "="
            else:
                diff_str = "start"
            
            progress_text += f"{date}  ●━━  {weight} kg  {diff_str}\n"
        
        progress_text += f"\n🎯 Goal: {goal}\n"
        
        if total_diff > 0:
            progress_text += f"💪 Total lost: {total_diff:.1f} kg 🔥\n"
        elif total_diff < 0:
            progress_text += f"📈 Gained: {abs(total_diff):.1f} kg\n"
        else:
            progress_text += f"⚖️ Weight stable\n"
        
        if total_diff > 0:
            days = len(history)
            progress_text += f"📅 Over {days} {'day' if days == 1 else 'days'}\n"
        
        await message.answer(progress_text)
        
    except Exception as e:
        logger.error(f"Error parsing weight history: {e}")
        progress = (
            f"📊 Your progress, {name}:\n\n"
            f"⚖️ Current weight: {current_weight} kg\n"
            f"🎯 Goal: {goal}\n\n"
            "💡 Press '⚖️ Weigh In' to update weight!"
        )
        await message.answer(progress)


@dp.message(F.text.in_(["⚙️ Настройки"]))
async def menu_settings(message: Message):
    user_id = message.from_user.id
    name = await get_fact(user_id, "name") or "?"
    goal = await get_fact(user_id, "goal") or "?"
    weight = await get_fact(user_id, "weight_kg") or "?"
    height = await get_fact(user_id, "height_cm") or "?"
    age = await get_fact(user_id, "age") or "?"
    activity = await get_fact(user_id, "activity") or "?"
    
    settings = (
        f"⚙️ Your settings:\n\n"
        f"👤 Name: {name}\n"
        f"🎯 Goal: {goal}\n"
        f"⚖️ Weight: {weight} kg\n"
        f"📏 Height: {height} cm\n"
        f"🎂 Age: {age} years\n"
        f"🏃 Activity: {activity}\n\n"
        "To change data, write:\nreset"
    )
    
    await message.answer(settings)


# -------------------- default text handler (NO thinking emojis!) --------------------
@dp.message(F.text)
async def handle_text(message: Message, state: FSMContext):
    """Handle all other text - NO thinking emojis!"""
    if is_reset_command(message.text):
        user_id = message.from_user.id
        await clear_user_data(user_id)
        await state.clear()
        await message.answer("✅ Сброшено! Напиши /start чтобы начать заново.", reply_markup=ReplyKeyboardRemove())
        return
    
    user_id = message.from_user.id
    text = normalize_text(message.text)

    current_state = await state.get_state()
    if current_state in {
        Onboarding.waiting_name.state,
        Onboarding.waiting_goal.state,
        Onboarding.waiting_whA.state,
        Onboarding.waiting_activity.state,
        WeightTracking.waiting_weight.state,
    }:
        return

    # Check profile - if missing, START onboarding immediately!
    missing = await profile_missing(user_id)
    if missing is not None:
        if missing == "language":
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [
                    InlineKeyboardButton(text="🇷🇺 Русский", callback_data="lang_ru"),
                    InlineKeyboardButton(text="🇨🇿 Čeština", callback_data="lang_cs"),
                ],
                [
                    InlineKeyboardButton(text="🇬🇧 English", callback_data="lang_en")
                ]
            ])
            await message.answer(
                "Выбери язык / Choose language / Vyberte jazyk:",
                reply_markup=keyboard
            )
            await state.set_state(LanguageSelection.waiting_language)
            return
        
        user_lang = await get_fact(user_id, "language") or "ru"
        greeting = get_text_lang(user_lang, "greeting")
        await message.answer(greeting, reply_markup=ReplyKeyboardRemove())
        await asyncio.sleep(1)
        await message.answer(get_text_lang(user_lang, "ask_name"))
        await state.set_state(Onboarding.waiting_name)
        return

    # Quick greetings
    user_lang = await get_fact(user_id, "language") or "ru"
    low = text.lower()
    if any(x in low for x in ["привет", "здрав", "hello", "hi", "ahoj", "čau"]):
        name = await get_fact(user_id, "name") or "друг"
        menu = create_main_menu()
        await message.answer(f"Hi, {name}! 😊 How can I help?", reply_markup=menu)
        return

    # Normal chat (NO thinking emojis!)
    reply = await chat_reply(text, user_id)
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
