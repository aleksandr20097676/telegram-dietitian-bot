import os

# Telegram
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN", "")

# OpenAI
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
GPT_MODEL = os.getenv("GPT_MODEL", "gpt-4o")

# Stripe
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY", "sk_test_51S7iLaIUVQyE7u4k...")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET", "whsec_...")
STRIPE_PRICE_BASIC = os.getenv("STRIPE_PRICE_BASIC", "price_1SibahIUVQyE7u4kbYsicAbT")
STRIPE_PRICE_PREMIUM = os.getenv("STRIPE_PRICE_PREMIUM", "price_1SibciIUVQyE7u4kHlOdB7BF")

# Subscription settings
BASIC_DAILY_PHOTO_LIMIT = int(os.getenv("BASIC_DAILY_PHOTO_LIMIT", "10"))
TRIAL_DAYS = int(os.getenv("TRIAL_DAYS", "1"))
