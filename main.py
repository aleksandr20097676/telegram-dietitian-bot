"""
Telegram Dietitian Bot with GPT-5.2 Vision
Multilingual support: Russian, Czech, English
"""

import asyncio
import logging
from aiogram import Bot, Dispatcher, F
from aiogram.filters import CommandStart
from aiogram.types import Message, BufferedInputFile
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
import base64
from openai import AsyncOpenAI
from database import Database
from languages import get_text, detect_language
from config import TELEGRAM_TOKEN, OPENAI_API_KEY
import io

# Logging setup
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Initialize
bot = Bot(token=TELEGRAM_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
openai_client = AsyncOpenAI(api_key=str(OPENAI_API_KEY), http_client=None)
db = Database()

# States
class BotStates(StatesGroup):
    waiting_for_photo = State()


async def send_animation(message: Message, animation_type: str, lang: str):
    """Send animated messages for better UX"""
    animations = {
        "analyzing": [
            "🔍", "🔎", "🔍", "🔎"
        ],
        "processing": [
            "⏳", "⌛", "⏳", "⌛"
        ],
        "calculating": [
            "🧮", "📊", "🧮", "📊"
        ]
    }
    
    texts = {
        "analyzing": {
            "ru": "Анализирую фото",
            "cs": "Analyzuji fotku",
            "en": "Analyzing photo"
        },
        "processing": {
            "ru": "Обрабатываю данные",
            "cs": "Zpracovávám data",
            "en": "Processing data"
        },
        "calculating": {
            "ru": "Рассчитываю калории",
            "cs": "Počítám kalorie",
            "en": "Calculating calories"
        }
    }
    
    emoji_sequence = animations.get(animation_type, ["⏳"])
    text_base = texts.get(animation_type, {}).get(lang, "Processing")
    
    msg = await message.answer(f"{emoji_sequence[0]} {text_base}...")
    
    for i in range(1, 4):
        await asyncio.sleep(0.5)
        emoji = emoji_sequence[i % len(emoji_sequence)]
        await msg.edit_text(f"{emoji} {text_base}{'.' * (i + 1)}")
    
    return msg


async def analyze_food_photo(photo_bytes: bytes, lang: str) -> dict:
    """Analyze food photo using GPT-5.2 Vision"""
    
    # Convert to base64
    base64_image = base64.b64encode(photo_bytes).decode('utf-8')
    
    # Multilingual prompts
    prompts = {
        "ru": """Проанализируй это фото еды. Определи:
1. Все ингредиенты и продукты на фото
2. Примерный вес каждого ингредиента в граммах
3. Общую калорийность блюда
4. Белки, жиры, углеводы (БЖУ)

Ответь ТОЛЬКО в формате JSON:
{
  "ingredients": [
    {"name": "название", "weight_g": число, "calories": число, "protein": число, "fat": число, "carbs": число}
  ],
  "total": {
    "calories": число,
    "protein": число,
    "fat": число,
    "carbs": число
  },
  "dish_name": "название блюда"
}""",
        "cs": """Analyzuj tuto fotku jídla. Urči:
1. Všechny ingredience a produkty na fotce
2. Přibližnou hmotnost každé ingredience v gramech
3. Celkovou kalorickou hodnotu pokrmu
4. Bílkoviny, tuky, sacharidy (BZCH)

Odpověz POUZE ve formátu JSON:
{
  "ingredients": [
    {"name": "název", "weight_g": číslo, "calories": číslo, "protein": číslo, "fat": číslo, "carbs": číslo}
  ],
  "total": {
    "calories": číslo,
    "protein": číslo,
    "fat": číslo,
    "carbs": číslo
  },
  "dish_name": "název pokrmu"
}""",
        "en": """Analyze this food photo. Determine:
1. All ingredients and products in the photo
2. Approximate weight of each ingredient in grams
3. Total calorie content of the dish
4. Proteins, fats, carbohydrates (macros)

Answer ONLY in JSON format:
{
  "ingredients": [
    {"name": "name", "weight_g": number, "calories": number, "protein": number, "fat": number, "carbs": number}
  ],
  "total": {
    "calories": number,
    "protein": number,
    "fat": number,
    "carbs": number
  },
  "dish_name": "dish name"
}"""
    }
    
    try:
        response = await openai_client.chat.completions.create(
            model="gpt-5.2",  # Latest GPT-5.2
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": prompts.get(lang, prompts["en"])
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{base64_image}",
                                "detail": "high"  # High detail for better analysis
                            }
                        }
                    ]
                }
            ],
            max_tokens=2000,
            temperature=0.3  # Lower temperature for more consistent results
        )
        
        # Parse JSON response
        import json
        result_text = response.choices[0].message.content
        
        # Clean up response (remove markdown if present)
        result_text = result_text.replace("```json", "").replace("```", "").strip()
        
        result = json.loads(result_text)
        return result
        
    except Exception as e:
        logger.error(f"Error analyzing photo: {e}")
        return None


def format_nutrition_result(data: dict, lang: str) -> str:
    """Format nutrition data into beautiful message"""
    
    if not data:
        return get_text("error", lang)
    
    # Headers
    headers = {
        "ru": "🍽 **{}**\n\n📊 **Пищевая ценность:**\n\n",
        "cs": "🍽 **{}**\n\n📊 **Nutriční hodnoty:**\n\n",
        "en": "🍽 **{}**\n\n📊 **Nutritional Value:**\n\n"
    }
    
    ingredient_headers = {
        "ru": "🥗 **Ингредиенты:**\n",
        "cs": "🥗 **Ingredience:**\n",
        "en": "🥗 **Ingredients:**\n"
    }
    
    total_headers = {
        "ru": "\n💪 **Общая информация:**\n",
        "cs": "\n💪 **Celkové informace:**\n",
        "en": "\n💪 **Total Information:**\n"
    }
    
    result = headers[lang].format(data.get('dish_name', 'Блюдо'))
    
    # Ingredients
    result += ingredient_headers[lang]
    for ing in data.get('ingredients', []):
        result += f"• {ing['name']} ({ing['weight_g']}г) - {ing['calories']} ккал\n"
        result += f"  Б: {ing['protein']}г | Ж: {ing['fat']}г | У: {ing['carbs']}г\n\n"
    
    # Total
    total = data.get('total', {})
    result += total_headers[lang]
    result += f"🔥 Калории: **{total.get('calories', 0)} ккал**\n"
    result += f"🥩 Белки: **{total.get('protein', 0)}г**\n"
    result += f"🧈 Жиры: **{total.get('fat', 0)}г**\n"
    result += f"🍞 Углеводы: **{total.get('carbs', 0)}г**\n"
    
    return result


@dp.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext):
    """Start command handler"""
    lang = detect_language(message.text)
    
    # Save user language
    await state.update_data(lang=lang)
    
    welcome_text = get_text("welcome", lang)
    await message.answer(welcome_text, parse_mode="Markdown")


@dp.message(F.photo)
async def handle_photo(message: Message, state: FSMContext):
    """Handle food photo"""
    # Get user language
    user_data = await state.get_data()
    lang = user_data.get('lang', 'en')
    
    try:
        # Show analyzing animation
        anim_msg = await send_animation(message, "analyzing", lang)
        
        # Download photo
        photo = message.photo[-1]  # Get highest resolution
        photo_file = await bot.download(photo)
        photo_bytes = photo_file.read()
        
        # Update animation
        await anim_msg.edit_text(f"🔍 {get_text('analyzing_photo', lang)}")
        
        # Analyze with GPT-5.2
        result = await analyze_food_photo(photo_bytes, lang)
        
        # Delete animation message
        await anim_msg.delete()
        
        if result:
            # Format and send result
            formatted_result = format_nutrition_result(result, lang)
            await message.answer(formatted_result, parse_mode="Markdown")
            
            # Send encouragement
            await message.answer(get_text("encouragement", lang))
        else:
            await message.answer(get_text("error", lang))
            
    except Exception as e:
        logger.error(f"Error handling photo: {e}")
        await message.answer(get_text("error", lang))


@dp.message()
async def handle_text(message: Message, state: FSMContext):
    """Handle text messages"""
    lang = detect_language(message.text)
    await state.update_data(lang=lang)
    
    # Check for commands
    text_lower = message.text.lower()
    
    if any(word in text_lower for word in ['help', 'помощь', 'pomoc', 'nápověda']):
        await message.answer(get_text("help", lang), parse_mode="Markdown")
    else:
        await message.answer(get_text("send_photo", lang))


async def main():
    """Main function"""
    logger.info("Starting Telegram Dietitian Bot...")
    logger.info("Using GPT-5.2 for food analysis")
    
    # Initialize database
    db.init_db()
    
    # Start bot
    await dp.start_polling(bot)


if __name__ == '__main__':
    asyncio.run(main())
