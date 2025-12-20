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

🌟 Я работаю на **GPT-5.2** - самой современной AI модели!

Готов помочь тебе следить за питанием! 💪""",
        
        "cs": """👋 **Ahoj! Jsem tvůj osobní dietolog-bot!**

📸 Pošli mi fotku svého jídla a já:
• Určím všechny ingredience
• Spočítám kalorie a BZCH
• Dám hodnocení nutriční hodnoty

🌟 Používám **GPT-5.2** - nejmodernější AI model!

Jsem připraven ti pomoci sledovat tvou stravu! 💪""",
        
        "en": """👋 **Hello! I'm your personal dietitian bot!**

📸 Send me a photo of your food, and I will:
• Identify all ingredients
• Calculate calories and macros
• Provide nutritional assessment

🌟 I'm powered by **GPT-5.2** - the latest AI model!

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
    
    "analyzing_photo": {
        "ru": "Анализирую фото с помощью GPT-5.2...",
        "cs": "Analyzuji fotku pomocí GPT-5.2...",
        "en": "Analyzing photo with GPT-5.2..."
    },
    
    "error": {
        "ru": "❌ Упс! Не смог проанализировать фото. Попробуй другое фото или напиши /help",
        "cs": "❌ Ups! Nemohl jsem analyzovat fotku. Zkus jinou fotku nebo napiš /help",
        "en": "❌ Oops! Couldn't analyze the photo. Try another photo or type /help"
    },
    
    "encouragement": {
        "ru": "🎯 Отличный выбор! Продолжай следить за питанием! 💪",
        "cs": "🎯 Skvělá volba! Pokračuj ve sledování své stravy! 💪",
        "en": "🎯 Great choice! Keep tracking your nutrition! 💪"
    }
}


def detect_language(text: str) -> str:
    """
    Detect language from text
    Simple detection based on common words
    """
    text_lower = text.lower()
    
    # Russian keywords
    russian_keywords = ['привет', 'помощь', 'спасибо', 'еда', 'калории']
    # Czech keywords
    czech_keywords = ['ahoj', 'pomoc', 'díky', 'jídlo', 'kalorie']
    # English keywords  
    english_keywords = ['hello', 'help', 'thanks', 'food', 'calories']
    
    # Count matches
    ru_count = sum(1 for word in russian_keywords if word in text_lower)
    cs_count = sum(1 for word in czech_keywords if word in text_lower)
    en_count = sum(1 for word in english_keywords if word in text_lower)
    
    # Detect by Cyrillic characters
    if any('\u0400' <= char <= '\u04FF' for char in text):
        return 'ru'
    
    # Detect by Czech characters
    czech_chars = 'ěščřžýáíéůú'
    if any(char in text_lower for char in czech_chars):
        return 'cs'
    
    # Return language with most matches
    if ru_count > 0 or cs_count > 0 or en_count > 0:
        max_lang = max([('ru', ru_count), ('cs', cs_count), ('en', en_count)], key=lambda x: x[1])
        return max_lang[0]
    
    # Default to English
    return 'en'


def get_text(key: str, lang: str = 'en') -> str:
    """
    Get text in specified language
    Falls back to English if translation not found
    """
    if key not in TEXTS:
        return f"Text '{key}' not found"
    
    if lang not in TEXTS[key]:
        lang = 'en'
    
    return TEXTS[key][lang]
