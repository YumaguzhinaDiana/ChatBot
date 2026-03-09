import os
import telebot
import requests
from dotenv import load_dotenv
import logging
from typing import Dict, Optional, List
import time
from functools import wraps
import re
import random

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

load_dotenv()

TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
SPOONACULAR_API_KEY = os.getenv('SPOONACULAR_API_KEY')
DEEPSEEK_API_KEY = os.getenv('DEEPSEEK_API_KEY')

if not TELEGRAM_TOKEN or not SPOONACULAR_API_KEY or not DEEPSEEK_API_KEY:
    raise ValueError("Не найдены токены в .env файле")

bot = telebot.TeleBot(TELEGRAM_TOKEN)

SPOONACULAR_BASE_URL = "https://api.spoonacular.com"
DEEPSEEK_URL = "https://openrouter.ai/api/v1/chat/completions"
DEEPSEEK_MODEL = "deepseek/deepseek-r1"

AVAILABLE_EMOTIONS = [
    "грустно", "весело", "злой", "устал",
    "влюблен", "стресс", "счастлив", "одиноко",
    "ностальгия", "энергия", "романтика", "голоден"
]


def clean_deepseek_response(text: str) -> str:
    """Очистка ответа DeepSeek от тегов и лишнего текста"""
    if not text:
        return ""
    text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL)
    text = re.sub(r'<[^>]+>', '', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


def translate_with_deepseek(text: str, instruction: str) -> str:
    """Универсальная функция для перевода/обработки текста через DeepSeek"""
    if not text or not DEEPSEEK_API_KEY:
        return text

    try:
        headers = {
            "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
            "Content-Type": "application/json"
        }

        enhanced_instruction = instruction + "\n\n"
        enhanced_instruction += "Пример перевода ингредиентов:\n"
        enhanced_instruction += "• 1 teaspoon Allspice -> • 1 чайная ложка душистого перца\n"
        enhanced_instruction += "• 2 Apples -> • 2 яблока\n"
        enhanced_instruction += "• cup Packed brown sugar -> • стакан коричневого сахара\n"
        enhanced_instruction += "• 6 Carrots -> • 6 морковок\n"
        enhanced_instruction += "• 4 Celery stalks -> • 4 стебля сельдерея\n"
        enhanced_instruction += "• 1 Chicken, cut up -> • 1 курица, разделанная\n"
        enhanced_instruction += "• 8 cloves garlic -> • 8 зубчиков чеснока\n"
        enhanced_instruction += "• 1 large Onion -> • 1 большая луковица\n\n"
        enhanced_instruction += f"Текст для перевода:\n{text}"

        data = {
            "model": DEEPSEEK_MODEL,
            "messages": [{"role": "user", "content": enhanced_instruction}],
            "temperature": 0.3,
            "max_tokens": 2000
        }

        response = requests.post(
            DEEPSEEK_URL,
            headers=headers,
            json=data,
            timeout=30
        )

        if response.status_code == 200:
            result = response.json()
            content = result["choices"][0]["message"]["content"]
            return clean_deepseek_response(content)
        else:
            logger.error(f"Ошибка DeepSeek API: {response.status_code}")
            return text

    except Exception as e:
        logger.error(f"Ошибка при обращении к DeepSeek: {e}")
        return text


def translate_recipe_title(title: str) -> str:
    """Перевод названия рецепта на русский"""
    if not title:
        return "Рецепт"

    instruction = (
        "Переведи название рецепта на русский язык. "
        "Верни ТОЛЬКО переведенное название, без пояснений."
    )
    translated = translate_with_deepseek(title, instruction)
    return translated if translated else title


def get_search_query_by_emotion(emotion: str) -> str:
    """Получение поискового запроса для Spoonacular по эмоции через DeepSeek"""
    try:
        instruction = (
            f"Пользователь чувствует '{emotion}'. Придумай ОДИН поисковый запрос на АНГЛИЙСКОМ языке "
            f"для сайта с рецептами (Spoonacular), чтобы найти блюдо, которое идеально подходит под это настроение.\n\n"
            f"Запрос должен состоять из 1-3 слов на английском, которые помогут найти конкретные рецепты.\n\n"
            f"Примеры:\n"
            f"грустно → comfort food\n"
            f"весело → party food\n"
            f"энергия → protein breakfast\n\n"
            f"Верни ТОЛЬКО поисковый запрос, без пояснений и дополнительного текста."
        )

        headers = {
            "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
            "Content-Type": "application/json"
        }

        data = {
            "model": DEEPSEEK_MODEL,
            "messages": [{"role": "user", "content": instruction}],
            "temperature": 0.5,
            "max_tokens": 50
        }

        response = requests.post(
            DEEPSEEK_URL,
            headers=headers,
            json=data,
            timeout=30
        )

        if response.status_code == 200:
            result = response.json()
            content = result["choices"][0]["message"]["content"]
            query = clean_deepseek_response(content).strip().lower()
            logger.info(f"DeepSeek сгенерировал запрос для эмоции '{emotion}': {query}")
            return query
        else:
            logger.error(f"Ошибка DeepSeek API: {response.status_code}")
            return "food"

    except Exception as e:
        logger.error(f"Ошибка при получении поискового запроса: {e}")
        return "food"


def search_recipes_by_emotion(emotion: str, number: int = 3) -> Optional[List[Dict]]:
    """Поиск рецептов по эмоции через AI-сгенерированный запрос"""
    query = get_search_query_by_emotion(emotion)
    params = {
        'apiKey': SPOONACULAR_API_KEY,
        'query': query,
        'number': number,
        'sort': 'popularity',
        'sortDirection': 'desc'
    }

    try:
        response = requests.get(
            f"{SPOONACULAR_BASE_URL}/recipes/complexSearch",
            params=params,
            timeout=15
        )

        if response.status_code == 402:
            logger.error("Превышен лимит запросов Spoonacular API")
            return None

        response.raise_for_status()
        data = response.json()
        results = data.get('results', [])

        if results:
            logger.info(f"Найдено {len(results)} рецептов по запросу '{query}' для эмоции '{emotion}'")
        else:
            logger.info(f"Ничего не найдено по запросу '{query}', пробуем общий запрос")
            params['query'] = 'food'
            response = requests.get(
                f"{SPOONACULAR_BASE_URL}/recipes/complexSearch",
                params=params,
                timeout=15
            )
            response.raise_for_status()
            data = response.json()
            results = data.get('results', [])

        return results

    except Exception as e:
        logger.error(f"Ошибка поиска рецептов по эмоции: {e}")
        return None


def get_emotion_description(emotion: str, recipe_title: str) -> str:
    """Получение красивого описания почему это блюдо подходит под настроение"""
    try:
        instruction = (
            f"Пользователь чувствует '{emotion}'. Был найден рецепт '{recipe_title}'. "
            f"Напиши ОДНО короткое предложение на русском языке, почему это блюдо идеально подходит под это настроение.\n\n"
            f"Примеры:\n"
            f"грустно, 'Картофельное пюре с котлетой' → Теплое и нежное блюдо, которое согреет душу и напомнит о доме\n"
            f"весело, 'Радужный торт' → Яркий и красочный десерт, который поднимет настроение с первого взгляда\n"
            f"злой, 'Острая курица карри' → Обжигающая острота поможет выпустить пар и оставит приятное послевкусие\n\n"
            f"Верни ТОЛЬКО предложение, без пояснений."
        )

        headers = {
            "Authorization": f"Bearer {DEEPSEEK_API_KEY}",
            "Content-Type": "application/json"
        }

        data = {
            "model": DEEPSEEK_MODEL,
            "messages": [{"role": "user", "content": instruction}],
            "temperature": 0.7,
            "max_tokens": 100
        }

        response = requests.post(
            DEEPSEEK_URL,
            headers=headers,
            json=data,
            timeout=30
        )

        if response.status_code == 200:
            result = response.json()
            content = result["choices"][0]["message"]["content"]
            return clean_deepseek_response(content)
        else:
            return f"Идеальное блюдо для вашего настроения!"

    except Exception as e:
        logger.error(f"Ошибка при получении описания: {e}")
        return f"Идеальное блюдо для вашего настроения!"


def format_full_recipe(recipe: Dict) -> str:
    """Форматирование полного рецепта с переводом на русский"""
    try:
        translated_title = translate_recipe_title(recipe.get('title', 'Рецепт'))
        recipe_parts = []

        if recipe.get('readyInMinutes'):
            recipe_parts.append(f"⏱️ *Время:* {recipe['readyInMinutes']} минут")
        if recipe.get('servings'):
            recipe_parts.append(f"👥 *Порций:* {recipe['servings']}")

        if recipe_parts:
            recipe_parts.append("")

        if recipe.get('extendedIngredients'):
            recipe_parts.append("📝 *Ингредиенты:*")

            ingredients_list = []
            for ing in recipe['extendedIngredients']:
                ingredients_list.append(f"• {ing.get('original', '')}")

            ingredients_text = "\n".join(ingredients_list)

            translated_ingredients = translate_with_deepseek(
                ingredients_text,
                "Переведи список ингредиентов на русский язык. Сохрани формат с точками в начале строки. "
                "Переведи меры (teaspoon -> чайная ложка, cup -> стакан, tablespoon -> столовая ложка, cloves -> зубчики). "
                "Названия продуктов переведи на русский. Сохрани все числа и меры."
            )

            recipe_parts.append(translated_ingredients if translated_ingredients else ingredients_text)
            recipe_parts.append("")

        if recipe.get('instructions'):
            recipe_parts.append("*Приготовление:*")

            instructions = recipe['instructions']
            instructions = instructions.replace('<ol>', '').replace('</ol>', '')
            instructions = instructions.replace('<li>', '• ').replace('</li>', '\n')
            instructions = re.sub(r'<[^>]+>', '', instructions)

            translated_instructions = translate_with_deepseek(
                instructions,
                "Переведи инструкцию по приготовлению на русский язык. "
                "Сохрани формат с точками в начале шагов. "
                "Переведи температуру (350°F -> 175°C, 400°F -> 200°C и т.д.). "
                "Переведи все кулинарные термины понятно и подробно. "
                "Сохрани нумерацию шагов если она есть."
            )

            recipe_parts.append(translated_instructions if translated_instructions else instructions)
            recipe_parts.append("")

        if recipe.get('sourceUrl'):
            recipe_parts.append(f"[Полный рецепт (оригинал)]({recipe['sourceUrl']})")

        full_recipe = "\n".join(recipe_parts)

        return f"*{translated_title}*\n\n{full_recipe}"
    except Exception as e:
        logger.error(f"Ошибка форматирования рецепта: {e}")
        return f"*Рецепт*\n\nИзвините, произошла ошибка при форматировании рецепта."


def get_random_recipe() -> Optional[Dict]:
    """Получение случайного рецепта с обработкой ошибок"""
    params = {
        'apiKey': SPOONACULAR_API_KEY,
        'number': 1,
        'sort': 'random'
    }

    try:
        response = requests.get(
            f"{SPOONACULAR_BASE_URL}/recipes/random",
            params=params,
            timeout=15
        )

        if response.status_code == 402:
            logger.error("Превышен лимит запросов Spoonacular API")
            return None

        response.raise_for_status()
        data = response.json()

        if data and data.get('recipes') and len(data['recipes']) > 0:
            recipe = data['recipes'][0]
            return recipe
        return None

    except requests.exceptions.RequestException as e:
        logger.error(f"Ошибка получения случайного рецепта: {e}")
        return None


def get_recipe_details(recipe_id: int) -> Optional[Dict]:
    """Получение детальной информации о рецепте"""
    params = {
        'apiKey': SPOONACULAR_API_KEY,
        'includeNutrition': False
    }

    try:
        response = requests.get(
            f"{SPOONACULAR_BASE_URL}/recipes/{recipe_id}/information",
            params=params,
            timeout=15
        )

        if response.status_code == 402:
            logger.error("Превышен лимит запросов Spoonacular API")
            return None

        response.raise_for_status()
        return response.json()
    except Exception as e:
        logger.error(f"Ошибка получения деталей: {e}")
        return None


def create_main_keyboard():
    """Создание главной клавиатуры с кнопками"""
    markup = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(
        telebot.types.KeyboardButton("🍽️ Случайный рецепт"),
        telebot.types.KeyboardButton("😊 Рецепт по настроению"),
        telebot.types.KeyboardButton("🏠 Главное меню")
    )
    return markup


def create_emotions_keyboard():
    """Создание клавиатуры с эмоциями для выбора"""
    markup = telebot.types.InlineKeyboardMarkup(row_width=3)
    buttons = []
    for emotion in AVAILABLE_EMOTIONS:
        button = telebot.types.InlineKeyboardButton(
            text=emotion.capitalize(),
            callback_data=f"emotion_{emotion}"
        )
        buttons.append(button)

    markup.add(*buttons)

    markup.add(
        telebot.types.InlineKeyboardButton(
            text="Назад",
            callback_data="back_to_main"
        )
    )

    return markup


def handle_api_errors(func):
    @wraps(func)
    def wrapper(message, *args, **kwargs):
        try:
            return func(message, *args, **kwargs)
        except requests.exceptions.Timeout:
            bot.reply_to(message, "⏱️ Превышено время ожидания. Попробуйте позже.", reply_markup=create_main_keyboard())
        except requests.exceptions.ConnectionError:
            bot.reply_to(message, "🌐 Ошибка соединения. Проверьте интернет.", reply_markup=create_main_keyboard())
        except Exception as e:
            logger.error(f"Ошибка: {e}")
            bot.reply_to(message, "Произошла ошибка. Попробуйте еще раз.", reply_markup=create_main_keyboard())

    return wrapper


@bot.message_handler(commands=['start'])
def start_command(message):
    """Обработчик команды /start - приветствие"""
    welcome_text = (
        "👨‍🍳 *Что умеет этот бот?*\n\n"
        "Привет! Я умный кулинарный бот помощник.\n\n"
        "📋 *Команды:*\n"
        "• /start - это меню\n"
        "• /random - случайный рецепт\n"
        "• /create - рецепт по настроению (с выбором эмоции)\n\n"
        "Или просто нажми кнопку ниже!"
    )

    bot.send_message(
        message.chat.id,
        welcome_text,
        parse_mode='Markdown',
        reply_markup=create_main_keyboard()
    )


@bot.message_handler(commands=['random'])
@handle_api_errors
def random_command(message):
    """Обработчик команды /random - случайный рецепт"""
    send_random_recipe(message)


@bot.message_handler(commands=['create'])
@handle_api_errors
def create_command(message):
    """Обработчик команды /create - показать выбор эмоций"""
    emotions_text = "*Выберите ваше настроение из списка:*"

    bot.send_message(
        message.chat.id,
        emotions_text,
        parse_mode='Markdown',
        reply_markup=create_emotions_keyboard()
    )


@bot.callback_query_handler(func=lambda call: call.data.startswith('emotion_'))
@handle_api_errors
def emotion_callback_handler(call):
    """Обработчик выбора эмоции из inline клавиатуры"""
    emotion = call.data.replace('emotion_', '')
    bot.edit_message_reply_markup(
        call.message.chat.id,
        call.message.message_id,
        reply_markup=None
    )

    bot.answer_callback_query(call.id, f"Ищу рецепт для настроения: {emotion}")

    class TempMessage:
        def __init__(self, chat_id, text):
            self.chat = type('obj', (object,), {'id': chat_id})
            self.text = text
            self.from_user = call.from_user
            self.message_id = None

    temp_message = TempMessage(call.message.chat.id, f"/create {emotion}")
    process_emotion_recipe(temp_message, emotion)


@bot.callback_query_handler(func=lambda call: call.data == "back_to_main")
def back_to_main_callback(call):
    """Обработчик кнопки возврата в главное меню"""
    bot.answer_callback_query(call.id, "🏠 Возврат в меню")
    bot.delete_message(call.message.chat.id, call.message.message_id)
    start_command(call.message)


@bot.message_handler(func=lambda message: message.text == "🍽️ Случайный рецепт")
@handle_api_errors
def random_recipe_button_handler(message):
    """Обработчик кнопки случайного рецепта"""
    send_random_recipe(message)


@bot.message_handler(func=lambda message: message.text == "😊 Рецепт по настроению")
@handle_api_errors
def mood_recipe_button_handler(message):
    """Обработчик кнопки рецепта по настроению"""
    create_command(message)


@bot.message_handler(func=lambda message: message.text == "🏠 Главное меню")
def main_menu_button_handler(message):
    """Обработчик кнопки главного меню"""
    start_command(message)


def process_emotion_recipe(message, emotion):
    """Обработка рецепта по выбранной эмоции"""
    bot.send_chat_action(message.chat.id, 'typing')

    status_msg = bot.send_message(
        message.chat.id,
        f"*Анализирую настроение:* {emotion}\n\n*Подбираю идеальный рецепт...*",
        parse_mode='Markdown'
    )

    recipes = search_recipes_by_emotion(emotion, number=5)

    if recipes and len(recipes) > 0:
        selected_recipe = random.choice(recipes)
        recipe_title = selected_recipe.get('title', 'блюдо')

        bot.edit_message_text(
            f"*Настроение:* {emotion}\n\n"
            f"*Нашел подходящий рецепт...*\n\n"
            f"*Загружаю детали...*",
            message.chat.id,
            status_msg.message_id,
            parse_mode='Markdown'
        )

        recipe_details = get_recipe_details(selected_recipe['id'])

        if recipe_details:
            bot.delete_message(message.chat.id, status_msg.message_id)

            description = get_emotion_description(emotion, recipe_title)
            recipe_text = format_full_recipe(recipe_details)

            mood_header = f"😊 *Рецепт для настроения:* {emotion}\n💭 *Почему:* {description}\n\n"
            recipe_text = mood_header + recipe_text

            if recipe_details.get('image'):
                if len(recipe_text) > 1000:
                    bot.send_photo(
                        message.chat.id,
                        recipe_details['image']
                    )
                    bot.send_message(
                        message.chat.id,
                        recipe_text,
                        parse_mode='Markdown',
                        reply_markup=create_main_keyboard()
                    )
                else:
                    bot.send_photo(
                        message.chat.id,
                        recipe_details['image'],
                        caption=recipe_text,
                        parse_mode='Markdown',
                        reply_markup=create_main_keyboard()
                    )
            else:
                bot.send_message(
                    message.chat.id,
                    recipe_text,
                    parse_mode='Markdown',
                    reply_markup=create_main_keyboard()
                )
        else:
            translated_title = translate_recipe_title(recipe_title)
            bot.edit_message_text(
                f"😊 *Настроение:* {emotion}\n\n"
                f"✨ *Рекомендую:* {translated_title}\n\n"
                f"*К сожалению, не удалось загрузить полный рецепт.*\n"
                f"Попробуйте еще раз!",
                message.chat.id,
                status_msg.message_id,
                parse_mode='Markdown',
                reply_markup=create_main_keyboard()
            )
    else:
        bot.edit_message_text(
            f"😊 *Настроение:* {emotion}\n\n"
            f"😔 *Не смог подобрать рецепт*\n\n"
            f"Попробуйте другую эмоцию",
            message.chat.id,
            status_msg.message_id,
            parse_mode='Markdown',
            reply_markup=create_main_keyboard()
        )


@handle_api_errors
def send_random_recipe(message):
    """Отправка случайного рецепта"""
    bot.send_chat_action(message.chat.id, 'typing')

    status_msg = bot.send_message(
        message.chat.id,
        "🍳 *Ищу интересный рецепт...*",
        parse_mode='Markdown'
    )

    random_recipe = get_random_recipe()

    recipe_details = None
    if random_recipe and random_recipe.get('id'):
        recipe_details = get_recipe_details(random_recipe['id'])

    if not recipe_details:
        recipe_details = random_recipe

    bot.delete_message(message.chat.id, status_msg.message_id)

    try:
        recipe_text = format_full_recipe(recipe_details)

        if recipe_details and recipe_details.get('image'):
            if len(recipe_text) > 1000:
                bot.send_photo(
                    message.chat.id,
                    recipe_details['image']
                )
                bot.send_message(
                    message.chat.id,
                    recipe_text,
                    parse_mode='Markdown',
                    reply_markup=create_main_keyboard()
                )
            else:
                bot.send_photo(
                    message.chat.id,
                    recipe_details['image'],
                    caption=recipe_text,
                    parse_mode='Markdown',
                    reply_markup=create_main_keyboard()
                )
        else:
            bot.send_message(
                message.chat.id,
                recipe_text,
                parse_mode='Markdown',
                reply_markup=create_main_keyboard()
            )
    except Exception as e:
        logger.error(f"Ошибка отправки рецепта: {e}")
        bot.send_message(
            message.chat.id,
            "Произошла ошибка при отправке рецепта. Попробуйте еще раз.",
            reply_markup=create_main_keyboard()
        )


def main():
    """Запуск бота"""
    logger.info("Бот запущен и готов к работе!")
    bot.remove_webhook()

    while True:
        try:
            bot.infinity_polling(timeout=60, long_polling_timeout=60)
        except KeyboardInterrupt:
            print("\n👋 Бот остановлен")
            break
        except Exception as e:
            logger.error(f"Ошибка: {e}")
            print(f"Ошибка: {e}")
            print("Перезапуск через 5 секунд...")
            time.sleep(5)


if __name__ == '__main__':
    main()
