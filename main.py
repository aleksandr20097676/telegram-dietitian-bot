#!/usr/bin/env python3
"""
Telegram Dietitian Bot - Photo Food Analysis
Uses OpenAI GPT-4 Vision for food recognition and calorie calculation
"""

import asyncio
import logging
import base64
from io import BytesIO
from aiogram import Bot, Dispatcher, F
from aiogram.filters import Command
from aiogram.types import Message, BufferedInputFile
from aiogram.fsm.storage.memory import MemoryStorage
import httpx 
from openai import AsyncOpenAI
import aiofiles

# Import configuration
from config import TELEGRAM_TOKEN, OPENAI_API_KEY, GPT_MODEL
from database import FOOD_DATABASE
from languages import TEXTS, detect_language, get_text

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Initialize OpenAI client
http_client = httpx.AsyncClient(timeout=60.0)

openai_client = AsyncOpenAI(
    api_key=OPENAI_API_KEY,
    http_client=http_client)



# Initialize bot and dispatcher
bot = Bot(token=TELEGRAM_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)


async def analyze_food_photo(photo_bytes: bytes, user_language: str) -> str:
    """
    Analyze food photo using GPT-4 Vision API
    
    Args:
        photo_bytes: Image bytes
        user_language: User's language code
        
    Returns:
        Analysis result text
    """
    try:
        # Convert photo to base64
        base64_image = base64.b64encode(photo_bytes).decode('utf-8')
        
        # Create database description
        db_description = "Available food database:\n"
        for food_name, food_data in FOOD_DATABASE.items():
            db_description += f"- {food_name}: {food_data['calories']} kcal per {food_data['portion']}, "
            db_description += f"Protein: {food_data['protein']}g, Carbs: {food_data['carbs']}g, Fat: {food_data['fat']}g\n"
        
        # Prepare prompt based on language
        prompt = get_text(user_language, 'analysis_prompt').format(
            db_description=db_description
        )
        
        # Call GPT-4 Vision API
        response = await openai_client.chat.completions.create(
            model=GPT_MODEL,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": prompt
                        },
                        {
                            "type": "image_url",
                            "image_url": {
                                "url": f"data:image/jpeg;base64,{base64_image}",
                                "detail": "high"
                            }
                        }
                    ]
                }
            ],
            max_tokens=1000,
            temperature=0.7
        )
        
        # Extract result
        result = response.choices[0].message.content
        logger.info(f"Analysis completed for {user_language} language")
        return result
        
    except Exception as e:
        logger.error(f"Error analyzing photo: {e}")
        return get_text(user_language, 'error_analysis')
    async def chat_reply(user_text: str, user_language: str) -> str:
    """
    Simple conversational reply (no photo). Uses GPT model from config.
    """
    try:
        system_ru = (
            "Ты дружелюбный и умный диетолог. Общайся как человек: "
            "задай 1-2 уточняющих вопроса, предложи план, отвечай коротко и по делу. "
            "Если человек хочет — попроси рост/вес/цель/активность. "
            "Если уместно — предложи прислать фото еды для точного подсчёта."
        )
        system_cs = (
            "Jsi přátelský a chytrý dietolog. Mluv jako člověk: "
            "polož 1–2 doplňující otázky, navrhni plán, odpovídej stručně a věcně. "
            "Když je to potřeba, zeptej se na výšku/váhu/cíl/aktivitu. "
            "Když se hodí, nabídni poslat fotku jídla pro přesnější výpočet."
        )
        system_en = (
            "You are a friendly and smart dietitian. Talk like a human: "
            "ask 1–2 clarifying questions, suggest a plan, keep it concise and useful. "
            "If needed, ask height/weight/goal/activity. "
            "If relevant, suggest sending a food photo for accurate calculation."
        )

        system_map = {"ru": system_ru, "cs": system_cs, "en": system_en}
        system_prompt = system_map.get(user_language, system_en)

        resp = await openai_client.chat.completions.create(
            model=GPT_MODEL,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_text},
            ],
            max_tokens=400,
            temperature=0.7,
        )

        return resp.choices[0].message.content.strip()

    except Exception as e:
        logger.error(f"Error in chat_reply: {e}")
        return get_text(user_language, "error_general")
      


@dp.message(Command("start"))
async def cmd_start(message: Message):
    """Handle /start command"""
    user_language = detect_language(message.from_user.language_code)
    await message.answer(get_text(user_language, 'welcome'))


@dp.message(Command("help"))
async def cmd_help(message: Message):
    """Handle /help command"""
    user_language = detect_language(message.from_user.language_code)
    await message.answer(get_text(user_language, 'help'))


@dp.message(F.photo)
async def handle_photo(message: Message):
    """Handle photo messages"""
    user_language = detect_language(message.from_user.language_code)
    
    try:
        # Send "analyzing" message
        status_msg = await message.answer(get_text(user_language, 'analyzing'))
        
        # Get photo
        photo = message.photo[-1]  # Get highest resolution
        
        # Download photo
        photo_file = await bot.get_file(photo.file_id)
        photo_bytes = await bot.download_file(photo_file.file_path)
        
        # Analyze photo
        result = await analyze_food_photo(photo_bytes.read(), user_language)
        
        # Delete status message
        await status_msg.delete()
        
        # Send result
        await message.answer(result)
        
    except Exception as e:
        logger.error(f"Error handling photo: {e}")
        await message.answer(get_text(user_language, 'error_general'))


@dp.message()
@dp.message()
async def handle_text(message: Message):
    user_language = detect_language(message.from_user.language_code)
    text = (message.text or "").strip().lower()

    greetings = ["привет", "здравств", "hello", "hi", "ahoj", "čau"]
    if any(g in text for g in greetings):
        await message.answer(get_text(user_language, "greeting"))
        return

    reply = await chat_reply(message.text, user_language)
    await message.answer(reply)


async def main():
    """Main function to run the bot"""
    logger.info("Starting Telegram Dietitian Bot...")
    logger.info(f"Using {GPT_MODEL} for food analysis")
    
    try:
        # Start polling
        await dp.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
