"""
Multilingual text support for Telegram Dietitian Bot
Languages: Russian (ru), Czech (cs), English (en)
"""

TEXTS = {
    "welcome": {
        "ru": """👋 **Привет! Я твой персональный диетолог-бот!**

📸 Отправь мне фото своей еды, и я:
• Определю все ингредиенты
• Рассчитаю калории и БЖУ
• Дам оценку пищевой ценности

🌟 Я работаю на GPT-4 - современной AI модели!

Готов помочь тебе следить за питанием! 💪""",
        
        "cs": """👋 **Ahoj! Jsem tvůj osobní dietolog-bot!**

📸 Pošli mi fotku svého jídla a já:
• Určím všechny ingredience
• Spočítám kalorie a BZCH
• Dám hodnocení nutriční hodnoty

🌟 Používám GPT-4 - moderní AI model!

Jsem připraven ti pomoci sledovat tvou stravu! 💪""",
        
        "en": """👋 **Hello! I'm your personal dietitian bot!**

📸 Send me a photo of your food, and I will:
• Identify all ingredients
• Calculate calories and macros
• Provide nutritional assessment

🌟 I'm powered by GPT-4 - modern AI model!

Ready to help you track your nutrition! 💪"""
    },
    
    "help": {
        "ru": """ℹ️ **Как пользоваться ботом:**

1. 📸 Сфотографируй свою еду
2. 📤 Отправь фото мне
3. ⏳ Подожди анализа (5-10 секунд)
4. 📊 Получи полную информацию!

**Что я умею:**
✅ Анализировать фото еды
✅ Определять ингредиенты
✅ Рассчитывать калории
✅ Показывать БЖУ
✅ Работать на русском, чешском и английском

💡 **Совет:** Фотографируй еду при хорошем освещении для лучших результатов!""",
        
        "cs": """ℹ️ **Jak používat bota:**

1. 📸 Vyfoť své jídlo
2. 📤 Pošli mi fotku
3. ⏳ Počkej na analýzu (5-10 sekund)
4. 📊 Získej kompletní informace!

**Co umím:**
✅ Analyzovat fotky jídla
✅ Určovat ingredience
✅ Počítat kalorie
✅ Zobrazovat BZCH
✅ Pracovat v ruštině, češtině a angličtině

💡 **Tip:** Fotit jídlo při dobrém osvětlení pro lepší výsledky!""",
        
        "en": """ℹ️ **How to use the bot:**

1. 📸 Take a photo of your food
2. 📤 Send me the photo
3. ⏳ Wait for analysis (5-10 seconds)
4. 📊 Get complete information!

**What I can do:**
✅ Analyze food photos
✅ Identify ingredients
✅ Calculate calories
✅ Show macros
✅ Work in Russian, Czech, and English

💡 **Tip:** Take photos in good lighting for best results!"""
    },
    
    "send_photo": {
        "ru": "📸 Отправь мне фото еды, чтобы я мог его проанализировать!",
        "cs": "📸 Pošli mi fotku jídla, abych ji mohl analyzovat!",
        "en": "📸 Send me a photo of food so I can analyze it!"
    },
    
    "analyzing": {
        "ru": "⏳ Анализирую фото...",
        "cs": "⏳ Analyzuji fotku...",
        "en": "⏳ Analyzing photo..."
    },
    
    "error_analysis": {
        "ru": "❌ Не смог проанализировать фото. Попробуй другое фото.",
        "cs": "❌ Nemohl jsem analyzovat fotku. Zkus jinou fotku.",
        "en": "❌ Couldn't analyze the photo. Try another photo."
    },
    
    "error_general": {
        "ru": "❌ Произошла ошибка. Попробуй еще раз или напиши /help",
        "cs": "❌ Došlo k chybě. Zkus to znovu nebo napiš /help",
        "en": "❌ An error occurred. Try again or type /help"
    },
    
    "analysis_prompt": {
        "ru": """Ты опытный диетолог. Проанализируй фото еды и предоставь:

1. **Список ингредиентов** - что ты видишь на фото
2. **Расчет калорий** - используй базу данных ниже для точного расчета
3. **БЖУ** - белки, жиры, углеводы в граммах
4. **Оценка** - здоровое ли это блюдо

{db_description}

Будь точным и конкретным в расчетах!""",
        
        "cs": """Jsi zkušený dietolog. Analyzuj fotku jídla a poskytni:

1. **Seznam ingrediencí** - co vidíš na fotce
2. **Výpočet kalorií** - použij níže uvedenou databázi pro přesný výpočet
3. **BZCH** - bílkoviny, tuky, sacharidy v gramech
4. **Hodnocení** - je to zdravé jídlo

{db_description}

Buď přesný a konkrétní ve výpočtech!""",
        
        "en": """You are an experienced dietitian. Analyze the food photo and provide:

1. **Ingredient List** - what you see in the photo
2. **Calorie Calculation** - use the database below for accurate calculation
3. **Macros** - protein, fat, carbs in grams
4. **Assessment** - is this a healthy dish

{db_description}

Be precise and specific in calculations!"""
    },
    "greeting": {
    "ru": "Привет! 😊 Как дела? Я твой AI-диетолог. Хочешь похудеть, набрать форму или просто разобраться с питанием?",
    "cs": "Ahoj! 😊 Jak se máš? Jsem tvůj AI dietolog. Chceš zhubnout, zlepšit formu nebo se jen poradit o jídle?",
    "en": "Hi! 😊 How are you? I’m your AI dietitian. Do you want to lose weight, get in shape, or just understand nutrition better?"
}

}


def detect_language(language_code: str) -> str:
    """
    Detect language from Telegram language code
    
    Args:
        language_code: Telegram user language code (e.g., 'ru', 'cs', 'en')
        
    Returns:
        Language code ('ru', 'cs', or 'en')
    """
    if not language_code:
        return 'en'
    
    language_code = language_code.lower()
    
    # Map language codes
    if language_code.startswith('ru'):
        return 'ru'
    elif language_code.startswith('cs') or language_code.startswith('cz'):
        return 'cs'
    else:
        return 'en'


def get_text(language: str, key: str) -> str:
    """
    Get text in specified language
    
    Args:
        language: Language code
        key: Text key
        
    Returns:
        Translated text
    """
    if key not in TEXTS:
        return f"Text '{key}' not found"
    
    if language not in TEXTS[key]:
        language = 'en'
    
    return TEXTS[key][language]
