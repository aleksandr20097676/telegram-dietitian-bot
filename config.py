"""
Configuration file for Telegram Dietitian Bot
"""

import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Telegram Bot Token
TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN', '')

# OpenAI API Key
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY', '')

# Database
DATABASE_NAME = 'dietitian_bot.db'

# Supported languages
SUPPORTED_LANGUAGES = ['ru', 'cs', 'en']
DEFAULT_LANGUAGE = 'en'

# OpenAI settings
OPENAI_MODEL = 'gpt-5.2'  # Latest GPT-5.2 model
OPENAI_MAX_TOKENS = 2000
OPENAI_TEMPERATURE = 0.3

# Bot settings
ANIMATION_SPEED = 0.5  # seconds between animation frames
