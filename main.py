#!/usr/bin/env python3
"""
Telegram Dietitian Bot - С ПОДПИСКАМИ STRIPE
✅ Два тарифа: Basic (€10) и Premium (€20)
✅ 1 день бесплатный пробный период
✅ Лимит фото для Basic: 10/день
✅ Premium: безлимит
✅ Мультиязычность (RU/CS/EN)
"""

import asyncio
import logging
import base64
import re
import json
import stripe
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

from config import (
    TELEGRAM_TOKEN, OPENAI_API_KEY, GPT_MODEL,
    STRIPE_SECRET_KEY, STRIPE_WEBHOOK_SECRET,
    STRIPE_PRICE_BASIC, STRIPE_PRICE_PREMIUM,
    BASIC_DAILY_PHOTO_LIMIT, TRIAL_DAYS
)
from database import FOOD_DATABASE
from db import init_db, ensure_user_exists, set_fact, set_facts, get_fact, delete_all_facts

# -------------------- Stripe Configuration --------------------
stripe.api_key = STRIPE_SECRET_KEY

# -------------------- Admin Configuration --------------------
# Админы имеют бесплатный безлимитный доступ
# Добавляй ID через запятую в переменной ADMIN_IDS в Railway
import os
ADMIN_IDS_STR = os.getenv("ADMIN_IDS", "1642251041")  # По умолчанию твой ID
ADMIN_IDS = [int(x.strip()) for x in ADMIN_IDS_STR.split(",") if x.strip().isdigit()]

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

# -------------------- ПОЛНЫЕ ТЕКСТЫ НА 3 ЯЗЫКАХ --------------------
TEXTS = {
    "ru": {
        # Выбор языка
        "choose_language": "Выбери язык / Choose language / Vyberte jazyk:",
        
        # Приветствие и онбординг
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
        "name_invalid": "Напиши, пожалуйста, только имя (2–30 символов).",
        "welcome_back": "С возвращением, {name}! 😊\nЯ готов помочь тебе с питанием. Чем займёмся сегодня?",
        "ask_goal": "Отлично, {name}! Какая у тебя цель?",
        "goal_lose": "🏃 Похудеть",
        "goal_gain": "💪 Набрать",
        "goal_maintain": "⚖️ Поддерживать",
        "goal_lose_value": "похудеть",
        "goal_gain_value": "набрать массу",
        "goal_maintain_value": "поддерживать",
        "goal_accepted": (
            "Супер! Отличная цель! 🎯\n\n"
            "Теперь расскажи мне о себе:\n"
            "Напиши одним сообщением: вес (кг), рост (см), возраст\n\n"
            "Например: 114, 182, 49"
        ),
        "wha_invalid": "Напиши все данные одним сообщением: вес, рост, возраст.\nНапример: 114, 182, 49",
        "ask_activity": "Отлично! Последний вопрос:\n\nКакая у тебя физическая активность?",
        "activity_low": "🛋 Низкая",
        "activity_medium": "🚶 Средняя",
        "activity_high": "🏃 Высокая",
        "activity_low_value": "низкая",
        "activity_medium_value": "средняя",
        "activity_high_value": "высокая",
        "onboarding_complete": (
            "Отлично! Теперь я знаю о тебе всё необходимое! 🎉\n\n"
            "Для использования бота необходима подписка.\n"
            "Нажми кнопку ниже чтобы выбрать тариф!"
        ),
        
        # ПОДПИСКИ
        "subscription_required": (
            "⚠️ Для использования бота необходима подписка.\n\n"
            "Нажми /subscribe чтобы выбрать тариф."
        ),
        "subscription_expired": (
            "⚠️ Твоя подписка истекла.\n\n"
            "Нажми /subscribe чтобы продлить."
        ),
        "choose_plan": (
            "💳 Выбери тариф:\n\n"
            "📦 **Basic** — €10/месяц\n"
            "• До 10 анализов фото в день\n"
            "• Планы питания\n"
            "• Программы тренировок\n\n"
            "⭐ **Premium** — €20/месяц\n"
            "• Безлимитные анализы фото\n"
            "• Приоритетная поддержка\n"
            "• Все функции Basic\n\n"
            "🎁 Первый день — БЕСПЛАТНО!\n\n"
            "💡 Отменить подписку можно в любой момент: /cancel"
        ),
        "btn_basic": "📦 Basic — €10/мес",
        "btn_premium": "⭐ Premium — €20/мес",
        "payment_link": "💳 Перейди по ссылке для оплаты:\n{url}\n\nПосле оплаты бот автоматически активирует подписку!",
        "subscription_activated": (
            "✅ Подписка активирована!\n\n"
            "📦 Тариф: {plan}\n"
            "📅 Действует до: {expires}\n\n"
            "Теперь ты можешь пользоваться ботом! 🎉\n\n"
            "💡 Отменить подписку: /cancel"
        ),
        "subscription_status": (
            "📊 Твоя подписка:\n\n"
            "📦 Тариф: {plan}\n"
            "📅 Действует до: {expires}\n"
            "📸 Фото сегодня: {used}/{limit}\n\n"
            "❌ Отменить подписку: /cancel"
        ),
        "photo_limit_reached": (
            "⚠️ Ты достиг лимита анализов на сегодня ({limit}).\n\n"
            "Обнови подписку до Premium для безлимитных анализов!\n"
            "/subscribe"
        ),
        "trial_started": (
            "🎁 Пробный период активирован!\n\n"
            "У тебя есть 1 день бесплатного доступа.\n"
            "После этого нужно будет оформить подписку."
        ),
        
        # Меню кнопки
        "menu_photo": "📸 Фото еды",
        "menu_question": "💬 Вопрос",
        "menu_meal_plan": "📋 План питания",
        "menu_workout": "💪 Тренировки",
        "menu_weigh_in": "⚖️ Взвеситься",
        "menu_progress": "📊 Мой прогресс",
        "menu_settings": "⚙️ Настройки",
        
        # Ответы на меню
        "photo_prompt": "📸 Отлично! Сфотографируй свою еду и отправь мне.\nЯ проанализирую и посчитаю калории!",
        "question_prompt": "💬 Задай любой вопрос о питании!\nМожешь написать или отправить голосовое сообщение 🎤",
        "meal_plan_loading": "{name}, составляю персональный план питания для твоей цели: {goal}...\nЭто займёт немного времени ⏳",
        "meal_plan_result": "📋 Твой план питания:\n\n{plan}",
        "workout_loading": "{name}, составляю программу тренировок для твоей цели: {goal}...\nУчитываю твою активность ⏳",
        "workout_result": "💪 Твоя программа тренировок:\n\n{plan}",
        "weigh_in_prompt": (
            "⚖️ Взвешивание\n\n"
            "Напиши свой текущий вес в килограммах.\n"
            "Например: 101\n\n"
            "Я запомню и покажу твой прогресс! 📊"
        ),
        "weight_invalid": "Напиши число, например: 101",
        "weight_unrealistic": "Это не похоже на реальный вес. Попробуй ещё раз.",
        "weight_stable": "⚖️ Вес записан: {weight} кг\n\nВес стабилен! 👍\nТак держать! 💪",
        "weight_down": "⚖️ Вес записан: {weight} кг\n\n⬇️ -{diff} кг с прошлого раза!\nОтличная работа! {emoji}",
        "weight_up": "⚖️ Вес записан: {weight} кг\n\n⬆️ +{diff} кг с прошлого раза\nНе переживай, продолжаем! 💪",
        "weight_total_lost": "\n\n💪 Всего сброшено: {diff} кг! {emoji}",
        "weight_total_gained": "\n\n📈 Всего набрано: {diff} кг",
        "weight_see_progress": "\n\n📊 Нажми «Мой прогресс» чтобы увидеть динамику!",
        "progress_title": "📊 Твой прогресс, {name}:\n\n",
        "progress_current": "⚖️ Текущий вес: {weight} кг\n",
        "progress_goal": "🎯 Цель: {goal}\n",
        "progress_no_history": "\n💡 Нажми «⚖️ Взвеситься» чтобы начать отслеживать прогресс!",
        "progress_total_lost": "💪 Всего сброшено: {diff} кг 🔥\n",
        "progress_total_gained": "📈 Набрано: {diff} кг\n",
        "progress_stable": "⚖️ Вес стабилен\n",
        "progress_days": "📅 За {days} {days_word}\n",
        "day_one": "день",
        "day_few": "дня",
        "day_many": "дней",
        "settings_title": (
            "⚙️ Твои настройки:\n\n"
            "👤 Имя: {name}\n"
            "🎯 Цель: {goal}\n"
            "⚖️ Вес: {weight} кг\n"
            "📏 Рост: {height} см\n"
            "🎂 Возраст: {age} лет\n"
            "🏃 Активность: {activity}\n\n"
            "Чтобы изменить данные, напиши:\nreset"
        ),
        
        # Анализ фото
        "analyzing_1": "🔍 Смотрю на твою еду...",
        "analyzing_2": "🤔 Хм, интересненько...",
        "analyzing_3": "💭 Думаю-думаю...",
        "analyzing_done": "✨ Готово! Вот что думаю:",
        "photo_error": "Произошла ошибка при анализе фото 😔\nПопробуй ещё раз или опиши блюдо словами!",
        "photo_not_recognized": "Не смог проанализировать фото. Попробуй другое фото или опиши блюдо словами.",
        
        # Голосовые
        "voice_listening": "🎤 Слушаю...",
        "voice_recognized": "📝 Распознано: \"{text}\"",
        "voice_error": "Не удалось распознать речь. Попробуй ещё раз 🙂",
        "voice_process_error": "Не удалось обработать голосовое 😔 Попробуй ещё раз!",
        
        # Общее
        "reset_done": "✅ Сброшено! Напиши /start чтобы начать заново.",
        "complete_registration": "Пожалуйста, заверши регистрацию! Напиши /start",
        "hello_response": "Привет, {name}! 😊 Чем могу помочь?",
        "chat_error": "Произошла ошибка. Попробуй переформулировать вопрос 🙂",
        "photo_complete_first": "Сначала заверши регистрацию! Напиши /start",
        "photo_process_error": "Не удалось обработать фото 😔 Попробуй ещё раз!",
        
        # Help
        "help_text": (
            "📋 Команды:\n"
            "/start — начать или продолжить\n"
            "/subscribe — управление подпиской\n"
            "/status — статус подписки\n"
            "/cancel — отменить подписку\n"
            "reset — сбросить анкету\n\n"
            "💬 Можно:\n"
            "• Задавать вопросы про питание\n"
            "• Присылать фото еды для анализа 📸\n"
            "• Просить план питания или тренировок"
        ),
        
        # GPT prompts
        "gpt_response_lang": "русском",
        "gpt_meal_plan_prompt": "Составь план питания на день с учётом моей цели: {goal}. Включи завтрак, обед, ужин и перекусы.",
        "gpt_workout_prompt": "Составь программу тренировок на неделю. Моя цель: {goal}. Распиши упражнения по дням.",
    },
    
    "cs": {
        # Výběr jazyka
        "choose_language": "Vyberte jazyk / Choose language / Выбери язык:",
        
        # Uvítání a onboarding
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
        "name_invalid": "Napiš prosím jen jméno (2–30 znaků).",
        "welcome_back": "Vítej zpět, {name}! 😊\nJsem připraven pomoci s tvým stravováním. Co dnes budeme dělat?",
        "ask_goal": "Skvělé, {name}! Jaký je tvůj cíl?",
        "goal_lose": "🏃 Zhubnout",
        "goal_gain": "💪 Nabrat",
        "goal_maintain": "⚖️ Udržovat",
        "goal_lose_value": "zhubnout",
        "goal_gain_value": "nabrat",
        "goal_maintain_value": "udržovat",
        "goal_accepted": (
            "Super! Výborný cíl! 🎯\n\n"
            "Teď mi řekni o sobě:\n"
            "Napiš v jedné zprávě: váha (kg), výška (cm), věk\n\n"
            "Například: 114, 182, 49"
        ),
        "wha_invalid": "Napiš všechny údaje v jedné zprávě: váha, výška, věk.\nNapříklad: 114, 182, 49",
        "ask_activity": "Výborně! Poslední otázka:\n\nJaká je tvá fyzická aktivita?",
        "activity_low": "🛋 Nízká",
        "activity_medium": "🚶 Střední",
        "activity_high": "🏃 Vysoká",
        "activity_low_value": "nízká",
        "activity_medium_value": "střední",
        "activity_high_value": "vysoká",
        "onboarding_complete": (
            "Skvělé! Teď o tobě vím vše potřebné! 🎉\n\n"
            "Pro používání bota je potřeba předplatné.\n"
            "Klikni na tlačítko níže pro výběr tarifu!"
        ),
        
        # PŘEDPLATNÉ
        "subscription_required": (
            "⚠️ Pro používání bota je potřeba předplatné.\n\n"
            "Napiš /subscribe pro výběr tarifu."
        ),
        "subscription_expired": (
            "⚠️ Tvé předplatné vypršelo.\n\n"
            "Napiš /subscribe pro prodloužení."
        ),
        "choose_plan": (
            "💳 Vyber tarif:\n\n"
            "📦 **Basic** — €10/měsíc\n"
            "• Až 10 analýz fotek denně\n"
            "• Jídelní plány\n"
            "• Tréninkové programy\n\n"
            "⭐ **Premium** — €20/měsíc\n"
            "• Neomezené analýzy fotek\n"
            "• Prioritní podpora\n"
            "• Všechny funkce Basic\n\n"
            "🎁 První den — ZDARMA!\n\n"
            "💡 Zrušit předplatné můžeš kdykoliv: /cancel"
        ),
        "btn_basic": "📦 Basic — €10/měs",
        "btn_premium": "⭐ Premium — €20/měs",
        "payment_link": "💳 Přejdi na odkaz pro platbu:\n{url}\n\nPo platbě bot automaticky aktivuje předplatné!",
        "subscription_activated": (
            "✅ Předplatné aktivováno!\n\n"
            "📦 Tarif: {plan}\n"
            "📅 Platí do: {expires}\n\n"
            "Teď můžeš používat bota! 🎉\n\n"
            "💡 Zrušit předplatné: /cancel"
        ),
        "subscription_status": (
            "📊 Tvé předplatné:\n\n"
            "📦 Tarif: {plan}\n"
            "📅 Platí do: {expires}\n"
            "📸 Fotek dnes: {used}/{limit}\n\n"
            "❌ Zrušit předplatné: /cancel"
        ),
        "photo_limit_reached": (
            "⚠️ Dosáhl jsi denního limitu analýz ({limit}).\n\n"
            "Uprav předplatné na Premium pro neomezené analýzy!\n"
            "/subscribe"
        ),
        "trial_started": (
            "🎁 Zkušební období aktivováno!\n\n"
            "Máš 1 den bezplatného přístupu.\n"
            "Poté bude potřeba předplatné."
        ),
        
        # Menu tlačítka
        "menu_photo": "📸 Fotka jídla",
        "menu_question": "💬 Otázka",
        "menu_meal_plan": "📋 Jídelní plán",
        "menu_workout": "💪 Tréninky",
        "menu_weigh_in": "⚖️ Zvážit se",
        "menu_progress": "📊 Můj pokrok",
        "menu_settings": "⚙️ Nastavení",
        
        # Odpovědi na menu
        "photo_prompt": "📸 Skvělé! Vyfoť své jídlo a pošli mi ho.\nAnalyzuji a spočítám kalorie!",
        "question_prompt": "💬 Zeptej se na cokoliv o výživě!\nMůžeš napsat nebo poslat hlasovou zprávu 🎤",
        "meal_plan_loading": "{name}, vytvářím osobní jídelní plán pro tvůj cíl: {goal}...\nChvíli to potrvá ⏳",
        "meal_plan_result": "📋 Tvůj jídelní plán:\n\n{plan}",
        "workout_loading": "{name}, vytvářím tréninkový program pro tvůj cíl: {goal}...\nZohledňuji tvou aktivitu ⏳",
        "workout_result": "💪 Tvůj tréninkový program:\n\n{plan}",
        "weigh_in_prompt": (
            "⚖️ Vážení\n\n"
            "Napiš svou aktuální váhu v kilogramech.\n"
            "Například: 101\n\n"
            "Zapamatuji si a ukážu tvůj pokrok! 📊"
        ),
        "weight_invalid": "Napiš číslo, například: 101",
        "weight_unrealistic": "To nevypadá jako reálná váha. Zkus to znovu.",
        "weight_stable": "⚖️ Váha zapsána: {weight} kg\n\nVáha stabilní! 👍\nTak dál! 💪",
        "weight_down": "⚖️ Váha zapsána: {weight} kg\n\n⬇️ -{diff} kg od minule!\nSkvělá práce! {emoji}",
        "weight_up": "⚖️ Váha zapsána: {weight} kg\n\n⬆️ +{diff} kg od minule\nNevadí, pokračujeme! 💪",
        "weight_total_lost": "\n\n💪 Celkem shozeno: {diff} kg! {emoji}",
        "weight_total_gained": "\n\n📈 Celkem nabráno: {diff} kg",
        "weight_see_progress": "\n\n📊 Klikni na «Můj pokrok» pro zobrazení dynamiky!",
        "progress_title": "📊 Tvůj pokrok, {name}:\n\n",
        "progress_current": "⚖️ Aktuální váha: {weight} kg\n",
        "progress_goal": "🎯 Cíl: {goal}\n",
        "progress_no_history": "\n💡 Klikni na «⚖️ Zvážit se» pro sledování pokroku!",
        "progress_total_lost": "💪 Celkem shozeno: {diff} kg 🔥\n",
        "progress_total_gained": "📈 Nabráno: {diff} kg\n",
        "progress_stable": "⚖️ Váha stabilní\n",
        "progress_days": "📅 Za {days} {days_word}\n",
        "day_one": "den",
        "day_few": "dny",
        "day_many": "dní",
        "settings_title": (
            "⚙️ Tvá nastavení:\n\n"
            "👤 Jméno: {name}\n"
            "🎯 Cíl: {goal}\n"
            "⚖️ Váha: {weight} kg\n"
            "📏 Výška: {height} cm\n"
            "🎂 Věk: {age} let\n"
            "🏃 Aktivita: {activity}\n\n"
            "Pro změnu údajů napiš:\nreset"
        ),
        
        # Analýza fotek
        "analyzing_1": "🔍 Dívám se na tvoje jídlo...",
        "analyzing_2": "🤔 Hmm, zajímavé...",
        "analyzing_3": "💭 Přemýšlím...",
        "analyzing_done": "✨ Hotovo! Tady je co si myslím:",
        "photo_error": "Při analýze fotky nastala chyba 😔\nZkus to znovu nebo popiš jídlo slovy!",
        "photo_not_recognized": "Nepodařilo se analyzovat fotku. Zkus jinou nebo popiš jídlo slovy.",
        
        # Hlasové zprávy
        "voice_listening": "🎤 Poslouchám...",
        "voice_recognized": "📝 Rozpoznáno: \"{text}\"",
        "voice_error": "Nepodařilo se rozpoznat řeč. Zkus to znovu 🙂",
        "voice_process_error": "Nepodařilo se zpracovat hlasovou zprávu 😔 Zkus to znovu!",
        
        # Obecné
        "reset_done": "✅ Resetováno! Napiš /start pro nový začátek.",
        "complete_registration": "Prosím dokonči registraci! Napiš /start",
        "hello_response": "Ahoj, {name}! 😊 Jak ti mohu pomoci?",
        "chat_error": "Nastala chyba. Zkus přeformulovat otázku 🙂",
        "photo_complete_first": "Nejprve dokonči registraci! Napiš /start",
        "photo_process_error": "Nepodařilo se zpracovat fotku 😔 Zkus to znovu!",
        
        # Help
        "help_text": (
            "📋 Příkazy:\n"
            "/start — začít nebo pokračovat\n"
            "/subscribe — správa předplatného\n"
            "/status — stav předplatného\n"
            "/cancel — zrušit předplatné\n"
            "reset — resetovat profil\n\n"
            "💬 Můžeš:\n"
            "• Ptát se na výživu\n"
            "• Poslat fotku jídla na analýzu 📸\n"
            "• Požádat o jídelní plán nebo trénink"
        ),
        
        # GPT prompts
        "gpt_response_lang": "čeština",
        "gpt_meal_plan_prompt": "Vytvoř jídelní plán na den s ohledem na můj cíl: {goal}. Zahrň snídani, oběd, večeři a svačiny.",
        "gpt_workout_prompt": "Vytvoř týdenní tréninkový program. Můj cíl: {goal}. Rozpiš cviky podle dnů.",
    },
    
    "en": {
        # Language selection
        "choose_language": "Choose language / Выбери язык / Vyberte jazyk:",
        
        # Greeting and onboarding
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
        "name_invalid": "Please write just your name (2–30 characters).",
        "welcome_back": "Welcome back, {name}! 😊\nI'm ready to help with your nutrition. What shall we work on today?",
        "ask_goal": "Great, {name}! What's your goal?",
        "goal_lose": "🏃 Lose weight",
        "goal_gain": "💪 Gain muscle",
        "goal_maintain": "⚖️ Maintain",
        "goal_lose_value": "lose weight",
        "goal_gain_value": "gain muscle",
        "goal_maintain_value": "maintain",
        "goal_accepted": (
            "Awesome! Great goal! 🎯\n\n"
            "Now tell me about yourself:\n"
            "Write in one message: weight (kg), height (cm), age\n\n"
            "For example: 114, 182, 49"
        ),
        "wha_invalid": "Please write all data in one message: weight, height, age.\nFor example: 114, 182, 49",
        "ask_activity": "Perfect! Last question:\n\nWhat's your physical activity level?",
        "activity_low": "🛋 Low",
        "activity_medium": "🚶 Moderate",
        "activity_high": "🏃 High",
        "activity_low_value": "low",
        "activity_medium_value": "moderate",
        "activity_high_value": "high",
        "onboarding_complete": (
            "Excellent! Now I know everything I need! 🎉\n\n"
            "A subscription is required to use the bot.\n"
            "Click the button below to choose a plan!"
        ),
        
        # SUBSCRIPTIONS
        "subscription_required": (
            "⚠️ A subscription is required to use the bot.\n\n"
            "Type /subscribe to choose a plan."
        ),
        "subscription_expired": (
            "⚠️ Your subscription has expired.\n\n"
            "Type /subscribe to renew."
        ),
        "choose_plan": (
            "💳 Choose a plan:\n\n"
            "📦 **Basic** — €10/month\n"
            "• Up to 10 photo analyses per day\n"
            "• Meal plans\n"
            "• Workout programs\n\n"
            "⭐ **Premium** — €20/month\n"
            "• Unlimited photo analyses\n"
            "• Priority support\n"
            "• All Basic features\n\n"
            "🎁 First day — FREE!\n\n"
            "💡 Cancel anytime: /cancel"
        ),
        "btn_basic": "📦 Basic — €10/mo",
        "btn_premium": "⭐ Premium — €20/mo",
        "payment_link": "💳 Go to this link to pay:\n{url}\n\nAfter payment, the bot will automatically activate your subscription!",
        "subscription_activated": (
            "✅ Subscription activated!\n\n"
            "📦 Plan: {plan}\n"
            "📅 Valid until: {expires}\n\n"
            "You can now use the bot! 🎉\n\n"
            "💡 Cancel subscription: /cancel"
        ),
        "subscription_status": (
            "📊 Your subscription:\n\n"
            "📦 Plan: {plan}\n"
            "📅 Valid until: {expires}\n"
            "📸 Photos today: {used}/{limit}\n\n"
            "❌ Cancel subscription: /cancel"
        ),
        "photo_limit_reached": (
            "⚠️ You've reached your daily analysis limit ({limit}).\n\n"
            "Upgrade to Premium for unlimited analyses!\n"
            "/subscribe"
        ),
        "trial_started": (
            "🎁 Trial period activated!\n\n"
            "You have 1 day of free access.\n"
            "After that, you'll need a subscription."
        ),
        
        # Menu buttons
        "menu_photo": "📸 Food photo",
        "menu_question": "💬 Question",
        "menu_meal_plan": "📋 Meal plan",
        "menu_workout": "💪 Workouts",
        "menu_weigh_in": "⚖️ Weigh in",
        "menu_progress": "📊 My progress",
        "menu_settings": "⚙️ Settings",
        
        # Menu responses
        "photo_prompt": "📸 Great! Take a photo of your food and send it to me.\nI'll analyze and count calories!",
        "question_prompt": "💬 Ask any nutrition question!\nYou can write or send a voice message 🎤",
        "meal_plan_loading": "{name}, creating a personalized meal plan for your goal: {goal}...\nThis will take a moment ⏳",
        "meal_plan_result": "📋 Your meal plan:\n\n{plan}",
        "workout_loading": "{name}, creating a workout program for your goal: {goal}...\nConsidering your activity level ⏳",
        "workout_result": "💪 Your workout program:\n\n{plan}",
        "weigh_in_prompt": (
            "⚖️ Weigh-in\n\n"
            "Write your current weight in kilograms.\n"
            "Example: 101\n\n"
            "I'll remember and show your progress! 📊"
        ),
        "weight_invalid": "Please write a number, e.g.: 101",
        "weight_unrealistic": "This doesn't seem like a realistic weight. Try again.",
        "weight_stable": "⚖️ Weight recorded: {weight} kg\n\nWeight stable! 👍\nKeep it up! 💪",
        "weight_down": "⚖️ Weight recorded: {weight} kg\n\n⬇️ -{diff} kg since last time!\nGreat work! {emoji}",
        "weight_up": "⚖️ Weight recorded: {weight} kg\n\n⬆️ +{diff} kg since last time\nNo worries, keep going! 💪",
        "weight_total_lost": "\n\n💪 Total lost: {diff} kg! {emoji}",
        "weight_total_gained": "\n\n📈 Total gained: {diff} kg",
        "weight_see_progress": "\n\n📊 Press 'My progress' to see dynamics!",
        "progress_title": "📊 Your progress, {name}:\n\n",
        "progress_current": "⚖️ Current weight: {weight} kg\n",
        "progress_goal": "🎯 Goal: {goal}\n",
        "progress_no_history": "\n💡 Press '⚖️ Weigh in' to start tracking progress!",
        "progress_total_lost": "💪 Total lost: {diff} kg 🔥\n",
        "progress_total_gained": "📈 Gained: {diff} kg\n",
        "progress_stable": "⚖️ Weight stable\n",
        "progress_days": "📅 Over {days} {days_word}\n",
        "day_one": "day",
        "day_few": "days",
        "day_many": "days",
        "settings_title": (
            "⚙️ Your settings:\n\n"
            "👤 Name: {name}\n"
            "🎯 Goal: {goal}\n"
            "⚖️ Weight: {weight} kg\n"
            "📏 Height: {height} cm\n"
            "🎂 Age: {age} years\n"
            "🏃 Activity: {activity}\n\n"
            "To change data, write:\nreset"
        ),
        
        # Photo analysis
        "analyzing_1": "🔍 Looking at your food...",
        "analyzing_2": "🤔 Hmm, interesting...",
        "analyzing_3": "💭 Thinking...",
        "analyzing_done": "✨ Done! Here's what I think:",
        "photo_error": "Error analyzing photo 😔\nTry again or describe the dish in words!",
        "photo_not_recognized": "Couldn't analyze the photo. Try another photo or describe the dish in words.",
        
        # Voice messages
        "voice_listening": "🎤 Listening...",
        "voice_recognized": "📝 Recognized: \"{text}\"",
        "voice_error": "Couldn't recognize speech. Try again 🙂",
        "voice_process_error": "Couldn't process voice message 😔 Try again!",
        
        # General
        "reset_done": "✅ Reset! Write /start to begin again.",
        "complete_registration": "Please complete registration! Write /start",
        "hello_response": "Hi, {name}! 😊 How can I help?",
        "chat_error": "An error occurred. Try rephrasing your question 🙂",
        "photo_complete_first": "Please complete registration first! Write /start",
        "photo_process_error": "Couldn't process photo 😔 Try again!",
        
        # Help
        "help_text": (
            "📋 Commands:\n"
            "/start — start or continue\n"
            "/subscribe — manage subscription\n"
            "/status — subscription status\n"
            "/cancel — cancel subscription\n"
            "reset — reset profile\n\n"
            "💬 You can:\n"
            "• Ask about nutrition\n"
            "• Send food photos for analysis 📸\n"
            "• Request meal plans or workouts"
        ),
        
        # GPT prompts
        "gpt_response_lang": "English",
        "gpt_meal_plan_prompt": "Create a meal plan for the day considering my goal: {goal}. Include breakfast, lunch, dinner, and snacks.",
        "gpt_workout_prompt": "Create a weekly workout program. My goal: {goal}. List exercises by day.",
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
        await delete_all_facts(user_id)
    except Exception as e:
        logger.error(f"Error clearing user data: {e}")


async def profile_missing(user_id: int) -> Optional[str]:
    """Returns prompt for missing data or None if complete"""
    language = await get_fact(user_id, "language")
    name = await get_fact(user_id, "name")
    goal = await get_fact(user_id, "goal")
    weight = await get_fact(user_id, "weight_kg")
    height = await get_fact(user_id, "height_cm")
    age = await get_fact(user_id, "age")
    activity = await get_fact(user_id, "activity")

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


def create_main_menu(lang: str) -> ReplyKeyboardMarkup:
    """Создаёт главное меню на нужном языке"""
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text=get_text_lang(lang, "menu_photo")),
                KeyboardButton(text=get_text_lang(lang, "menu_question"))
            ],
            [
                KeyboardButton(text=get_text_lang(lang, "menu_meal_plan")),
                KeyboardButton(text=get_text_lang(lang, "menu_workout"))
            ],
            [
                KeyboardButton(text=get_text_lang(lang, "menu_weigh_in")),
                KeyboardButton(text=get_text_lang(lang, "menu_progress"))
            ],
            [
                KeyboardButton(text=get_text_lang(lang, "menu_settings"))
            ]
        ],
        resize_keyboard=True
    )


# Список всех вариантов кнопок меню для всех языков
ALL_MENU_PHOTO = [TEXTS["ru"]["menu_photo"], TEXTS["cs"]["menu_photo"], TEXTS["en"]["menu_photo"]]
ALL_MENU_QUESTION = [TEXTS["ru"]["menu_question"], TEXTS["cs"]["menu_question"], TEXTS["en"]["menu_question"]]
ALL_MENU_MEAL_PLAN = [TEXTS["ru"]["menu_meal_plan"], TEXTS["cs"]["menu_meal_plan"], TEXTS["en"]["menu_meal_plan"]]
ALL_MENU_WORKOUT = [TEXTS["ru"]["menu_workout"], TEXTS["cs"]["menu_workout"], TEXTS["en"]["menu_workout"]]
ALL_MENU_WEIGH_IN = [TEXTS["ru"]["menu_weigh_in"], TEXTS["cs"]["menu_weigh_in"], TEXTS["en"]["menu_weigh_in"]]
ALL_MENU_PROGRESS = [TEXTS["ru"]["menu_progress"], TEXTS["cs"]["menu_progress"], TEXTS["en"]["menu_progress"]]
ALL_MENU_SETTINGS = [TEXTS["ru"]["menu_settings"], TEXTS["cs"]["menu_settings"], TEXTS["en"]["menu_settings"]]


def get_days_word(lang: str, days: int) -> str:
    """Склонение слова 'день' для разных языков"""
    if lang == "ru":
        if days == 1:
            return TEXTS["ru"]["day_one"]
        elif 2 <= days <= 4:
            return TEXTS["ru"]["day_few"]
        else:
            return TEXTS["ru"]["day_many"]
    elif lang == "cs":
        if days == 1:
            return TEXTS["cs"]["day_one"]
        elif 2 <= days <= 4:
            return TEXTS["cs"]["day_few"]
        else:
            return TEXTS["cs"]["day_many"]
    else:
        if days == 1:
            return TEXTS["en"]["day_one"]
        else:
            return TEXTS["en"]["day_many"]


# ==================== SUBSCRIPTION FUNCTIONS ====================

async def get_subscription(user_id: int) -> Optional[dict]:
    """Получить информацию о подписке пользователя"""
    sub_json = await get_fact(user_id, "subscription")
    if not sub_json:
        return None
    try:
        return json.loads(sub_json)
    except:
        return None


async def set_subscription(user_id: int, plan: str, expires_at: datetime, stripe_customer_id: str = None, stripe_subscription_id: str = None):
    """Установить подписку пользователя"""
    sub_data = {
        "plan": plan,  # "basic", "premium", "trial"
        "expires_at": expires_at.isoformat(),
        "stripe_customer_id": stripe_customer_id,
        "stripe_subscription_id": stripe_subscription_id,
        "created_at": datetime.now().isoformat()
    }
    await set_fact(user_id, "subscription", json.dumps(sub_data))


async def check_subscription_valid(user_id: int) -> Tuple[bool, Optional[str]]:
    """
    Проверить активна ли подписка
    Returns: (is_valid, plan_or_error_key)
    """
    # Админы имеют бесплатный доступ
    if user_id in ADMIN_IDS:
        return True, "admin"
    
    sub = await get_subscription(user_id)
    if not sub:
        return False, "subscription_required"
    
    expires_at = datetime.fromisoformat(sub["expires_at"])
    if datetime.now() > expires_at:
        return False, "subscription_expired"
    
    return True, sub["plan"]


async def get_daily_photo_count(user_id: int) -> int:
    """Получить количество фото за сегодня"""
    today = datetime.now().strftime("%Y-%m-%d")
    usage_json = await get_fact(user_id, "daily_usage")
    
    if not usage_json:
        return 0
    
    try:
        usage = json.loads(usage_json)
        if usage.get("date") == today:
            return usage.get("photo_count", 0)
        return 0
    except:
        return 0


async def increment_photo_count(user_id: int):
    """Увеличить счётчик фото за сегодня"""
    today = datetime.now().strftime("%Y-%m-%d")
    usage_json = await get_fact(user_id, "daily_usage")
    
    if usage_json:
        try:
            usage = json.loads(usage_json)
            if usage.get("date") == today:
                usage["photo_count"] = usage.get("photo_count", 0) + 1
            else:
                usage = {"date": today, "photo_count": 1}
        except:
            usage = {"date": today, "photo_count": 1}
    else:
        usage = {"date": today, "photo_count": 1}
    
    await set_fact(user_id, "daily_usage", json.dumps(usage))


async def can_analyze_photo(user_id: int) -> Tuple[bool, Optional[str]]:
    """
    Проверить может ли пользователь анализировать фото
    Returns: (can_analyze, error_key_if_not)
    """
    # Админы - безлимит
    if user_id in ADMIN_IDS:
        return True, None
    
    # Проверяем подписку
    is_valid, plan_or_error = await check_subscription_valid(user_id)
    if not is_valid:
        return False, plan_or_error
    
    plan = plan_or_error
    
    # Premium, trial, admin и granted - безлимит
    if plan in ["premium", "trial", "admin", "granted"]:
        return True, None
    
    # Basic - проверяем лимит
    count = await get_daily_photo_count(user_id)
    if count >= BASIC_DAILY_PHOTO_LIMIT:
        return False, "photo_limit_reached"
    
    return True, None


async def create_checkout_session(user_id: int, plan: str, lang: str) -> Optional[str]:
    """Создать Stripe Checkout Session и вернуть URL"""
    try:
        price_id = STRIPE_PRICE_BASIC if plan == "basic" else STRIPE_PRICE_PREMIUM
        
        session = stripe.checkout.Session.create(
            payment_method_types=["card"],
            line_items=[{
                "price": price_id,
                "quantity": 1,
            }],
            mode="subscription",
            success_url=f"https://t.me/dietolog_ai_2025_bot?start=payment_success",
            cancel_url=f"https://t.me/dietolog_ai_2025_bot?start=payment_cancel",
            metadata={
                "user_id": str(user_id),
                "plan": plan
            },
            subscription_data={
                "trial_period_days": TRIAL_DAYS,
                "metadata": {
                    "user_id": str(user_id),
                    "plan": plan
                }
            }
        )
        
        return session.url
    except Exception as e:
        logger.error(f"Error creating checkout session: {e}")
        return None


# ==================== STRIPE WEBHOOK HANDLER ====================

async def handle_stripe_webhook(request):
    """Обработчик Stripe webhook"""
    payload = await request.read()
    sig_header = request.headers.get("Stripe-Signature")
    
    try:
        event = stripe.Webhook.construct_event(
            payload, sig_header, STRIPE_WEBHOOK_SECRET
        )
    except ValueError as e:
        logger.error(f"Invalid payload: {e}")
        return web.Response(status=400)
    except stripe.error.SignatureVerificationError as e:
        logger.error(f"Invalid signature: {e}")
        return web.Response(status=400)
    
    # Обработка событий
    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        user_id = int(session["metadata"].get("user_id", 0))
        plan = session["metadata"].get("plan", "basic")
        
        if user_id:
            # Активируем подписку на 30 дней + 1 день триала
            expires_at = datetime.now() + timedelta(days=31)
            await set_subscription(
                user_id, 
                plan, 
                expires_at,
                session.get("customer"),
                session.get("subscription")
            )
            
            # Отправляем сообщение пользователю
            user_lang = await get_fact(user_id, "language") or "ru"
            plan_name = "Basic" if plan == "basic" else "Premium"
            expires_str = expires_at.strftime("%d.%m.%Y")
            
            try:
                await bot.send_message(
                    user_id,
                    get_text_lang(user_lang, "subscription_activated", plan=plan_name, expires=expires_str),
                    reply_markup=create_main_menu(user_lang)
                )
            except Exception as e:
                logger.error(f"Error sending activation message: {e}")
    
    elif event["type"] == "customer.subscription.updated":
        subscription = event["data"]["object"]
        user_id = int(subscription["metadata"].get("user_id", 0))
        
        if user_id and subscription["status"] == "active":
            plan = subscription["metadata"].get("plan", "basic")
            # Обновляем дату истечения
            current_period_end = datetime.fromtimestamp(subscription["current_period_end"])
            await set_subscription(
                user_id,
                plan,
                current_period_end,
                subscription.get("customer"),
                subscription.get("id")
            )
    
    elif event["type"] == "customer.subscription.deleted":
        subscription = event["data"]["object"]
        user_id = int(subscription["metadata"].get("user_id", 0))
        
        if user_id:
            # Подписка отменена - устанавливаем истечение на сейчас
            await set_subscription(user_id, "cancelled", datetime.now())
    
    return web.Response(status=200)


# ==================== BOT HANDLERS ====================

def format_food_card(food_name: str, calories: int, protein: float, fat: float, carbs: float, weight: int = 100, lang: str = "ru") -> str:
    """Форматирует красивую карточку с результатами анализа"""
    headers = {
        "ru": "АНАЛИЗ БЛЮДА",
        "cs": "ANALÝZA JÍDLA",
        "en": "FOOD ANALYSIS"
    }
    labels = {
        "ru": {"portion": "Порция", "cal": "Калории", "protein": "Белки", "fat": "Жиры", "carbs": "Углеводы"},
        "cs": {"portion": "Porce", "cal": "Kalorie", "protein": "Bílkoviny", "fat": "Tuky", "carbs": "Sacharidy"},
        "en": {"portion": "Portion", "cal": "Calories", "protein": "Protein", "fat": "Fat", "carbs": "Carbs"}
    }
    lbl = labels.get(lang, labels["ru"])
    header = headers.get(lang, headers["ru"])
    
    card = (
        f"╔═══════════════════════════╗\n"
        f"║   📊 {header}        ║\n"
        f"╠═══════════════════════════╣\n"
        f"║ 🍽 {food_name}\n"
        f"║ ⚖️ {lbl['portion']}: ~{weight}г\n"
        f"║                           ║\n"
        f"║ 🔥 {lbl['cal']}: {calories} ккал\n"
        f"║ 🥩 {lbl['protein']}: {protein}г\n"
        f"║ 🧈 {lbl['fat']}: {fat}г\n"
        f"║ 🍞 {lbl['carbs']}: {carbs}г\n"
        f"╚═══════════════════════════╝"
    )
    return card


async def analyze_food_photo(photo_bytes: bytes, user_id: int) -> str:
    """Vision analysis with improved recognition and 80/20 recommendations"""
    try:
        name = await get_fact(user_id, "name") or "друг"
        goal = await get_fact(user_id, "goal") or "поддерживать вес"
        weight = await get_fact(user_id, "weight_kg") or "?"
        activity = await get_fact(user_id, "activity") or "средняя"
        user_lang = await get_fact(user_id, "language") or "ru"
        
        base64_image = base64.b64encode(photo_bytes).decode("utf-8")

        response_lang = get_text_lang(user_lang, "gpt_response_lang")
        
        # Промпты на разных языках для точного ответа
        if user_lang == "cs":
            system_prompt = f"""Jsi zkušený dietolog. Analyzuj fotku jídla a dej přesný odhad.
ODPOVÍDEJ POUZE ČESKY!

PROFIL UŽIVATELE:
- Jméno: {name}
- Cíl: {goal}
- Váha: {weight} kg
- Aktivita: {activity}

TVŮJ ÚKOL:
1. Urči jaké jídlo je na fotce
2. Odhadni velikost porce v gramech
3. Vypočítej KBJU pro tuto porci
4. Dej užitečné doporučení

DŮLEŽITÉ - ODPOVĚZ PŘESNĚ V TOMTO FORMÁTU:
NÁZEV: [název jídla]
PORCE: [číslo] g
KCAL: [číslo]
BÍLKOVINY: [číslo] g
TUKY: [číslo] g
SACHARIDY: [číslo] g
DOPORUČENÍ: [tvé rady]

PRAVIDLA:
- Porce běžného talíře = 250-400g
- Maso/ryba = minimálně 150-200g a 200-400 kcal
- Příloha = 150-250g a 150-300 kcal
- Salát = 200-350g a 100-250 kcal
- NEPIŠ 3 kcal nebo 2g — to není realistické!
- Minimum pro jakékoliv jídlo: 50 kcal

ODPOVÍDEJ POUZE ČESKY!"""
            user_prompt = "Analyzuj toto jídlo. Dej realistický odhad KBJU."
            
        elif user_lang == "en":
            system_prompt = f"""You are an experienced dietitian. Analyze the food photo and give accurate estimates.
RESPOND ONLY IN ENGLISH!

USER PROFILE:
- Name: {name}
- Goal: {goal}
- Weight: {weight} kg
- Activity: {activity}

YOUR TASK:
1. Identify the food in the photo
2. Estimate portion size in grams
3. Calculate macros for this portion
4. Give useful recommendations

IMPORTANT - RESPOND EXACTLY IN THIS FORMAT:
NAME: [food name]
PORTION: [number] g
KCAL: [number]
PROTEIN: [number] g
FAT: [number] g
CARBS: [number] g
RECOMMENDATIONS: [your advice]

RULES:
- Regular plate portion = 250-400g
- Meat/fish = at least 150-200g and 200-400 kcal
- Side dish = 150-250g and 150-300 kcal
- Salad = 200-350g and 100-250 kcal
- DON'T write 3 kcal or 2g — that's unrealistic!
- Minimum for any food: 50 kcal

RESPOND ONLY IN ENGLISH!"""
            user_prompt = "Analyze this food. Give realistic macro estimates."
            
        else:  # ru по умолчанию
            system_prompt = f"""Ты опытный диетолог-нутрициолог. Анализируй фото еды и давай точную оценку.
ОТВЕЧАЙ ТОЛЬКО НА РУССКОМ ЯЗЫКЕ!

ПРОФИЛЬ ПОЛЬЗОВАТЕЛЯ:
- Имя: {name}
- Цель: {goal}
- Вес: {weight} кг
- Активность: {activity}

ТВОЯ ЗАДАЧА:
1. Определи что за блюдо/продукты на фото
2. Оцени размер порции в граммах (визуально, сравни с тарелкой)
3. Рассчитай КБЖУ для этой порции
4. Дай полезные рекомендации

ВАЖНО - ОТВЕЧАЙ СТРОГО В ТАКОМ ФОРМАТЕ:
НАЗВАНИЕ: [название блюда]
ПОРЦИЯ: [число] г
ККАЛ: [число]
БЕЛКИ: [число] г
ЖИРЫ: [число] г
УГЛЕВОДЫ: [число] г
РЕКОМЕНДАЦИИ: [твои советы]

ПРАВИЛА:
- Порция обычной тарелки еды = 250-400г
- Если видишь мясо/рыбу — это минимум 150-200г и 200-400 ккал
- Если видишь кашу/гарнир — это 150-250г и 150-300 ккал
- Если видишь салат — это 200-350г и 100-250 ккал
- НЕ ПИШИ 3 ккал или 2г — это нереалистично для еды!
- Минимум для любой еды: 50 ккал

ОТВЕЧАЙ ТОЛЬКО НА РУССКОМ ЯЗЫКЕ!"""
            user_prompt = "Проанализируй это блюдо. Дай реалистичную оценку КБЖУ."

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
                            "image_url": {"url": f"data:image/jpeg;base64,{base64_image}", "detail": "high"}
                        },
                    ],
                },
            ],
            max_tokens=1500,
            temperature=0.3,
        )

        result = (resp.choices[0].message.content or "").strip()
        logger.info(f"GPT Response: {result[:500]}")
        
        if not result:
            return get_text_lang(user_lang, "photo_not_recognized")

        # Парсим ответ - ищем числа после ключевых слов
        food_name = "Блюдо"
        weight_g = 250
        calories = 0
        protein = 0.0
        fat = 0.0
        carbs = 0.0
        recommendations = ""
        
        lines = result.split('\n')
        
        for line in lines:
            line_lower = line.lower().strip()
            
            # Название блюда
            if any(x in line_lower for x in ['название:', 'name:', 'блюдо:', 'dish:', 'jídlo:', 'název:']):
                parts = line.split(':', 1)
                if len(parts) > 1:
                    food_name = parts[1].strip()
            
            # Порция/вес
            elif any(x in line_lower for x in ['порция:', 'portion:', 'вес:', 'weight:', 'porce:', 'váha:']):
                nums = re.findall(r'(\d+)', line)
                if nums:
                    weight_g = int(nums[0])
                    if weight_g < 10:  # Явно ошибка
                        weight_g = 250
            
            # Калории
            elif any(x in line_lower for x in ['ккал:', 'kcal:', 'калории:', 'calories:', 'kalorie:']):
                nums = re.findall(r'(\d+)', line)
                if nums:
                    calories = int(nums[0])
            
            # Белки
            elif any(x in line_lower for x in ['белки:', 'белок:', 'protein:', 'bílkoviny:']):
                nums = re.findall(r'(\d+\.?\d*)', line)
                if nums:
                    protein = float(nums[0])
            
            # Жиры
            elif any(x in line_lower for x in ['жиры:', 'жир:', 'fat:', 'fats:', 'tuky:']):
                nums = re.findall(r'(\d+\.?\d*)', line)
                if nums:
                    fat = float(nums[0])
            
            # Углеводы
            elif any(x in line_lower for x in ['углеводы:', 'carbs:', 'carbohydrates:', 'sacharidy:']):
                nums = re.findall(r'(\d+\.?\d*)', line)
                if nums:
                    carbs = float(nums[0])
        
        # Собираем рекомендации
        rec_started = False
        rec_lines = []
        for line in lines:
            ll = line.lower()
            if any(x in ll for x in ['рекоменд', 'recommend', 'doporuč', 'советы', 'tips']):
                rec_started = True
                if ':' in line:
                    after_colon = line.split(':', 1)[1].strip()
                    if after_colon:
                        rec_lines.append(after_colon)
                continue
            if rec_started and line.strip():
                rec_lines.append(line.strip())
        recommendations = '\n'.join(rec_lines)
        
        # Проверка на нереалистичные значения
        if calories < 20:
            # Попробуем найти калории по-другому
            all_nums = re.findall(r'(\d{2,4})\s*(?:ккал|kcal|калор)', result.lower())
            if all_nums:
                calories = int(all_nums[0])
            else:
                # Оценим по БЖУ
                calories = int(protein * 4 + fat * 9 + carbs * 4)
                if calories < 50:
                    calories = 200  # Дефолт для еды
        
        # Если совсем не распознал
        if calories == 0 and protein == 0 and fat == 0 and carbs == 0:
            return f"🤔 {result}"
        
        # Создаём карточку
        card = format_food_card(food_name, calories, protein, fat, carbs, weight_g, user_lang)
        
        if recommendations:
            rec_label = {"ru": "Рекомендации", "cs": "Doporučení", "en": "Recommendations"}
            card += f"\n\n💡 {rec_label.get(user_lang, 'Рекомендации')}:\n\n{recommendations}"
        
        return card

    except Exception as e:
        logger.error(f"Error analyzing photo: {e}", exc_info=True)
        user_lang = await get_fact(user_id, "language") or "ru"
        return get_text_lang(user_lang, "photo_error")


async def chat_reply(user_text: str, user_id: int) -> str:
    """Normal chat reply"""
    try:
        name = await get_fact(user_id, "name") or ""
        goal = await get_fact(user_id, "goal") or ""
        weight = await get_fact(user_id, "weight_kg") or ""
        height = await get_fact(user_id, "height_cm") or ""
        age = await get_fact(user_id, "age") or ""
        activity = await get_fact(user_id, "activity") or ""
        job = await get_fact(user_id, "job") or ""
        user_lang = await get_fact(user_id, "language") or "ru"

        response_lang = get_text_lang(user_lang, "gpt_response_lang")

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
        user_lang = await get_fact(user_id, "language") or "ru"
        return get_text_lang(user_lang, "chat_error")


# -------------------- /start with language selection --------------------
@dp.message(Command("start"))
async def cmd_start(message: Message, state: FSMContext):
    """Start with language selection"""
    user_id = message.from_user.id
    await state.clear()
    
    # Обработка deep link после оплаты
    args = message.text.split()
    if len(args) > 1:
        param = args[1]
        user_lang = await get_fact(user_id, "language") or "ru"
        
        if param == "payment_success":
            # Проверяем подписку
            is_valid, plan = await check_subscription_valid(user_id)
            if is_valid:
                name = await get_fact(user_id, "name") or "друг"
                menu = create_main_menu(user_lang)
                await message.answer(
                    f"🎉 Отлично, {name}!\n\n"
                    f"Твоя подписка активирована. Теперь ты можешь пользоваться всеми функциями бота!\n\n"
                    f"📸 Отправь фото еды для анализа",
                    reply_markup=menu
                )
            else:
                await message.answer(
                    "⏳ Подписка обрабатывается...\n\n"
                    "Подожди несколько секунд и отправь /start"
                )
            return
        
        elif param == "payment_cancel":
            await message.answer(
                "❌ Оплата отменена\n\n"
                "Если хочешь попробовать снова, напиши /subscribe"
            )
            return

    missing = await profile_missing(user_id)
    
    if missing is None:
        # Профиль заполнен - проверяем подписку
        user_lang = await get_fact(user_id, "language") or "ru"
        name = await get_fact(user_id, "name") or "друг"
        
        is_valid, plan_or_error = await check_subscription_valid(user_id)
        
        if is_valid:
            menu = create_main_menu(user_lang)
            welcome = get_text_lang(user_lang, "welcome_back", name=name)
            await message.answer(welcome, reply_markup=menu)
        else:
            # Нужна подписка
            await message.answer(
                get_text_lang(user_lang, plan_or_error),
                reply_markup=ReplyKeyboardRemove()
            )
        return

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
    
    if missing == "name":
        greeting = get_text_lang(user_lang, "greeting")
        await message.answer(greeting, reply_markup=ReplyKeyboardRemove())
        await asyncio.sleep(1)
        
        ask_name = get_text_lang(user_lang, "ask_name")
        await message.answer(ask_name)
        await state.set_state(Onboarding.waiting_name)


# -------------------- /subscribe --------------------
@dp.message(Command("subscribe"))
async def cmd_subscribe(message: Message):
    """Show subscription options"""
    user_id = message.from_user.id
    user_lang = await get_fact(user_id, "language") or "ru"
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=get_text_lang(user_lang, "btn_basic"), callback_data="sub_basic")],
        [InlineKeyboardButton(text=get_text_lang(user_lang, "btn_premium"), callback_data="sub_premium")]
    ])
    
    await message.answer(
        get_text_lang(user_lang, "choose_plan"),
        reply_markup=keyboard,
        parse_mode="Markdown"
    )


@dp.callback_query(F.data.in_(["sub_basic", "sub_premium"]))
async def handle_subscription_choice(callback: CallbackQuery):
    """Handle subscription plan selection"""
    user_id = callback.from_user.id
    user_lang = await get_fact(user_id, "language") or "ru"
    plan = "basic" if callback.data == "sub_basic" else "premium"
    
    await callback.answer()
    await callback.message.edit_reply_markup(reply_markup=None)
    
    # Создаём Stripe checkout session
    checkout_url = await create_checkout_session(user_id, plan, user_lang)
    
    if checkout_url:
        await callback.message.answer(
            get_text_lang(user_lang, "payment_link", url=checkout_url)
        )
    else:
        await callback.message.answer(get_text_lang(user_lang, "chat_error"))


# -------------------- /status --------------------
@dp.message(Command("status"))
async def cmd_status(message: Message):
    """Show subscription status"""
    user_id = message.from_user.id
    user_lang = await get_fact(user_id, "language") or "ru"
    
    # Админы
    if user_id in ADMIN_IDS:
        await message.answer(
            "👑 Статус: АДМИН\n\n"
            "📦 Тариф: Бесплатный безлимит\n"
            "📅 Действует: Навсегда\n"
            "📸 Фото: ∞"
        )
        return
    
    sub = await get_subscription(user_id)
    
    if not sub:
        await message.answer(get_text_lang(user_lang, "subscription_required"))
        return
    
    plan = sub.get("plan", "none")
    expires_at = datetime.fromisoformat(sub["expires_at"])
    expires_str = expires_at.strftime("%d.%m.%Y")
    
    plan_names = {"basic": "Basic", "premium": "Premium", "trial": "Trial", "granted": "🎁 Подарочный"}
    plan_name = plan_names.get(plan, plan.capitalize())
    
    # Получаем использование
    used = await get_daily_photo_count(user_id)
    limit = "∞" if plan in ["premium", "granted"] else str(BASIC_DAILY_PHOTO_LIMIT)
    
    await message.answer(
        get_text_lang(user_lang, "subscription_status", 
                     plan=plan_name, expires=expires_str, used=used, limit=limit)
    )


# -------------------- /cancel --------------------
@dp.message(Command("cancel"))
async def cmd_cancel(message: Message):
    """Cancel subscription - создаёт ссылку на Stripe Customer Portal"""
    user_id = message.from_user.id
    user_lang = await get_fact(user_id, "language") or "ru"
    
    sub = await get_subscription(user_id)
    
    if not sub:
        await message.answer("❌ У тебя нет активной подписки")
        return
    
    # Проверяем есть ли stripe_customer_id
    customer_id = sub.get("stripe_customer_id")
    
    if not customer_id:
        # Подарочная или ручная подписка
        await message.answer("ℹ️ Твоя подписка не связана со Stripe. Обратись к администратору.")
        return
    
    try:
        # Создаём сессию Customer Portal
        portal_session = stripe.billing_portal.Session.create(
            customer=customer_id,
            return_url=f"https://t.me/dietolog_ai_2025_bot"
        )
        
        cancel_texts = {
            "ru": "🔗 Для управления подпиской перейди по ссылке:\n\n{url}\n\nТам ты сможешь:\n• Отменить подписку\n• Изменить способ оплаты\n• Посмотреть историю платежей",
            "cs": "🔗 Pro správu předplatného klikni na odkaz:\n\n{url}\n\nTam můžeš:\n• Zrušit předplatné\n• Změnit způsob platby\n• Zobrazit historii plateb",
            "en": "🔗 To manage your subscription, click the link:\n\n{url}\n\nThere you can:\n• Cancel subscription\n• Change payment method\n• View payment history"
        }
        
        text = cancel_texts.get(user_lang, cancel_texts["ru"]).format(url=portal_session.url)
        await message.answer(text)
        
    except Exception as e:
        logger.error(f"Error creating portal session: {e}")
        await message.answer("❌ Ошибка. Попробуй позже или обратись к администратору.")


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
    
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.answer()
    
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
    await message.answer(get_text_lang(user_lang, "help_text"))


# -------------------- Admin commands --------------------
@dp.message(Command("grant"))
async def cmd_grant(message: Message):
    """Выдать бесплатный доступ пользователю (только для админов)"""
    user_id = message.from_user.id
    
    if user_id not in ADMIN_IDS:
        await message.answer("⛔ Эта команда только для админов")
        return
    
    # Парсим ID из команды: /grant 123456789
    parts = message.text.split()
    if len(parts) < 2:
        await message.answer(
            "📝 Использование: /grant <user_id>\n\n"
            "Пример: /grant 123456789\n\n"
            "Чтобы узнать ID пользователя, попроси его написать боту @getmyid_bot"
        )
        return
    
    try:
        target_id = int(parts[1])
    except ValueError:
        await message.answer("❌ Неверный ID. Используй числовой ID пользователя.")
        return
    
    # Выдаём бессрочную подписку
    await set_subscription(
        target_id,
        plan="granted",
        expires_at=datetime(2099, 12, 31),
        stripe_customer_id=None,
        stripe_subscription_id=None
    )
    
    await message.answer(f"✅ Бесплатный доступ выдан пользователю {target_id}")


@dp.message(Command("revoke"))
async def cmd_revoke(message: Message):
    """Отозвать бесплатный доступ (только для админов)"""
    user_id = message.from_user.id
    
    if user_id not in ADMIN_IDS:
        await message.answer("⛔ Эта команда только для админов")
        return
    
    parts = message.text.split()
    if len(parts) < 2:
        await message.answer("📝 Использование: /revoke <user_id>")
        return
    
    try:
        target_id = int(parts[1])
    except ValueError:
        await message.answer("❌ Неверный ID")
        return
    
    # Отзываем подписку
    await set_subscription(
        target_id,
        plan="revoked",
        expires_at=datetime.now(),
        stripe_customer_id=None,
        stripe_subscription_id=None
    )
    
    await message.answer(f"✅ Доступ отозван у пользователя {target_id}")


# -------------------- onboarding: name --------------------
@dp.message(Onboarding.waiting_name, F.text)
async def onboarding_name(message: Message, state: FSMContext):
    """Collect user name"""
    if is_reset_command(message.text):
        user_id = message.from_user.id
        await clear_user_data(user_id)
        await state.clear()
        user_lang = await get_fact(user_id, "language") or "ru"
        await message.answer(get_text_lang(user_lang, "reset_done"), reply_markup=ReplyKeyboardRemove())
        return
    
    user_id = message.from_user.id
    user_lang = await get_fact(user_id, "language") or "ru"
    await ensure_user_exists(user_id)
    name = normalize_text(message.text)
    
    if len(name) < 2 or len(name) > 30:
        await message.answer(get_text_lang(user_lang, "name_invalid"))
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
        "goal_lose": "goal_lose_value",
        "goal_gain": "goal_gain_value",
        "goal_maintain": "goal_maintain_value"
    }
    
    goal_key = goal_map.get(callback.data, "goal_maintain_value")
    goal = get_text_lang(user_lang, goal_key)
    await set_fact(user_id, "goal", goal)
    
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.answer()
    
    goal_accepted = get_text_lang(user_lang, "goal_accepted")
    await callback.message.answer(goal_accepted)
    await state.set_state(Onboarding.waiting_whA)


@dp.message(Onboarding.waiting_goal, F.text)
async def onboarding_goal_text(message: Message, state: FSMContext):
    """Handle goal if user writes instead of clicking"""
    if is_reset_command(message.text):
        user_id = message.from_user.id
        await clear_user_data(user_id)
        await state.clear()
        user_lang = await get_fact(user_id, "language") or "ru"
        await message.answer(get_text_lang(user_lang, "reset_done"), reply_markup=ReplyKeyboardRemove())
        return
    
    user_id = message.from_user.id
    user_lang = await get_fact(user_id, "language") or "ru"
    goal_text = normalize_text(message.text).lower()
    
    if any(x in goal_text for x in ["похуд", "сброс", "lose", "zhubn"]):
        goal = get_text_lang(user_lang, "goal_lose_value")
    elif any(x in goal_text for x in ["наб", "мыш", "gain", "nabr"]):
        goal = get_text_lang(user_lang, "goal_gain_value")
    else:
        goal = get_text_lang(user_lang, "goal_maintain_value")

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
        user_lang = await get_fact(user_id, "language") or "ru"
        await message.answer(get_text_lang(user_lang, "reset_done"), reply_markup=ReplyKeyboardRemove())
        return
    
    user_id = message.from_user.id
    user_lang = await get_fact(user_id, "language") or "ru"
    parsed = parse_weight_height_age(message.text)
    
    if parsed is None:
        await message.answer(get_text_lang(user_lang, "wha_invalid"))
        return

    w, h, a = parsed
    await set_facts(user_id, {
        "weight_kg": str(w),
        "height_cm": str(h),
        "age": str(a),
    })

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
    """Handle activity selection - завершение онбординга"""
    user_id = callback.from_user.id
    user_lang = await get_fact(user_id, "language") or "ru"
    
    activity_map = {
        "activity_low": "activity_low_value",
        "activity_medium": "activity_medium_value",
        "activity_high": "activity_high_value"
    }
    
    activity_key = activity_map.get(callback.data, "activity_medium_value")
    activity = get_text_lang(user_lang, activity_key)
    await set_facts(user_id, {"activity": activity, "job": ""})
    
    await callback.message.edit_reply_markup(reply_markup=None)
    await state.clear()
    await callback.answer()
    
    # Админы получают доступ сразу без подписки
    if user_id in ADMIN_IDS:
        await callback.message.answer(
            "🎉 Регистрация завершена!\n\nКак админ, у тебя полный бесплатный доступ!",
            reply_markup=create_main_menu(user_lang)
        )
        return
    
    # Онбординг завершён - показываем выбор подписки
    complete_msg = get_text_lang(user_lang, "onboarding_complete")
    await callback.message.answer(complete_msg)
    
    # Показываем тарифы
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=get_text_lang(user_lang, "btn_basic"), callback_data="sub_basic")],
        [InlineKeyboardButton(text=get_text_lang(user_lang, "btn_premium"), callback_data="sub_premium")]
    ])
    
    await callback.message.answer(
        get_text_lang(user_lang, "choose_plan"),
        reply_markup=keyboard,
        parse_mode="Markdown"
    )


@dp.message(Onboarding.waiting_activity, F.text)
async def onboarding_activity_text(message: Message, state: FSMContext):
    """Handle activity if user writes instead of clicking"""
    if is_reset_command(message.text):
        user_id = message.from_user.id
        await clear_user_data(user_id)
        await state.clear()
        user_lang = await get_fact(user_id, "language") or "ru"
        await message.answer(get_text_lang(user_lang, "reset_done"), reply_markup=ReplyKeyboardRemove())
        return
    
    user_id = message.from_user.id
    user_lang = await get_fact(user_id, "language") or "ru"
    t = normalize_text(message.text).lower()
    
    if any(x in t for x in ["низ", "low", "nízk"]):
        activity = get_text_lang(user_lang, "activity_low_value")
    elif any(x in t for x in ["выс", "high", "vysok"]):
        activity = get_text_lang(user_lang, "activity_high_value")
    else:
        activity = get_text_lang(user_lang, "activity_medium_value")

    await set_facts(user_id, {"activity": activity, "job": ""})
    await state.clear()
    
    # Админы получают доступ сразу без подписки
    if user_id in ADMIN_IDS:
        await message.answer(
            "🎉 Регистрация завершена!\n\nКак админ, у тебя полный бесплатный доступ!",
            reply_markup=create_main_menu(user_lang)
        )
        return
    
    # Показываем выбор подписки
    complete_msg = get_text_lang(user_lang, "onboarding_complete")
    await message.answer(complete_msg)
    
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=get_text_lang(user_lang, "btn_basic"), callback_data="sub_basic")],
        [InlineKeyboardButton(text=get_text_lang(user_lang, "btn_premium"), callback_data="sub_premium")]
    ])
    
    await message.answer(
        get_text_lang(user_lang, "choose_plan"),
        reply_markup=keyboard,
        parse_mode="Markdown"
    )


# -------------------- photo handler --------------------
@dp.message(F.photo)
async def handle_photo(message: Message, state: FSMContext):
    """Handle photo with subscription check"""
    user_id = message.from_user.id
    user_lang = await get_fact(user_id, "language") or "ru"

    # Проверяем профиль
    missing = await profile_missing(user_id)
    if missing is not None:
        await message.answer(get_text_lang(user_lang, "photo_complete_first"))
        return

    # Проверяем подписку и лимиты
    can_analyze, error_key = await can_analyze_photo(user_id)
    if not can_analyze:
        if error_key == "photo_limit_reached":
            await message.answer(get_text_lang(user_lang, error_key, limit=BASIC_DAILY_PHOTO_LIMIT))
        else:
            await message.answer(get_text_lang(user_lang, error_key))
        return

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
        
        # Увеличиваем счётчик фото
        await increment_photo_count(user_id)
        
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
        await message.answer(get_text_lang(user_lang, "photo_process_error"))


# -------------------- voice handler --------------------
@dp.message(F.voice)
async def handle_voice(message: Message, state: FSMContext):
    """Handle voice messages"""
    user_id = message.from_user.id
    user_lang = await get_fact(user_id, "language") or "ru"
    
    # Проверяем подписку
    is_valid, error_key = await check_subscription_valid(user_id)
    if not is_valid:
        await message.answer(get_text_lang(user_lang, error_key))
        return
    
    status_msg = await message.answer(get_text_lang(user_lang, "voice_listening"))

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
            await message.answer(get_text_lang(user_lang, "voice_error"))
            return
        
        await message.answer(get_text_lang(user_lang, "voice_recognized", text=recognized_text))
        
        if is_reset_command(recognized_text):
            await clear_user_data(user_id)
            await state.clear()
            await message.answer(get_text_lang(user_lang, "reset_done"), reply_markup=ReplyKeyboardRemove())
            return
        
        current_state = await state.get_state()
        if current_state == Onboarding.waiting_name.state:
            name = normalize_text(recognized_text)
            if len(name) < 2 or len(name) > 30:
                await message.answer(get_text_lang(user_lang, "name_invalid"))
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
        
        missing = await profile_missing(user_id)
        if missing is not None:
            await message.answer(get_text_lang(user_lang, "complete_registration"))
            return
        
        low = recognized_text.lower()
        if any(x in low for x in ["привет", "здрав", "hello", "hi", "ahoj"]):
            name = await get_fact(user_id, "name") or "друг"
            await message.answer(get_text_lang(user_lang, "hello_response", name=name))
            return
        
        reply = await chat_reply(recognized_text, user_id)
        await message.answer(reply)
        
    except Exception as e:
        logger.error(f"Error handling voice: {e}", exc_info=True)
        try:
            await status_msg.delete()
        except:
            pass
        await message.answer(get_text_lang(user_lang, "voice_process_error"))


# -------------------- weight tracking --------------------
@dp.message(F.text.in_(ALL_MENU_WEIGH_IN))
async def menu_weigh_in(message: Message, state: FSMContext):
    """Handle weigh-in button"""
    user_id = message.from_user.id
    user_lang = await get_fact(user_id, "language") or "ru"
    
    # Проверяем подписку
    is_valid, error_key = await check_subscription_valid(user_id)
    if not is_valid:
        await message.answer(get_text_lang(user_lang, error_key))
        return
    
    await message.answer(get_text_lang(user_lang, "weigh_in_prompt"))
    await state.set_state(WeightTracking.waiting_weight)


@dp.message(WeightTracking.waiting_weight, F.text)
async def process_weight_input(message: Message, state: FSMContext):
    """Process weight input"""
    user_id = message.from_user.id
    user_lang = await get_fact(user_id, "language") or "ru"
    text = normalize_text(message.text)
    
    try:
        nums = re.findall(r'\d+\.?\d*', text)
        if not nums:
            await message.answer(get_text_lang(user_lang, "weight_invalid"))
            return
        
        new_weight = float(nums[0])
        
        if new_weight < 30 or new_weight > 350:
            await message.answer(get_text_lang(user_lang, "weight_unrealistic"))
            return
        
        old_weight_str = await get_fact(user_id, "weight_kg")
        old_weight = float(old_weight_str) if old_weight_str else new_weight
        
        await set_fact(user_id, "weight_kg", str(new_weight))
        
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
        
        if abs(diff) < 0.1:
            result = get_text_lang(user_lang, "weight_stable", weight=new_weight)
        elif diff > 0:
            emoji = "🔥" if diff >= 2 else "✨"
            result = get_text_lang(user_lang, "weight_down", weight=new_weight, diff=f"{diff:.1f}", emoji=emoji)
        else:
            result = get_text_lang(user_lang, "weight_up", weight=new_weight, diff=f"{abs(diff):.1f}")
        
        if len(history) > 1:
            first_weight = history[0]['weight']
            total_diff = first_weight - new_weight
            if abs(total_diff) > 0.1:
                if total_diff > 0:
                    emoji = "🔥🔥🔥" if total_diff >= 10 else "🔥🔥" if total_diff >= 5 else "🔥"
                    result += get_text_lang(user_lang, "weight_total_lost", diff=f"{total_diff:.1f}", emoji=emoji)
                else:
                    result += get_text_lang(user_lang, "weight_total_gained", diff=f"{abs(total_diff):.1f}")
        
        result += get_text_lang(user_lang, "weight_see_progress")
        
        await state.clear()
        await message.answer(result)
        
    except Exception as e:
        logger.error(f"Error processing weight: {e}", exc_info=True)
        await message.answer(get_text_lang(user_lang, "chat_error"))
        await state.clear()


# -------------------- menu buttons --------------------
@dp.message(F.text.in_(ALL_MENU_PHOTO))
async def menu_photo(message: Message):
    user_id = message.from_user.id
    user_lang = await get_fact(user_id, "language") or "ru"
    
    # Проверяем подписку
    is_valid, error_key = await check_subscription_valid(user_id)
    if not is_valid:
        await message.answer(get_text_lang(user_lang, error_key))
        return
    
    await message.answer(get_text_lang(user_lang, "photo_prompt"))


@dp.message(F.text.in_(ALL_MENU_QUESTION))
async def menu_question(message: Message):
    user_id = message.from_user.id
    user_lang = await get_fact(user_id, "language") or "ru"
    
    # Проверяем подписку
    is_valid, error_key = await check_subscription_valid(user_id)
    if not is_valid:
        await message.answer(get_text_lang(user_lang, error_key))
        return
    
    await message.answer(get_text_lang(user_lang, "question_prompt"))


@dp.message(F.text.in_(ALL_MENU_MEAL_PLAN))
async def menu_meal_plan(message: Message):
    user_id = message.from_user.id
    user_lang = await get_fact(user_id, "language") or "ru"
    
    # Проверяем подписку
    is_valid, error_key = await check_subscription_valid(user_id)
    if not is_valid:
        await message.answer(get_text_lang(user_lang, error_key))
        return
    
    name = await get_fact(user_id, "name") or "друг"
    goal = await get_fact(user_id, "goal") or "maintain"
    
    await message.answer(get_text_lang(user_lang, "meal_plan_loading", name=name, goal=goal))
    
    prompt = get_text_lang(user_lang, "gpt_meal_plan_prompt", goal=goal)
    reply = await chat_reply(prompt, user_id)
    await message.answer(get_text_lang(user_lang, "meal_plan_result", plan=reply))


@dp.message(F.text.in_(ALL_MENU_WORKOUT))
async def menu_workout(message: Message):
    user_id = message.from_user.id
    user_lang = await get_fact(user_id, "language") or "ru"
    
    # Проверяем подписку
    is_valid, error_key = await check_subscription_valid(user_id)
    if not is_valid:
        await message.answer(get_text_lang(user_lang, error_key))
        return
    
    name = await get_fact(user_id, "name") or "друг"
    goal = await get_fact(user_id, "goal") or "maintain"
    
    await message.answer(get_text_lang(user_lang, "workout_loading", name=name, goal=goal))
    
    prompt = get_text_lang(user_lang, "gpt_workout_prompt", goal=goal)
    reply = await chat_reply(prompt, user_id)
    await message.answer(get_text_lang(user_lang, "workout_result", plan=reply))


@dp.message(F.text.in_(ALL_MENU_PROGRESS))
async def menu_progress(message: Message):
    user_id = message.from_user.id
    user_lang = await get_fact(user_id, "language") or "ru"
    name = await get_fact(user_id, "name") or "друг"
    current_weight = await get_fact(user_id, "weight_kg") or "?"
    goal = await get_fact(user_id, "goal") or "?"
    
    weight_history_str = await get_fact(user_id, "weight_history")
    
    if not weight_history_str:
        progress = get_text_lang(user_lang, "progress_title", name=name)
        progress += get_text_lang(user_lang, "progress_current", weight=current_weight)
        progress += get_text_lang(user_lang, "progress_goal", goal=goal)
        progress += get_text_lang(user_lang, "progress_no_history")
        await message.answer(progress)
        return
    
    try:
        history = json.loads(weight_history_str)
        
        if not history or len(history) == 0:
            progress = get_text_lang(user_lang, "progress_title", name=name)
            progress += get_text_lang(user_lang, "progress_current", weight=current_weight)
            progress += get_text_lang(user_lang, "progress_goal", goal=goal)
            progress += get_text_lang(user_lang, "progress_no_history")
            await message.answer(progress)
            return
        
        history.sort(key=lambda x: x['date'])
        
        first_weight = history[0]['weight']
        last_weight = history[-1]['weight']
        total_diff = first_weight - last_weight
        
        progress_text = get_text_lang(user_lang, "progress_title", name=name)
        
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
                diff_str = "start" if user_lang == "en" else "начало" if user_lang == "ru" else "začátek"
            
            progress_text += f"{date}  ●━━  {weight} kg  {diff_str}\n"
        
        progress_text += f"\n{get_text_lang(user_lang, 'progress_goal', goal=goal)}"
        
        if total_diff > 0:
            progress_text += get_text_lang(user_lang, "progress_total_lost", diff=f"{total_diff:.1f}")
        elif total_diff < 0:
            progress_text += get_text_lang(user_lang, "progress_total_gained", diff=f"{abs(total_diff):.1f}")
        else:
            progress_text += get_text_lang(user_lang, "progress_stable")
        
        if total_diff > 0:
            days = len(history)
            days_word = get_days_word(user_lang, days)
            progress_text += get_text_lang(user_lang, "progress_days", days=days, days_word=days_word)
        
        await message.answer(progress_text)
        
    except Exception as e:
        logger.error(f"Error parsing weight history: {e}")
        progress = get_text_lang(user_lang, "progress_title", name=name)
        progress += get_text_lang(user_lang, "progress_current", weight=current_weight)
        progress += get_text_lang(user_lang, "progress_goal", goal=goal)
        progress += get_text_lang(user_lang, "progress_no_history")
        await message.answer(progress)


@dp.message(F.text.in_(ALL_MENU_SETTINGS))
async def menu_settings(message: Message):
    user_id = message.from_user.id
    user_lang = await get_fact(user_id, "language") or "ru"
    name = await get_fact(user_id, "name") or "?"
    goal = await get_fact(user_id, "goal") or "?"
    weight = await get_fact(user_id, "weight_kg") or "?"
    height = await get_fact(user_id, "height_cm") or "?"
    age = await get_fact(user_id, "age") or "?"
    activity = await get_fact(user_id, "activity") or "?"
    
    settings = get_text_lang(user_lang, "settings_title",
                             name=name, goal=goal, weight=weight,
                             height=height, age=age, activity=activity)
    
    await message.answer(settings)


# -------------------- default text handler --------------------
@dp.message(F.text)
async def handle_text(message: Message, state: FSMContext):
    """Handle all other text"""
    if is_reset_command(message.text):
        user_id = message.from_user.id
        await clear_user_data(user_id)
        await state.clear()
        user_lang = await get_fact(user_id, "language") or "ru"
        await message.answer(get_text_lang(user_lang, "reset_done"), reply_markup=ReplyKeyboardRemove())
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

    user_lang = await get_fact(user_id, "language") or "ru"
    
    # Проверяем подписку для обычных сообщений
    is_valid, error_key = await check_subscription_valid(user_id)
    if not is_valid:
        await message.answer(get_text_lang(user_lang, error_key))
        return
    
    low = text.lower()
    if any(x in low for x in ["привет", "здрав", "hello", "hi", "ahoj", "čau"]):
        name = await get_fact(user_id, "name") or "друг"
        menu = create_main_menu(user_lang)
        await message.answer(get_text_lang(user_lang, "hello_response", name=name), reply_markup=menu)
        return

    reply = await chat_reply(text, user_id)
    await message.answer(reply)


# -------------------- run --------------------
async def main():
    logger.info("🚀 Starting Dietitian Bot with Stripe...")
    logger.info(f"📊 GPT Model: {GPT_MODEL}")

    await init_db()
    logger.info("✅ Database initialized")

    # Создаём aiohttp app для webhook
    app = web.Application()
    app.router.add_post("/stripe/webhook", handle_stripe_webhook)
    
    # Запускаем webhook сервер в фоне
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", 8080)
    await site.start()
    logger.info("✅ Stripe webhook server started on port 8080")

    try:
        logger.info("🤖 Bot is polling...")
        await dp.start_polling(bot)
    finally:
        logger.info("🛑 Shutting down...")
        await runner.cleanup()
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
