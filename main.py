#!/usr/bin/env python3
"""
Telegram Dietitian Bot - WEBHOOK режим
✅ Webhook вместо polling - для высокой нагрузки
✅ Stripe webhooks работают
"""

import asyncio
import logging
import base64
import re
import json
import stripe
import os
from io import BytesIO
from typing import Optional, Tuple
from datetime import datetime, timedelta
from aiohttp import web

import httpx
from openai import AsyncOpenAI

from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup, KeyboardButton, ReplyKeyboardRemove, CallbackQuery
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.webhook.aiohttp_server import SimpleRequestHandler

from config import (
    TELEGRAM_TOKEN, OPENAI_API_KEY, GPT_MODEL,
    STRIPE_SECRET_KEY, STRIPE_WEBHOOK_SECRET,
    STRIPE_PRICE_BASIC, STRIPE_PRICE_PREMIUM,
    BASIC_DAILY_PHOTO_LIMIT, TRIAL_DAYS
)
from database import FOOD_DATABASE
from db import init_db, ensure_user_exists, set_fact, set_facts, get_fact, delete_all_facts

stripe.api_key = STRIPE_SECRET_KEY

# Webhook Configuration
RAILWAY_URL = os.getenv("RAILWAY_STATIC_URL") or os.getenv("RAILWAY_PUBLIC_DOMAIN")
if RAILWAY_URL and not RAILWAY_URL.startswith("http"):
    RAILWAY_URL = f"https://{RAILWAY_URL}"
WEBHOOK_HOST = os.getenv("WEBHOOK_HOST", RAILWAY_URL)
WEBHOOK_PATH = f"/webhook/{TELEGRAM_TOKEN}"
WEBHOOK_URL = f"{WEBHOOK_HOST}{WEBHOOK_PATH}" if WEBHOOK_HOST else None
WEB_SERVER_PORT = int(os.getenv("PORT", 8080))

ADMIN_IDS_STR = os.getenv("ADMIN_IDS", "1642251041")
ADMIN_IDS = [int(x.strip()) for x in ADMIN_IDS_STR.split(",") if x.strip().isdigit()]

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s")
logger = logging.getLogger("dietitian-bot")

http_client = httpx.AsyncClient(timeout=60.0)
openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY, http_client=http_client)

bot = Bot(token=TELEGRAM_TOKEN)
dp = Dispatcher(storage=MemoryStorage())

class LanguageSelection(StatesGroup):
    waiting_language = State()

class Onboarding(StatesGroup):
    waiting_name = State()
    waiting_goal = State()
    waiting_whA = State()
    waiting_activity = State()

class WeightTracking(StatesGroup):
    waiting_weight = State()

TEXTS = {
    "ru": {
        "choose_language": "Выбери язык / Choose language / Vyberte jazyk:",
        "greeting": "👋 Привет! Я твой AI-диетолог.\n\n🎯 Что я умею:\n• Анализировать фото еды и считать калории 📸\n• Составлять персональные планы питания 📋\n• Подбирать программы тренировок 💪\n\nДавай познакомимся! 😊",
        "ask_name": "Как тебя зовут? Напиши только имя.",
        "name_invalid": "Напиши только имя (2–30 символов).",
        "welcome_back": "С возвращением, {name}! 😊 Чем займёмся?",
        "ask_goal": "Отлично, {name}! Какая у тебя цель?",
        "goal_lose": "🏃 Похудеть", "goal_gain": "💪 Набрать", "goal_maintain": "⚖️ Поддерживать",
        "goal_lose_value": "похудеть", "goal_gain_value": "набрать массу", "goal_maintain_value": "поддерживать",
        "goal_accepted": "Супер! 🎯\n\nТеперь напиши одним сообщением: вес (кг), рост (см), возраст\n\nНапример: 114, 182, 49",
        "wha_invalid": "Напиши все данные: вес, рост, возраст.\nНапример: 114, 182, 49",
        "ask_activity": "Отлично! Какая у тебя физическая активность?",
        "activity_low": "🛋 Низкая", "activity_medium": "🚶 Средняя", "activity_high": "🏃 Высокая",
        "activity_low_value": "низкая", "activity_medium_value": "средняя", "activity_high_value": "высокая",
        "onboarding_complete": "Отлично! 🎉\n\nДля использования бота необходима подписка.",
        "subscription_required": "⚠️ Для использования бота необходима подписка.\n\nНажми /subscribe",
        "subscription_expired": "⚠️ Твоя подписка истекла.\n\nНажми /subscribe",
        "choose_plan": "💳 Выбери тариф:\n\n📦 **Basic** — €10/месяц\n• До 10 анализов фото в день\n\n⭐ **Premium** — €20/месяц\n• Безлимитные анализы\n\n🎁 Первый день — БЕСПЛАТНО!",
        "btn_basic": "📦 Basic — €10/мес", "btn_premium": "⭐ Premium — €20/мес",
        "payment_link": "💳 Перейди для оплаты:\n{url}",
        "subscription_activated": "✅ Подписка активирована!\n\n📦 Тариф: {plan}\n📅 До: {expires}",
        "subscription_status": "📊 Подписка:\n\n📦 Тариф: {plan}\n📅 До: {expires}\n📸 Фото: {used}/{limit}",
        "photo_limit_reached": "⚠️ Лимит анализов ({limit}). Обнови до Premium!\n/subscribe",
        "menu_photo": "📸 Фото еды", "menu_question": "💬 Вопрос",
        "menu_meal_plan": "📋 План питания", "menu_workout": "💪 Тренировки",
        "menu_weigh_in": "⚖️ Взвеситься", "menu_progress": "📊 Мой прогресс", "menu_settings": "⚙️ Настройки",
        "photo_prompt": "📸 Сфотографируй еду и отправь!",
        "question_prompt": "💬 Задай вопрос о питании!",
        "meal_plan_loading": "{name}, составляю план питания... ⏳",
        "meal_plan_result": "📋 План питания:\n\n{plan}",
        "workout_loading": "{name}, составляю тренировки... ⏳",
        "workout_result": "💪 Тренировки:\n\n{plan}",
        "weigh_in_prompt": "⚖️ Напиши вес в кг (например: 101)",
        "weight_invalid": "Напиши число: 101",
        "weight_unrealistic": "Нереальный вес. Попробуй ещё.",
        "weight_stable": "⚖️ {weight} кг — стабильно! 👍",
        "weight_down": "⚖️ {weight} кг — ⬇️ -{diff} кг! {emoji}",
        "weight_up": "⚖️ {weight} кг — ⬆️ +{diff} кг 💪",
        "weight_total_lost": "\n💪 Всего: -{diff} кг! {emoji}",
        "weight_total_gained": "\n📈 Всего: +{diff} кг",
        "weight_see_progress": "\n\n📊 Нажми «Мой прогресс»",
        "progress_title": "📊 Прогресс, {name}:\n\n",
        "progress_current": "⚖️ Вес: {weight} кг\n",
        "progress_goal": "🎯 Цель: {goal}\n",
        "progress_no_history": "\n💡 Нажми «Взвеситься»",
        "progress_total_lost": "💪 Сброшено: {diff} кг 🔥\n",
        "progress_total_gained": "📈 Набрано: {diff} кг\n",
        "progress_stable": "⚖️ Стабильно\n",
        "progress_days": "📅 За {days} {days_word}\n",
        "day_one": "день", "day_few": "дня", "day_many": "дней",
        "settings_title": "⚙️ Настройки:\n\n👤 {name}\n🎯 {goal}\n⚖️ {weight} кг\n📏 {height} см\n🎂 {age} лет\n🏃 {activity}\n\nreset — сбросить",
        "analyzing_1": "🔍 Смотрю...", "analyzing_2": "🤔 Хм...", "analyzing_3": "💭 Думаю...",
        "analyzing_done": "✨ Готово!",
        "photo_error": "Ошибка анализа 😔 Попробуй ещё!",
        "photo_not_recognized": "Не распознал. Попробуй другое фото.",
        "voice_listening": "🎤 Слушаю...",
        "voice_recognized": "📝 \"{text}\"",
        "voice_error": "Не распознал речь 🙂",
        "voice_process_error": "Ошибка голосового 😔",
        "reset_done": "✅ Сброшено! /start",
        "complete_registration": "Заверши регистрацию! /start",
        "hello_response": "Привет, {name}! 😊",
        "chat_error": "Ошибка. Переформулируй 🙂",
        "photo_complete_first": "Сначала /start",
        "photo_process_error": "Ошибка фото 😔",
        "help_text": "📋 /start /subscribe /status /cancel\nreset — сброс",
        "gpt_response_lang": "русском",
        "gpt_meal_plan_prompt": "План питания на день, цель: {goal}",
        "gpt_workout_prompt": "Тренировки на неделю, цель: {goal}",
    },
    "cs": {
        "choose_language": "Vyberte jazyk:",
        "greeting": "👋 Ahoj! Jsem AI dietolog.",
        "ask_name": "Jak se jmenuješ?",
        "name_invalid": "Jen jméno (2–30 znaků).",
        "welcome_back": "Vítej, {name}! 😊",
        "ask_goal": "Jaký je tvůj cíl, {name}?",
        "goal_lose": "🏃 Zhubnout", "goal_gain": "💪 Nabrat", "goal_maintain": "⚖️ Udržovat",
        "goal_lose_value": "zhubnout", "goal_gain_value": "nabrat", "goal_maintain_value": "udržovat",
        "goal_accepted": "Super! 🎯\n\nNapiš: váha, výška, věk\nNapř: 114, 182, 49",
        "wha_invalid": "Napiš: váha, výška, věk",
        "ask_activity": "Jaká aktivita?",
        "activity_low": "🛋 Nízká", "activity_medium": "🚶 Střední", "activity_high": "🏃 Vysoká",
        "activity_low_value": "nízká", "activity_medium_value": "střední", "activity_high_value": "vysoká",
        "onboarding_complete": "Skvělé! 🎉 Potřebuješ předplatné.",
        "subscription_required": "⚠️ Potřebuješ předplatné. /subscribe",
        "subscription_expired": "⚠️ Předplatné vypršelo. /subscribe",
        "choose_plan": "💳 Vyber:\n\n📦 Basic — €10/měs\n⭐ Premium — €20/měs\n\n🎁 1 den zdarma!",
        "btn_basic": "📦 Basic €10", "btn_premium": "⭐ Premium €20",
        "payment_link": "💳 Platba:\n{url}",
        "subscription_activated": "✅ Aktivováno!\n\n📦 {plan}\n📅 Do: {expires}",
        "subscription_status": "📊 Předplatné:\n\n📦 {plan}\n📅 Do: {expires}\n📸 {used}/{limit}",
        "photo_limit_reached": "⚠️ Limit ({limit}). Uprav na Premium!",
        "menu_photo": "📸 Fotka", "menu_question": "💬 Otázka",
        "menu_meal_plan": "📋 Jídelníček", "menu_workout": "💪 Tréninky",
        "menu_weigh_in": "⚖️ Zvážit", "menu_progress": "📊 Pokrok", "menu_settings": "⚙️ Nastavení",
        "photo_prompt": "📸 Pošli fotku jídla!",
        "question_prompt": "💬 Ptej se!",
        "meal_plan_loading": "{name}, tvořím plán... ⏳",
        "meal_plan_result": "📋 Plán:\n\n{plan}",
        "workout_loading": "{name}, tvořím tréninky... ⏳",
        "workout_result": "💪 Tréninky:\n\n{plan}",
        "weigh_in_prompt": "⚖️ Napiš váhu (kg)",
        "weight_invalid": "Napiš číslo",
        "weight_unrealistic": "Nereálná váha",
        "weight_stable": "⚖️ {weight} kg — stabilní! 👍",
        "weight_down": "⚖️ {weight} kg — ⬇️ -{diff} kg! {emoji}",
        "weight_up": "⚖️ {weight} kg — ⬆️ +{diff} kg 💪",
        "weight_total_lost": "\n💪 Celkem: -{diff} kg! {emoji}",
        "weight_total_gained": "\n📈 Celkem: +{diff} kg",
        "weight_see_progress": "\n\n📊 Klikni «Pokrok»",
        "progress_title": "📊 Pokrok, {name}:\n\n",
        "progress_current": "⚖️ Váha: {weight} kg\n",
        "progress_goal": "🎯 Cíl: {goal}\n",
        "progress_no_history": "\n💡 Klikni «Zvážit»",
        "progress_total_lost": "💪 Shozeno: {diff} kg 🔥\n",
        "progress_total_gained": "📈 Nabráno: {diff} kg\n",
        "progress_stable": "⚖️ Stabilní\n",
        "progress_days": "📅 Za {days} {days_word}\n",
        "day_one": "den", "day_few": "dny", "day_many": "dní",
        "settings_title": "⚙️ Nastavení:\n\n👤 {name}\n🎯 {goal}\n⚖️ {weight}\n📏 {height}\n🎂 {age}\n🏃 {activity}\n\nreset",
        "analyzing_1": "🔍 Dívám...", "analyzing_2": "🤔 Hmm...", "analyzing_3": "💭 Myslím...",
        "analyzing_done": "✨ Hotovo!",
        "photo_error": "Chyba 😔",
        "photo_not_recognized": "Nerozpoznáno.",
        "voice_listening": "🎤 Poslouchám...",
        "voice_recognized": "📝 \"{text}\"",
        "voice_error": "Nerozpoznáno 🙂",
        "voice_process_error": "Chyba 😔",
        "reset_done": "✅ Reset! /start",
        "complete_registration": "Dokonči! /start",
        "hello_response": "Ahoj, {name}! 😊",
        "chat_error": "Chyba 🙂",
        "photo_complete_first": "Nejprve /start",
        "photo_process_error": "Chyba 😔",
        "help_text": "📋 /start /subscribe /status /cancel",
        "gpt_response_lang": "čeština",
        "gpt_meal_plan_prompt": "Jídelníček na den, cíl: {goal}",
        "gpt_workout_prompt": "Tréninky na týden, cíl: {goal}",
    },
    "en": {
        "choose_language": "Choose language:",
        "greeting": "👋 Hi! I'm your AI dietitian.",
        "ask_name": "What's your name?",
        "name_invalid": "Just name (2–30 chars).",
        "welcome_back": "Welcome, {name}! 😊",
        "ask_goal": "What's your goal, {name}?",
        "goal_lose": "🏃 Lose", "goal_gain": "💪 Gain", "goal_maintain": "⚖️ Maintain",
        "goal_lose_value": "lose weight", "goal_gain_value": "gain muscle", "goal_maintain_value": "maintain",
        "goal_accepted": "Great! 🎯\n\nWrite: weight, height, age\nE.g: 114, 182, 49",
        "wha_invalid": "Write: weight, height, age",
        "ask_activity": "Activity level?",
        "activity_low": "🛋 Low", "activity_medium": "🚶 Moderate", "activity_high": "🏃 High",
        "activity_low_value": "low", "activity_medium_value": "moderate", "activity_high_value": "high",
        "onboarding_complete": "Excellent! 🎉 Subscription required.",
        "subscription_required": "⚠️ Subscription required. /subscribe",
        "subscription_expired": "⚠️ Subscription expired. /subscribe",
        "choose_plan": "💳 Choose:\n\n📦 Basic — €10/mo\n⭐ Premium — €20/mo\n\n🎁 1 day free!",
        "btn_basic": "📦 Basic €10", "btn_premium": "⭐ Premium €20",
        "payment_link": "💳 Pay:\n{url}",
        "subscription_activated": "✅ Activated!\n\n📦 {plan}\n📅 Until: {expires}",
        "subscription_status": "📊 Subscription:\n\n📦 {plan}\n📅 Until: {expires}\n📸 {used}/{limit}",
        "photo_limit_reached": "⚠️ Limit ({limit}). Upgrade to Premium!",
        "menu_photo": "📸 Photo", "menu_question": "💬 Question",
        "menu_meal_plan": "📋 Meal plan", "menu_workout": "💪 Workouts",
        "menu_weigh_in": "⚖️ Weigh in", "menu_progress": "📊 Progress", "menu_settings": "⚙️ Settings",
        "photo_prompt": "📸 Send food photo!",
        "question_prompt": "💬 Ask anything!",
        "meal_plan_loading": "{name}, creating plan... ⏳",
        "meal_plan_result": "📋 Plan:\n\n{plan}",
        "workout_loading": "{name}, creating workouts... ⏳",
        "workout_result": "💪 Workouts:\n\n{plan}",
        "weigh_in_prompt": "⚖️ Write weight (kg)",
        "weight_invalid": "Write number",
        "weight_unrealistic": "Unrealistic weight",
        "weight_stable": "⚖️ {weight} kg — stable! 👍",
        "weight_down": "⚖️ {weight} kg — ⬇️ -{diff} kg! {emoji}",
        "weight_up": "⚖️ {weight} kg — ⬆️ +{diff} kg 💪",
        "weight_total_lost": "\n💪 Total: -{diff} kg! {emoji}",
        "weight_total_gained": "\n📈 Total: +{diff} kg",
        "weight_see_progress": "\n\n📊 Press «Progress»",
        "progress_title": "📊 Progress, {name}:\n\n",
        "progress_current": "⚖️ Weight: {weight} kg\n",
        "progress_goal": "🎯 Goal: {goal}\n",
        "progress_no_history": "\n💡 Press «Weigh in»",
        "progress_total_lost": "💪 Lost: {diff} kg 🔥\n",
        "progress_total_gained": "📈 Gained: {diff} kg\n",
        "progress_stable": "⚖️ Stable\n",
        "progress_days": "📅 Over {days} {days_word}\n",
        "day_one": "day", "day_few": "days", "day_many": "days",
        "settings_title": "⚙️ Settings:\n\n👤 {name}\n🎯 {goal}\n⚖️ {weight}\n📏 {height}\n🎂 {age}\n🏃 {activity}\n\nreset",
        "analyzing_1": "🔍 Looking...", "analyzing_2": "🤔 Hmm...", "analyzing_3": "💭 Thinking...",
        "analyzing_done": "✨ Done!",
        "photo_error": "Error 😔",
        "photo_not_recognized": "Not recognized.",
        "voice_listening": "🎤 Listening...",
        "voice_recognized": "📝 \"{text}\"",
        "voice_error": "Not recognized 🙂",
        "voice_process_error": "Error 😔",
        "reset_done": "✅ Reset! /start",
        "complete_registration": "Complete! /start",
        "hello_response": "Hi, {name}! 😊",
        "chat_error": "Error 🙂",
        "photo_complete_first": "First /start",
        "photo_process_error": "Error 😔",
        "help_text": "📋 /start /subscribe /status /cancel",
        "gpt_response_lang": "English",
        "gpt_meal_plan_prompt": "Meal plan for day, goal: {goal}",
        "gpt_workout_prompt": "Workouts for week, goal: {goal}",
    }
}

def get_text_lang(lang, key, **kwargs):
    texts = TEXTS.get(lang, TEXTS["ru"])
    text = texts.get(key, TEXTS["ru"].get(key, ""))
    return text.format(**kwargs) if kwargs else text

def normalize_text(s): return (s or "").strip()

def parse_weight_height_age(text):
    nums = re.findall(r"\d{1,3}", normalize_text(text))
    if len(nums) < 3: return None
    w, h, a = int(nums[0]), int(nums[1]), int(nums[2])
    if not (30 <= w <= 350) or not (120 <= h <= 230) or not (10 <= a <= 100): return None
    return (w, h, a)

def is_reset_command(text):
    return normalize_text(text).lower() in {"reset", "/reset", "сброс", "заново", "resetovat"}

async def clear_user_data(user_id):
    try: await delete_all_facts(user_id)
    except: pass

async def profile_missing(user_id):
    if not await get_fact(user_id, "language"): return "language"
    if not await get_fact(user_id, "name"): return "name"
    if not await get_fact(user_id, "goal"): return "goal"
    if not await get_fact(user_id, "weight_kg") or not await get_fact(user_id, "height_cm") or not await get_fact(user_id, "age"): return "wha"
    if not await get_fact(user_id, "activity"): return "activity"
    return None

def create_main_menu(lang):
    return ReplyKeyboardMarkup(keyboard=[
        [KeyboardButton(text=get_text_lang(lang, "menu_photo")), KeyboardButton(text=get_text_lang(lang, "menu_question"))],
        [KeyboardButton(text=get_text_lang(lang, "menu_meal_plan")), KeyboardButton(text=get_text_lang(lang, "menu_workout"))],
        [KeyboardButton(text=get_text_lang(lang, "menu_weigh_in")), KeyboardButton(text=get_text_lang(lang, "menu_progress"))],
        [KeyboardButton(text=get_text_lang(lang, "menu_settings"))]
    ], resize_keyboard=True)

ALL_MENU_PHOTO = [TEXTS["ru"]["menu_photo"], TEXTS["cs"]["menu_photo"], TEXTS["en"]["menu_photo"]]
ALL_MENU_QUESTION = [TEXTS["ru"]["menu_question"], TEXTS["cs"]["menu_question"], TEXTS["en"]["menu_question"]]
ALL_MENU_MEAL_PLAN = [TEXTS["ru"]["menu_meal_plan"], TEXTS["cs"]["menu_meal_plan"], TEXTS["en"]["menu_meal_plan"]]
ALL_MENU_WORKOUT = [TEXTS["ru"]["menu_workout"], TEXTS["cs"]["menu_workout"], TEXTS["en"]["menu_workout"]]
ALL_MENU_WEIGH_IN = [TEXTS["ru"]["menu_weigh_in"], TEXTS["cs"]["menu_weigh_in"], TEXTS["en"]["menu_weigh_in"]]
ALL_MENU_PROGRESS = [TEXTS["ru"]["menu_progress"], TEXTS["cs"]["menu_progress"], TEXTS["en"]["menu_progress"]]
ALL_MENU_SETTINGS = [TEXTS["ru"]["menu_settings"], TEXTS["cs"]["menu_settings"], TEXTS["en"]["menu_settings"]]

def get_days_word(lang, days):
    if lang == "ru": return TEXTS["ru"]["day_one"] if days == 1 else TEXTS["ru"]["day_few"] if 2 <= days <= 4 else TEXTS["ru"]["day_many"]
    elif lang == "cs": return TEXTS["cs"]["day_one"] if days == 1 else TEXTS["cs"]["day_few"] if 2 <= days <= 4 else TEXTS["cs"]["day_many"]
    return TEXTS["en"]["day_one"] if days == 1 else TEXTS["en"]["day_many"]

async def get_subscription(user_id):
    sub_json = await get_fact(user_id, "subscription")
    if not sub_json: return None
    try: return json.loads(sub_json)
    except: return None

async def set_subscription(user_id, plan, expires_at, stripe_customer_id=None, stripe_subscription_id=None):
    await set_fact(user_id, "subscription", json.dumps({
        "plan": plan, "expires_at": expires_at.isoformat(),
        "stripe_customer_id": stripe_customer_id, "stripe_subscription_id": stripe_subscription_id,
        "created_at": datetime.now().isoformat()
    }))

async def check_subscription_valid(user_id):
    if user_id in ADMIN_IDS: return True, "admin"
    sub = await get_subscription(user_id)
    if not sub: return False, "subscription_required"
    if datetime.now() > datetime.fromisoformat(sub["expires_at"]): return False, "subscription_expired"
    return True, sub["plan"]

async def get_daily_photo_count(user_id):
    today = datetime.now().strftime("%Y-%m-%d")
    usage_json = await get_fact(user_id, "daily_usage")
    if not usage_json: return 0
    try:
        usage = json.loads(usage_json)
        return usage.get("photo_count", 0) if usage.get("date") == today else 0
    except: return 0

async def increment_photo_count(user_id):
    today = datetime.now().strftime("%Y-%m-%d")
    usage_json = await get_fact(user_id, "daily_usage")
    try:
        usage = json.loads(usage_json) if usage_json else {}
        if usage.get("date") == today: usage["photo_count"] = usage.get("photo_count", 0) + 1
        else: usage = {"date": today, "photo_count": 1}
    except: usage = {"date": today, "photo_count": 1}
    await set_fact(user_id, "daily_usage", json.dumps(usage))

async def can_analyze_photo(user_id):
    if user_id in ADMIN_IDS: return True, None
    is_valid, plan_or_error = await check_subscription_valid(user_id)
    if not is_valid: return False, plan_or_error
    if plan_or_error in ["premium", "trial", "admin", "granted"]: return True, None
    if await get_daily_photo_count(user_id) >= BASIC_DAILY_PHOTO_LIMIT: return False, "photo_limit_reached"
    return True, None

async def create_checkout_session(user_id, plan, lang):
    try:
        session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=[{"price": STRIPE_PRICE_BASIC if plan == "basic" else STRIPE_PRICE_PREMIUM, "quantity": 1}],
            mode="subscription",
            success_url=f"https://t.me/dietolog_ai_2025_bot?start=payment_success",
            cancel_url=f"https://t.me/dietolog_ai_2025_bot?start=payment_cancel",
            metadata={"user_id": str(user_id), "plan": plan},
            subscription_data={"trial_period_days": TRIAL_DAYS, "metadata": {"user_id": str(user_id), "plan": plan}}
        )
        return session.url
    except Exception as e:
        logger.error(f"Checkout error: {e}")
        return None

async def handle_stripe_webhook(request):
    try:
        payload = await request.read()
        sig_header = request.headers.get("Stripe-Signature")
        logger.info(f"Stripe webhook, size: {len(payload)}")
        if not sig_header: return web.Response(status=400, text="No signature")
        try: event = stripe.Webhook.construct_event(payload, sig_header, STRIPE_WEBHOOK_SECRET)
        except Exception as e:
            logger.error(f"Webhook error: {e}")
            return web.Response(status=400, text="Error")
        logger.info(f"Event: {event['type']}")
        if event["type"] == "checkout.session.completed":
            session = event["data"]["object"]
            user_id = int(session["metadata"].get("user_id", 0))
            plan = session["metadata"].get("plan", "basic")
            if user_id:
                expires_at = datetime.now() + timedelta(days=31)
                await set_subscription(user_id, plan, expires_at, session.get("customer"), session.get("subscription"))
                user_lang = await get_fact(user_id, "language") or "ru"
                try: await bot.send_message(user_id, get_text_lang(user_lang, "subscription_activated", plan=plan.capitalize(), expires=expires_at.strftime("%d.%m.%Y")), reply_markup=create_main_menu(user_lang))
                except: pass
        elif event["type"] == "customer.subscription.updated":
            sub = event["data"]["object"]
            user_id = int(sub["metadata"].get("user_id", 0))
            if user_id and sub["status"] == "active":
                await set_subscription(user_id, sub["metadata"].get("plan", "basic"), datetime.fromtimestamp(sub["current_period_end"]), sub.get("customer"), sub.get("id"))
        elif event["type"] == "customer.subscription.deleted":
            sub = event["data"]["object"]
            user_id = int(sub["metadata"].get("user_id", 0))
            if user_id: await set_subscription(user_id, "cancelled", datetime.now())
        return web.Response(status=200, text="OK")
    except Exception as e:
        logger.error(f"Stripe error: {e}", exc_info=True)
        return web.Response(status=500)

def format_food_card(name, cal, prot, fat, carbs, weight, lang):
    h = {"ru": "АНАЛИЗ", "cs": "ANALÝZA", "en": "ANALYSIS"}.get(lang, "АНАЛИЗ")
    return f"╔════════════════════╗\n║ 📊 {h}\n╠════════════════════╣\n║ 🍽 {name}\n║ ⚖️ ~{weight}г\n║ 🔥 {cal} ккал\n║ 🥩 {prot}г 🧈 {fat}г 🍞 {carbs}г\n╚════════════════════╝"

async def analyze_food_photo(photo_bytes, user_id):
    try:
        user_lang = await get_fact(user_id, "language") or "ru"
        base64_image = base64.b64encode(photo_bytes).decode("utf-8")
        resp = await openai_client.chat.completions.create(
            model=GPT_MODEL,
            messages=[
                {"role": "system", "content": f"Ты диетолог. Анализируй фото. Отвечай на {get_text_lang(user_lang, 'gpt_response_lang')}. Формат: НАЗВАНИЕ: [блюдо] ПОРЦИЯ: [г] ККАЛ: [число] БЕЛКИ: [г] ЖИРЫ: [г] УГЛЕВОДЫ: [г] РЕКОМЕНДАЦИИ: [советы]"},
                {"role": "user", "content": [{"type": "text", "text": "Анализируй"}, {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{base64_image}", "detail": "high"}}]}
            ],
            max_tokens=1500, temperature=0.3,
        )
        result = (resp.choices[0].message.content or "").strip()
        if not result: return get_text_lang(user_lang, "photo_not_recognized")
        food_name, weight_g, cal, prot, fat, carbs = "Блюдо", 250, 200, 10.0, 10.0, 20.0
        for line in result.split('\n'):
            ll = line.lower()
            if 'название:' in ll or 'name:' in ll: food_name = line.split(':', 1)[-1].strip()
            elif 'порция:' in ll or 'portion:' in ll:
                nums = re.findall(r'(\d+)', line)
                if nums: weight_g = max(int(nums[0]), 50)
            elif 'ккал:' in ll or 'kcal:' in ll:
                nums = re.findall(r'(\d+)', line)
                if nums: cal = int(nums[0])
            elif 'белки:' in ll or 'protein:' in ll:
                nums = re.findall(r'(\d+\.?\d*)', line)
                if nums: prot = float(nums[0])
            elif 'жиры:' in ll or 'fat:' in ll:
                nums = re.findall(r'(\d+\.?\d*)', line)
                if nums: fat = float(nums[0])
            elif 'углеводы:' in ll or 'carbs:' in ll:
                nums = re.findall(r'(\d+\.?\d*)', line)
                if nums: carbs = float(nums[0])
        return format_food_card(food_name, cal, prot, fat, carbs, weight_g, user_lang)
    except Exception as e:
        logger.error(f"Photo error: {e}")
        return get_text_lang(await get_fact(user_id, "language") or "ru", "photo_error")

async def chat_reply(user_text, user_id):
    try:
        user_lang = await get_fact(user_id, "language") or "ru"
        name = await get_fact(user_id, "name") or ""
        goal = await get_fact(user_id, "goal") or ""
        resp = await openai_client.chat.completions.create(
            model=GPT_MODEL,
            messages=[
                {"role": "system", "content": f"Ты AI-диетолог. Отвечай на {get_text_lang(user_lang, 'gpt_response_lang')}. Профиль: {name}, цель: {goal}. Кратко."},
                {"role": "user", "content": user_text}
            ],
            max_tokens=500, temperature=0.7,
        )
        return (resp.choices[0].message.content or "").strip()
    except: return get_text_lang(await get_fact(user_id, "language") or "ru", "chat_error")

@dp.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    user_id = message.from_user.id
    await state.clear()
    args = message.text.split()
    if len(args) > 1:
        user_lang = await get_fact(user_id, "language") or "ru"
        if args[1] == "payment_success":
            is_valid, _ = await check_subscription_valid(user_id)
            if is_valid:
                name = await get_fact(user_id, "name") or "друг"
                await message.answer(f"🎉 {name}, подписка активирована!", reply_markup=create_main_menu(user_lang))
            else:
                await message.answer("⏳ Обрабатывается... Подожди и /start")
            return
        elif args[1] == "payment_cancel":
            await message.answer("❌ Оплата отменена. /subscribe")
            return
    missing = await profile_missing(user_id)
    if not missing:
        user_lang = await get_fact(user_id, "language") or "ru"
        name = await get_fact(user_id, "name") or "друг"
        is_valid, err = await check_subscription_valid(user_id)
        if is_valid: await message.answer(get_text_lang(user_lang, "welcome_back", name=name), reply_markup=create_main_menu(user_lang))
        else: await message.answer(get_text_lang(user_lang, err), reply_markup=ReplyKeyboardRemove())
        return
    if missing == "language":
        kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🇷🇺 Русский", callback_data="lang_ru"), InlineKeyboardButton(text="🇨🇿 Čeština", callback_data="lang_cs")], [InlineKeyboardButton(text="🇬🇧 English", callback_data="lang_en")]])
        await message.answer("Выбери язык:", reply_markup=kb)
        await state.set_state(LanguageSelection.waiting_language)
        return
    user_lang = await get_fact(user_id, "language") or "ru"
    await message.answer(get_text_lang(user_lang, "greeting"), reply_markup=ReplyKeyboardRemove())
    await asyncio.sleep(1)
    await message.answer(get_text_lang(user_lang, "ask_name"))
    await state.set_state(Onboarding.waiting_name)

@dp.message(Command("subscribe"))
async def cmd_subscribe(message: Message):
    user_lang = await get_fact(message.from_user.id, "language") or "ru"
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=get_text_lang(user_lang, "btn_basic"), callback_data="sub_basic")], [InlineKeyboardButton(text=get_text_lang(user_lang, "btn_premium"), callback_data="sub_premium")]])
    await message.answer(get_text_lang(user_lang, "choose_plan"), reply_markup=kb, parse_mode="Markdown")

@dp.callback_query(F.data.in_(["sub_basic", "sub_premium"]))
async def handle_sub(callback: CallbackQuery):
    user_id = callback.from_user.id
    user_lang = await get_fact(user_id, "language") or "ru"
    plan = "basic" if callback.data == "sub_basic" else "premium"
    await callback.answer()
    await callback.message.edit_reply_markup(reply_markup=None)
    url = await create_checkout_session(user_id, plan, user_lang)
    if url: await callback.message.answer(get_text_lang(user_lang, "payment_link", url=url))
    else: await callback.message.answer(get_text_lang(user_lang, "chat_error"))

@dp.message(Command("status"))
async def cmd_status(message: Message):
    user_id = message.from_user.id
    user_lang = await get_fact(user_id, "language") or "ru"
    if user_id in ADMIN_IDS:
        await message.answer("👑 АДМИН — безлимит")
        return
    sub = await get_subscription(user_id)
    if not sub:
        await message.answer(get_text_lang(user_lang, "subscription_required"))
        return
    used = await get_daily_photo_count(user_id)
    limit = "∞" if sub.get("plan") in ["premium", "granted"] else str(BASIC_DAILY_PHOTO_LIMIT)
    await message.answer(get_text_lang(user_lang, "subscription_status", plan=sub.get("plan", "").capitalize(), expires=datetime.fromisoformat(sub["expires_at"]).strftime("%d.%m.%Y"), used=used, limit=limit))

@dp.message(Command("cancel"))
async def cmd_cancel(message: Message):
    user_id = message.from_user.id
    sub = await get_subscription(user_id)
    if not sub or not sub.get("stripe_customer_id"):
        await message.answer("❌ Нет подписки для отмены")
        return
    try:
        portal = stripe.billing_portal.Session.create(customer=sub["stripe_customer_id"], return_url="https://t.me/dietolog_ai_2025_bot")
        await message.answer(f"🔗 Управление:\n{portal.url}")
    except: await message.answer("❌ Ошибка")

@dp.message(Command("help"))
async def cmd_help(message: Message):
    await message.answer(get_text_lang(await get_fact(message.from_user.id, "language") or "ru", "help_text"))

@dp.message(Command("grant"))
async def cmd_grant(message: Message):
    if message.from_user.id not in ADMIN_IDS: return
    parts = message.text.split()
    if len(parts) < 2:
        await message.answer("/grant <user_id>")
        return
    try:
        target = int(parts[1])
        await set_subscription(target, "granted", datetime(2099, 12, 31))
        await message.answer(f"✅ Доступ выдан {target}")
    except: await message.answer("❌ Ошибка")

@dp.message(Command("revoke"))
async def cmd_revoke(message: Message):
    if message.from_user.id not in ADMIN_IDS: return
    parts = message.text.split()
    if len(parts) < 2: return
    try:
        target = int(parts[1])
        await set_subscription(target, "revoked", datetime.now())
        await message.answer(f"✅ Отозвано {target}")
    except: pass

@dp.callback_query(LanguageSelection.waiting_language)
async def lang_selected(callback: CallbackQuery, state: FSMContext):
    lang = {"lang_ru": "ru", "lang_cs": "cs", "lang_en": "en"}.get(callback.data, "ru")
    await set_fact(callback.from_user.id, "language", lang)
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.answer()
    await callback.message.answer(get_text_lang(lang, "greeting"), reply_markup=ReplyKeyboardRemove())
    await asyncio.sleep(1)
    await callback.message.answer(get_text_lang(lang, "ask_name"))
    await state.set_state(Onboarding.waiting_name)

@dp.message(Onboarding.waiting_name, F.text)
async def onb_name(message: Message, state: FSMContext):
    if is_reset_command(message.text):
        await clear_user_data(message.from_user.id)
        await state.clear()
        await message.answer(get_text_lang(await get_fact(message.from_user.id, "language") or "ru", "reset_done"), reply_markup=ReplyKeyboardRemove())
        return
    user_id = message.from_user.id
    user_lang = await get_fact(user_id, "language") or "ru"
    await ensure_user_exists(user_id)
    name = normalize_text(message.text)
    if len(name) < 2 or len(name) > 30:
        await message.answer(get_text_lang(user_lang, "name_invalid"))
        return
    await set_fact(user_id, "name", name)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=get_text_lang(user_lang, "goal_lose"), callback_data="goal_lose"), InlineKeyboardButton(text=get_text_lang(user_lang, "goal_gain"), callback_data="goal_gain")], [InlineKeyboardButton(text=get_text_lang(user_lang, "goal_maintain"), callback_data="goal_maintain")]])
    await message.answer(get_text_lang(user_lang, "ask_goal", name=name), reply_markup=kb)
    await state.set_state(Onboarding.waiting_goal)

@dp.callback_query(Onboarding.waiting_goal)
async def onb_goal_cb(callback: CallbackQuery, state: FSMContext):
    user_lang = await get_fact(callback.from_user.id, "language") or "ru"
    goal = get_text_lang(user_lang, {"goal_lose": "goal_lose_value", "goal_gain": "goal_gain_value", "goal_maintain": "goal_maintain_value"}.get(callback.data, "goal_maintain_value"))
    await set_fact(callback.from_user.id, "goal", goal)
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.answer()
    await callback.message.answer(get_text_lang(user_lang, "goal_accepted"))
    await state.set_state(Onboarding.waiting_whA)

@dp.message(Onboarding.waiting_whA, F.text)
async def onb_wha(message: Message, state: FSMContext):
    if is_reset_command(message.text):
        await clear_user_data(message.from_user.id)
        await state.clear()
        await message.answer(get_text_lang(await get_fact(message.from_user.id, "language") or "ru", "reset_done"), reply_markup=ReplyKeyboardRemove())
        return
    user_id = message.from_user.id
    user_lang = await get_fact(user_id, "language") or "ru"
    parsed = parse_weight_height_age(message.text)
    if not parsed:
        await message.answer(get_text_lang(user_lang, "wha_invalid"))
        return
    w, h, a = parsed
    await set_facts(user_id, {"weight_kg": str(w), "height_cm": str(h), "age": str(a)})
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=get_text_lang(user_lang, "activity_low"), callback_data="activity_low"), InlineKeyboardButton(text=get_text_lang(user_lang, "activity_medium"), callback_data="activity_medium")], [InlineKeyboardButton(text=get_text_lang(user_lang, "activity_high"), callback_data="activity_high")]])
    await message.answer(get_text_lang(user_lang, "ask_activity"), reply_markup=kb)
    await state.set_state(Onboarding.waiting_activity)

@dp.callback_query(Onboarding.waiting_activity)
async def onb_act_cb(callback: CallbackQuery, state: FSMContext):
    user_id = callback.from_user.id
    user_lang = await get_fact(user_id, "language") or "ru"
    act = get_text_lang(user_lang, {"activity_low": "activity_low_value", "activity_medium": "activity_medium_value", "activity_high": "activity_high_value"}.get(callback.data, "activity_medium_value"))
    await set_facts(user_id, {"activity": act, "job": ""})
    await callback.message.edit_reply_markup(reply_markup=None)
    await state.clear()
    await callback.answer()
    if user_id in ADMIN_IDS:
        await callback.message.answer("🎉 Готово! Ты админ — безлимит!", reply_markup=create_main_menu(user_lang))
        return
    await callback.message.answer(get_text_lang(user_lang, "onboarding_complete"))
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=get_text_lang(user_lang, "btn_basic"), callback_data="sub_basic")], [InlineKeyboardButton(text=get_text_lang(user_lang, "btn_premium"), callback_data="sub_premium")]])
    await callback.message.answer(get_text_lang(user_lang, "choose_plan"), reply_markup=kb, parse_mode="Markdown")

@dp.message(F.photo)
async def handle_photo(message: Message, state: FSMContext):
    user_id = message.from_user.id
    user_lang = await get_fact(user_id, "language") or "ru"
    if await profile_missing(user_id):
        await message.answer(get_text_lang(user_lang, "photo_complete_first"))
        return
    can, err = await can_analyze_photo(user_id)
    if not can:
        await message.answer(get_text_lang(user_lang, err, limit=BASIC_DAILY_PHOTO_LIMIT) if err == "photo_limit_reached" else get_text_lang(user_lang, err))
        return
    status = await message.answer(get_text_lang(user_lang, "analyzing_1"))
    try:
        await asyncio.sleep(1)
        await status.edit_text(get_text_lang(user_lang, "analyzing_2"))
        photo = message.photo[-1]
        file = await bot.get_file(photo.file_id)
        buf = BytesIO()
        await bot.download_file(file.file_path, destination=buf)
        result = await analyze_food_photo(buf.getvalue(), user_id)
        await increment_photo_count(user_id)
        await status.delete()
        await message.answer(result)
    except Exception as e:
        logger.error(f"Photo: {e}")
        try: await status.delete()
        except: pass
        await message.answer(get_text_lang(user_lang, "photo_process_error"))

@dp.message(F.voice)
async def handle_voice(message: Message, state: FSMContext):
    user_id = message.from_user.id
    user_lang = await get_fact(user_id, "language") or "ru"
    is_valid, err = await check_subscription_valid(user_id)
    if not is_valid:
        await message.answer(get_text_lang(user_lang, err))
        return
    status = await message.answer(get_text_lang(user_lang, "voice_listening"))
    try:
        file = await bot.get_file(message.voice.file_id)
        buf = BytesIO()
        await bot.download_file(file.file_path, destination=buf)
        buf.seek(0)
        buf.name = "voice.ogg"
        trans = await openai_client.audio.transcriptions.create(model="whisper-1", file=buf, language=user_lang)
        text = trans.text.strip()
        await status.delete()
        if not text:
            await message.answer(get_text_lang(user_lang, "voice_error"))
            return
        await message.answer(get_text_lang(user_lang, "voice_recognized", text=text))
        reply = await chat_reply(text, user_id)
        await message.answer(reply)
    except Exception as e:
        logger.error(f"Voice: {e}")
        try: await status.delete()
        except: pass
        await message.answer(get_text_lang(user_lang, "voice_process_error"))

@dp.message(F.text.in_(ALL_MENU_WEIGH_IN))
async def menu_weigh(message: Message, state: FSMContext):
    user_lang = await get_fact(message.from_user.id, "language") or "ru"
    is_valid, err = await check_subscription_valid(message.from_user.id)
    if not is_valid:
        await message.answer(get_text_lang(user_lang, err))
        return
    await message.answer(get_text_lang(user_lang, "weigh_in_prompt"))
    await state.set_state(WeightTracking.waiting_weight)

@dp.message(WeightTracking.waiting_weight, F.text)
async def proc_weight(message: Message, state: FSMContext):
    user_id = message.from_user.id
    user_lang = await get_fact(user_id, "language") or "ru"
    nums = re.findall(r'\d+\.?\d*', message.text)
    if not nums:
        await message.answer(get_text_lang(user_lang, "weight_invalid"))
        return
    new_w = float(nums[0])
    if new_w < 30 or new_w > 350:
        await message.answer(get_text_lang(user_lang, "weight_unrealistic"))
        return
    old_w_str = await get_fact(user_id, "weight_kg")
    old_w = float(old_w_str) if old_w_str else new_w
    await set_fact(user_id, "weight_kg", str(new_w))
    diff = old_w - new_w
    if abs(diff) < 0.1: result = get_text_lang(user_lang, "weight_stable", weight=new_w)
    elif diff > 0: result = get_text_lang(user_lang, "weight_down", weight=new_w, diff=f"{diff:.1f}", emoji="🔥" if diff >= 2 else "✨")
    else: result = get_text_lang(user_lang, "weight_up", weight=new_w, diff=f"{abs(diff):.1f}")
    result += get_text_lang(user_lang, "weight_see_progress")
    await state.clear()
    await message.answer(result)

@dp.message(F.text.in_(ALL_MENU_PHOTO))
async def menu_photo(message: Message):
    user_lang = await get_fact(message.from_user.id, "language") or "ru"
    is_valid, err = await check_subscription_valid(message.from_user.id)
    if not is_valid:
        await message.answer(get_text_lang(user_lang, err))
        return
    await message.answer(get_text_lang(user_lang, "photo_prompt"))

@dp.message(F.text.in_(ALL_MENU_QUESTION))
async def menu_question(message: Message):
    user_lang = await get_fact(message.from_user.id, "language") or "ru"
    is_valid, err = await check_subscription_valid(message.from_user.id)
    if not is_valid:
        await message.answer(get_text_lang(user_lang, err))
        return
    await message.answer(get_text_lang(user_lang, "question_prompt"))

@dp.message(F.text.in_(ALL_MENU_MEAL_PLAN))
async def menu_meal(message: Message):
    user_id = message.from_user.id
    user_lang = await get_fact(user_id, "language") or "ru"
    is_valid, err = await check_subscription_valid(user_id)
    if not is_valid:
        await message.answer(get_text_lang(user_lang, err))
        return
    name = await get_fact(user_id, "name") or "друг"
    goal = await get_fact(user_id, "goal") or ""
    await message.answer(get_text_lang(user_lang, "meal_plan_loading", name=name, goal=goal))
    reply = await chat_reply(get_text_lang(user_lang, "gpt_meal_plan_prompt", goal=goal), user_id)
    await message.answer(get_text_lang(user_lang, "meal_plan_result", plan=reply))

@dp.message(F.text.in_(ALL_MENU_WORKOUT))
async def menu_workout(message: Message):
    user_id = message.from_user.id
    user_lang = await get_fact(user_id, "language") or "ru"
    is_valid, err = await check_subscription_valid(user_id)
    if not is_valid:
        await message.answer(get_text_lang(user_lang, err))
        return
    name = await get_fact(user_id, "name") or "друг"
    goal = await get_fact(user_id, "goal") or ""
    await message.answer(get_text_lang(user_lang, "workout_loading", name=name, goal=goal))
    reply = await chat_reply(get_text_lang(user_lang, "gpt_workout_prompt", goal=goal), user_id)
    await message.answer(get_text_lang(user_lang, "workout_result", plan=reply))

@dp.message(F.text.in_(ALL_MENU_PROGRESS))
async def menu_progress(message: Message):
    user_id = message.from_user.id
    user_lang = await get_fact(user_id, "language") or "ru"
    name = await get_fact(user_id, "name") or "друг"
    weight = await get_fact(user_id, "weight_kg") or "?"
    goal = await get_fact(user_id, "goal") or "?"
    progress = get_text_lang(user_lang, "progress_title", name=name)
    progress += get_text_lang(user_lang, "progress_current", weight=weight)
    progress += get_text_lang(user_lang, "progress_goal", goal=goal)
    await message.answer(progress)

@dp.message(F.text.in_(ALL_MENU_SETTINGS))
async def menu_settings(message: Message):
    user_id = message.from_user.id
    user_lang = await get_fact(user_id, "language") or "ru"
    await message.answer(get_text_lang(user_lang, "settings_title",
        name=await get_fact(user_id, "name") or "?",
        goal=await get_fact(user_id, "goal") or "?",
        weight=await get_fact(user_id, "weight_kg") or "?",
        height=await get_fact(user_id, "height_cm") or "?",
        age=await get_fact(user_id, "age") or "?",
        activity=await get_fact(user_id, "activity") or "?"
    ))

@dp.message(F.text)
async def handle_text(message: Message, state: FSMContext):
    if is_reset_command(message.text):
        await clear_user_data(message.from_user.id)
        await state.clear()
        await message.answer(get_text_lang(await get_fact(message.from_user.id, "language") or "ru", "reset_done"), reply_markup=ReplyKeyboardRemove())
        return
    user_id = message.from_user.id
    current = await state.get_state()
    if current: return
    missing = await profile_missing(user_id)
    if missing:
        if missing == "language":
            kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="🇷🇺 Русский", callback_data="lang_ru"), InlineKeyboardButton(text="🇨🇿 Čeština", callback_data="lang_cs")], [InlineKeyboardButton(text="🇬🇧 English", callback_data="lang_en")]])
            await message.answer("Выбери язык:", reply_markup=kb)
            await state.set_state(LanguageSelection.waiting_language)
            return
        user_lang = await get_fact(user_id, "language") or "ru"
        await message.answer(get_text_lang(user_lang, "greeting"), reply_markup=ReplyKeyboardRemove())
        await asyncio.sleep(1)
        await message.answer(get_text_lang(user_lang, "ask_name"))
        await state.set_state(Onboarding.waiting_name)
        return
    user_lang = await get_fact(user_id, "language") or "ru"
    is_valid, err = await check_subscription_valid(user_id)
    if not is_valid:
        await message.answer(get_text_lang(user_lang, err))
        return
    text = message.text.lower()
    if any(x in text for x in ["привет", "hello", "hi", "ahoj"]):
        name = await get_fact(user_id, "name") or "друг"
        await message.answer(get_text_lang(user_lang, "hello_response", name=name), reply_markup=create_main_menu(user_lang))
        return
    reply = await chat_reply(message.text, user_id)
    await message.answer(reply)

async def health_check(request):
    return web.Response(text="OK")

async def on_startup(app):
    await init_db()
    logger.info("✅ DB initialized")
    if WEBHOOK_URL:
        await bot.set_webhook(url=WEBHOOK_URL, drop_pending_updates=True, allowed_updates=["message", "callback_query"])
        logger.info(f"✅ Webhook: {WEBHOOK_URL}")
    else:
        logger.warning("⚠️ No WEBHOOK_HOST")

async def on_shutdown(app):
    try: await bot.delete_webhook()
    except: pass
    try: await bot.session.close()
    except: pass
    try: await http_client.aclose()
    except: pass

def main():
    logger.info(f"🚀 Starting... Port={WEB_SERVER_PORT} Webhook={WEBHOOK_URL}")
    app = web.Application()
    app.router.add_get("/", health_check)
    app.router.add_get("/health", health_check)
    app.router.add_post("/stripe/webhook", handle_stripe_webhook)
    handler = SimpleRequestHandler(dispatcher=dp, bot=bot)
    handler.register(app, path=WEBHOOK_PATH)
    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)
    web.run_app(app, host="0.0.0.0", port=WEB_SERVER_PORT)

if __name__ == "__main__":
    main()
