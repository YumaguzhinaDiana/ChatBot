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
from transformer import UniversalDietDetector
from gigachat import GigaChat
from gigachat.models import Chat, Messages, MessagesRole

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

load_dotenv()

TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
SPOONACULAR_API_KEY = os.getenv('SPOONACULAR_API_KEY')
GIGACHAT_API_KEY = os.getenv('GIGACHAT_API_KEY')
HUGGINGFACE_API_KEY = os.getenv('HUGGINGFACE_API_KEY')

if not TELEGRAM_TOKEN or not SPOONACULAR_API_KEY or not GIGACHAT_API_KEY or not HUGGINGFACE_API_KEY:
    raise ValueError("Не найдены токены в .env файле")

bot = telebot.TeleBot(TELEGRAM_TOKEN)

SPOONACULAR_BASE_URL = "https://api.spoonacular.com"
diet_detector = UniversalDietDetector(HUGGINGFACE_API_KEY)

giga = GigaChat(credentials=GIGACHAT_API_KEY, verify_ssl_certs=False)

selected_command = ""

AVAILABLE_EMOTIONS = [
    "грустно", "весело", "злой", "устал",
    "влюблен", "стресс", "счастлив", "одиноко",
    "ностальгия", "энергия", "романтика", "голоден"
]


def clean_gigachat_response(text: str) -> str:
    """Очистка ответа GigaChat от лишнего текста"""
    if not text:
        return ""
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


def escape_markdown(text: str) -> str:
    """Экранирование специальных символов Markdown"""
    if not text:
        return ""
    special_chars = ['_', '*', '[', ']', '(', ')', '~', '`', '>', '#', '+', '-', '=', '|', '{', '}', '.', '!']
    for char in special_chars:
        text = text.replace(char, f'\\{char}')
    return text


def translate_with_gigachat(text: str, instruction: str) -> str:
    """Универсальная функция для перевода/обработки текста через GigaChat"""
    if not text or not GIGACHAT_API_KEY:
        return text

    try:
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

        payload = Chat(
            messages=[
                Messages(
                    role=MessagesRole.USER,
                    content=enhanced_instruction
                )
            ],
            temperature=0.3,
            max_tokens=2000
        )

        response = giga.chat(payload)

        if response and response.choices:
            content = response.choices[0].message.content
            return clean_gigachat_response(content)
        else:
            logger.error("Пустой ответ от GigaChat")
            return text

    except Exception as e:
        logger.error(f"Ошибка при обращении к GigaChat: {e}")
        return text


def translate_recipe_title(title: str) -> str:
    """Перевод названия рецепта на русский"""
    if not title:
        return "Рецепт"

    instruction = (
        "Переведи название рецепта на русский язык. "
        "Верни ТОЛЬКО переведенное название, без пояснений."
    )
    translated = translate_with_gigachat(title, instruction)
    return translated if translated else title


def get_search_query_by_emotion(emotion: str) -> str:
    """Получение поискового запроса для Spoonacular по эмоции через GigaChat"""
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

        payload = Chat(
            messages=[
                Messages(
                    role=MessagesRole.USER,
                    content=instruction
                )
            ],
            temperature=0.5,
            max_tokens=50
        )

        response = giga.chat(payload)

        if response and response.choices:
            content = response.choices[0].message.content
            query = clean_gigachat_response(content).strip().lower()
            logger.info(f"ИИ сгенерировал запрос для эмоции '{emotion}': {query}")
            return query
        else:
            logger.error("Пустой ответ от ИИ")
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
    logger.info(params)
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

        payload = Chat(
            messages=[
                Messages(
                    role=MessagesRole.USER,
                    content=instruction
                )
            ],
            temperature=0.7,
            max_tokens=100
        )

        response = giga.chat(payload)

        if response and response.choices:
            content = response.choices[0].message.content
            return clean_gigachat_response(content)
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

            translated_ingredients = translate_with_gigachat(
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

            translated_instructions = translate_with_gigachat(
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
        telebot.types.KeyboardButton("🎲 Случайный рецепт"),
        telebot.types.KeyboardButton("🎭 Рецепт по настроению"),
        telebot.types.KeyboardButton("🔎 Рецепт по названию"),
        telebot.types.KeyboardButton("🔍 Рецепт по ингредиентам"),
        telebot.types.KeyboardButton("🍴 Рецепты с учетом ограничений"),
        telebot.types.KeyboardButton("❓ Помощь"),
        telebot.types.KeyboardButton("🏠 Главное меню"),
        telebot.types.KeyboardButton("🚪 Выход")
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
            error_text = "⏱️ Превышено время ожидания. Попробуйте позже."
            if hasattr(message, 'message') and hasattr(message.message, 'chat'):
                bot.send_message(
                    message.message.chat.id,
                    error_text,
                    reply_markup=create_main_keyboard()
                )
            else:
                bot.reply_to(message, error_text, reply_markup=create_main_keyboard())
        except requests.exceptions.ConnectionError:
            error_text = "🌐 Ошибка соединения. Проверьте интернет."
            if hasattr(message, 'message') and hasattr(message.message, 'chat'):
                bot.send_message(
                    message.message.chat.id,
                    error_text,
                    reply_markup=create_main_keyboard()
                )
            else:
                bot.reply_to(message, error_text, reply_markup=create_main_keyboard())
        except telebot.apihelper.ApiTelegramException as e:
            if "message is not modified" in str(e):
                logger.debug("Сообщение не было изменено")
                pass
            elif "can't parse entities" in str(e):
                error_text = "Произошла ошибка форматирования. Попробуйте еще раз."
                if hasattr(message, 'message') and hasattr(message.message, 'chat'):
                    bot.send_message(
                        message.message.chat.id,
                        error_text,
                        reply_markup=create_main_keyboard()
                    )
                else:
                    bot.reply_to(message, error_text, reply_markup=create_main_keyboard())
            else:
                logger.error(f"Telegram API ошибка: {e}")
                error_text = f"Произошла ошибка. Попробуйте еще раз."
                if hasattr(message, 'message') and hasattr(message.message, 'chat'):
                    bot.send_message(
                        message.message.chat.id,
                        error_text,
                        reply_markup=create_main_keyboard()
                    )
                else:
                    bot.reply_to(message, error_text, reply_markup=create_main_keyboard())
        except Exception as e:
            logger.error(f"Ошибка: {e}")
            error_text = "Произошла ошибка. Попробуйте еще раз."
            if hasattr(message, 'message') and hasattr(message.message, 'chat'):
                bot.send_message(
                    message.message.chat.id,
                    error_text,
                    reply_markup=create_main_keyboard()
                )
            else:
                bot.reply_to(message, error_text, reply_markup=create_main_keyboard())

    return wrapper


@bot.message_handler(commands=['start'])
def start_command(message):
    welcome_text = (
        "👨‍🍳 Что умеет этот бот?\n\n"
        "Привет! Я умный кулинарный бот помощник.\n\n"
        "📋 Команды:\n"
        "/start - это меню\n"
        "/search название - поиск рецепта по названию\n"
        "/find продукты - поиск рецептов\n"
        "/random - случайный рецепт\n"
        "/create - рецепт по настроению (с выбором эмоции)\n"
        "/diet_find ограничения - поиск рецептов по диете\n"
        "/exit - выход с бота\n"
        "/help - подробная справка\n\n"
        "Приятного аппетита)"
    )
    bot.send_message(
        message.chat.id,
        welcome_text,
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


@bot.message_handler(commands=['help'])
def help_command(message):
    """Подробная справка"""
    global selected_command
    selected_command = "help"

    help_text = (
        "📚 *Подробная справка*\n\n"
        "*Как это работает:*\n"
        "1 Вы пишете продукты (на любом языке)\n"
        "2 ИИ переводит их для поиска\n"
        "3 Spoonacular находит рецепты\n"
        "4 **Рецепты сортируются по количеству совпадений**\n"
        "5 ИИ переводит рецепт на русский\n"
        "6 Вы получаете готовый рецепт!\n\n"
        "*Команды:*\n"
        "• `/start` - Главное меню\n"
        "• `/find [продукты]` - Поиск рецептов\n"
        "  Пример: `/find курица рис лук`\n"
        "• `/diet_find [ограничения]` - Поиск рецептов с учетом диет\n"
        "  Пример: `/diet_find вегетерианство без сахара`\n"
        "• `/random` - случайный рецепт\n"
        "• `/create [эмоция]` - рецепт по настроению\n"
        "• /exit - выход с бота\n"
        "• `/help` - Эта справка\n\n"
        "*Кнопки:*\n"
        "• 🔎 Рецепт по названию - быстрый поиск по названию\n"
        "• 🔍 Рецепт по ингредиентам - быстрый поиск по введенным ингредиентам\n"
        "• 🎲 Случайный рецепт\n"
        "• 🎭 Рецепт под настроение - быстрый поиск при выборе эмоции\n"
        "• 🍴 Рецепты с учетом ограничений - диетический поиск\n"
        "• 🚪 Выход"
        "• ❓ Помощь - показать справку\n"
        "• 🏠 Главное меню - вернуться\n\n"
        "✨ *Особенности:*\n"
        "• Понимает любой язык\n"
        "• Сортирует по лучшему совпадению\n"
        "• Полностью переводит рецепты\n"
        "• Показывает фото блюд"
    )

    bot.send_message(
        message.chat.id,
        help_text,
        parse_mode='Markdown',
        reply_markup=create_emotions_keyboard()
    )


@bot.callback_query_handler(func=lambda call: call.data.startswith('emotion_'))
@handle_api_errors
def emotion_callback_handler(call):
    """Обработчик выбора эмоции из inline клавиатуры"""
    emotion = call.data.replace('emotion_', '')

    try:
        bot.edit_message_reply_markup(
            call.message.chat.id,
            call.message.message_id,
            reply_markup=None
        )
    except telebot.apihelper.ApiTelegramException as e:
        if "message is not modified" in str(e):
            pass
        else:
            raise e

    bot.answer_callback_query(call.id, f"Ищу рецепт для настроения: {emotion}")

    class TempMessage:
        def __init__(self, chat_id, text, user_id):
            self.chat = type('obj', (object,), {'id': chat_id})
            self.text = text
            self.from_user = type('obj', (object,), {'id': user_id})
            self.message_id = None

    temp_message = TempMessage(call.message.chat.id, f"/create {emotion}", call.from_user.id)
    process_emotion_recipe(temp_message, emotion)


@bot.message_handler(func=lambda message: message.text == "🎲 Случайный рецепт")
@handle_api_errors
def random_recipe_button_handler(message):
    """Обработчик кнопки случайного рецепта"""
    send_random_recipe(message)


@bot.message_handler(func=lambda message: message.text == "🎭 Рецепт по настроению")
@handle_api_errors
def mood_recipe_button_handler(message):
    """Обработчик кнопки рецепта по настроению"""
    create_command(message)


@bot.message_handler(func=lambda message: message.text == "🏠 Главное меню")
def main_menu_button_handler(message):
    """Обработчик кнопки главного меню"""
    start_command(message)


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

            translated_ingredients = translate_with_gigachat(
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

            translated_instructions = translate_with_gigachat(
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


def send_recipe_with_photo(chat_id, photo_url, recipe_text, reply_markup=None):
    """Отправка рецепта с фото, автоматически разделяя если текст太长"""
    try:
        if len(recipe_text) <= 1024:
            bot.send_photo(
                chat_id,
                photo_url,
                caption=recipe_text,
                parse_mode='Markdown',
                reply_markup=reply_markup
            )
        else:
            bot.send_photo(
                chat_id,
                photo_url
            )
            bot.send_message(
                chat_id,
                recipe_text,
                parse_mode='Markdown',
                reply_markup=reply_markup
            )
    except telebot.apihelper.ApiTelegramException as e:
        if "can't parse entities" in str(e):
            if len(recipe_text) <= 1024:
                bot.send_photo(
                    chat_id,
                    photo_url,
                    caption=recipe_text.replace('*', '').replace('_', ''),
                    reply_markup=reply_markup
                )
            else:
                bot.send_photo(chat_id, photo_url)
                bot.send_message(
                    chat_id,
                    recipe_text.replace('*', '').replace('_', ''),
                    reply_markup=reply_markup
                )
        else:
            raise e


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

        try:
            bot.edit_message_text(
                f"*Настроение:* {emotion}\n\n"
                f"*Нашел подходящий рецепт...*\n\n"
                f"*Загружаю детали...*",
                message.chat.id,
                status_msg.message_id,
                parse_mode='Markdown'
            )
        except Exception as e:
            logger.error(f"Ошибка при редактировании сообщения: {e}")

        recipe_details = get_recipe_details(selected_recipe['id'])

        if recipe_details:
            try:
                bot.delete_message(message.chat.id, status_msg.message_id)
            except Exception as e:
                logger.error(f"Ошибка при удалении сообщения: {e}")

            description = get_emotion_description(emotion, recipe_title)
            recipe_text = format_full_recipe(recipe_details)

            mood_header = f"🎭 *Рецепт для настроения:* {emotion}\n💭 *Почему:* {description}\n\n"
            recipe_text = mood_header + recipe_text

            if recipe_details.get('image'):
                send_recipe_with_photo(
                    message.chat.id,
                    recipe_details['image'],
                    recipe_text,
                    create_main_keyboard()
                )
            else:
                try:
                    bot.send_message(
                        message.chat.id,
                        recipe_text,
                        parse_mode='Markdown',
                        reply_markup=create_main_keyboard()
                    )
                except telebot.apihelper.ApiTelegramException as e:
                    if "can't parse entities" in str(e):
                        bot.send_message(
                            message.chat.id,
                            recipe_text.replace('*', '').replace('_', ''),
                            reply_markup=create_main_keyboard()
                        )
                    else:
                        raise e
        else:
            translated_title = translate_recipe_title(recipe_title)
            try:
                bot.edit_message_text(
                    f"🎭 *Настроение:* {emotion}\n\n"
                    f"✨ *Рекомендую:* {translated_title}\n\n"
                    f"*К сожалению, не удалось загрузить полный рецепт.*\n"
                    f"Попробуйте еще раз!",
                    message.chat.id,
                    status_msg.message_id,
                    parse_mode='Markdown',
                    reply_markup=create_main_keyboard()
                )
            except Exception as e:
                logger.error(f"Ошибка при редактировании сообщения: {e}")
                bot.send_message(
                    message.chat.id,
                    f"🎭 Настроение: {emotion}\n\n"
                    f"✨ Рекомендую: {translated_title}\n\n"
                    f"К сожалению, не удалось загрузить полный рецепт.\n"
                    f"Попробуйте еще раз!",
                    reply_markup=create_main_keyboard()
                )
    else:
        try:
            bot.edit_message_text(
                f"🎭 *Настроение:* {emotion}\n\n"
                f"😔 *Не смог подобрать рецепт*\n\n"
                f"Попробуйте другую эмоцию",
                message.chat.id,
                status_msg.message_id,
                parse_mode='Markdown',
                reply_markup=create_main_keyboard()
            )
        except Exception as e:
            logger.error(f"Ошибка при редактировании сообщения: {e}")
            bot.send_message(
                message.chat.id,
                f"🎭 Настроение: {emotion}\n\n"
                f"😔 Не смог подобрать рецепт\n\n"
                f"Попробуйте другую эмоцию",
                reply_markup=create_main_keyboard()
            )


@bot.callback_query_handler(func=lambda call: call.data.startswith('recipe_'))
@handle_api_errors
def recipe_callback(call):
    """Показ полного рецепта"""
    recipe_id = int(call.data.split('_')[1])

    bot.answer_callback_query(call.id, "Загружаю рецепт...")
    bot.send_chat_action(call.message.chat.id, 'typing')

    status_msg = bot.send_message(
        call.message.chat.id,
        "Это может занять несколько секунд...",
        parse_mode='Markdown'
    )

    recipe_details = get_recipe_details(recipe_id)

    if recipe_details:
        recipe_text = format_full_recipe(recipe_details)

        try:
            bot.delete_message(call.message.chat.id, status_msg.message_id)
        except Exception as e:
            logger.error(f"Ошибка при удалении сообщения: {e}")

        if recipe_details.get('image'):
            send_recipe_with_photo(
                call.message.chat.id,
                recipe_details['image'],
                recipe_text,
                create_main_keyboard()
            )
        else:
            try:
                bot.send_message(
                    call.message.chat.id,
                    recipe_text,
                    parse_mode='Markdown',
                    reply_markup=create_main_keyboard()
                )
            except telebot.apihelper.ApiTelegramException as e:
                if "can't parse entities" in str(e):
                    bot.send_message(
                        call.message.chat.id,
                        recipe_text.replace('*', '').replace('_', ''),
                        reply_markup=create_main_keyboard()
                    )
                else:
                    raise e
    else:
        try:
            bot.edit_message_text(
                "😔 *Не удалось загрузить рецепт*",
                call.message.chat.id,
                status_msg.message_id,
                parse_mode='Markdown',
                reply_markup=create_main_keyboard()
            )
        except Exception as e:
            logger.error(f"Ошибка при редактировании сообщения: {e}")
            bot.send_message(
                call.message.chat.id,
                "😔 Не удалось загрузить рецепт",
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

    try:
        bot.delete_message(message.chat.id, status_msg.message_id)
    except Exception as e:
        logger.error(f"Ошибка при удалении сообщения: {e}")

    try:
        recipe_text = format_full_recipe(recipe_details)

        if recipe_details and recipe_details.get('image'):
            send_recipe_with_photo(
                message.chat.id,
                recipe_details['image'],
                recipe_text,
                create_main_keyboard()
            )
        else:
            try:
                bot.send_message(
                    message.chat.id,
                    recipe_text,
                    parse_mode='Markdown',
                    reply_markup=create_main_keyboard()
                )
            except telebot.apihelper.ApiTelegramException as e:
                if "can't parse entities" in str(e):
                    bot.send_message(
                        message.chat.id,
                        recipe_text.replace('*', '').replace('_', ''),
                        reply_markup=create_main_keyboard()
                    )
                else:
                    raise e
    except Exception as e:
        logger.error(f"Ошибка отправки рецепта: {e}")
        bot.send_message(
            message.chat.id,
            "Произошла ошибка при отправке рецепта. Попробуйте еще раз.",
            reply_markup=create_main_keyboard()
        )

@bot.message_handler(commands=['diet_find'])
@handle_api_errors
def diet_find_command(message):
    global selected_command
    command_parts = message.text.split(maxsplit=1)

    if len(command_parts) < 2:
        bot.reply_to(
            message,
            "*Напишите ограничения после /diet_find*\n\n"
            "Пример: `/diet_find вегетерианство без сахара`",
            parse_mode='Markdown',
            reply_markup=create_main_keyboard()
        )
        return
    selected_command = "diet_search"
    diet_analysis = diet_detector.analyze(message.text)

    if diet_analysis['all_restrictions']:
        restrictions = "\n".join(f"• {r}" for r in diet_analysis['all_restrictions'])
        bot.send_message(
            message.chat.id,
            f"✅ *Понял ваши ограничения:*\n{restrictions}",
            parse_mode='Markdown'
        )

    status_msg = bot.reply_to(
        message,
        f"🔍 *Ищу и сортирую рецепты...*\n\n",
        parse_mode='Markdown'
    )
    bot.edit_message_text(
        "🔍 *Ищу подходящие рецепты...*",
        message.chat.id,
        status_msg.message_id,
        parse_mode='Markdown'
    )

    recipes = search_with_diet(diet_analysis)
    logger.info(recipes)

    if not recipes:
        bot.edit_message_text(
            "😔 *Рецепты не найдены*\n\n"
            "Попробуйте другие продукты или нажмите /help",
            message.chat.id,
            status_msg.message_id,
            parse_mode='Markdown',
            reply_markup=create_main_keyboard()
        )
        return

    bot.delete_message(message.chat.id, status_msg.message_id)

    markup = telebot.types.InlineKeyboardMarkup(row_width=1)

    for recipe in recipes[:5]:
        translated_title = translate_recipe_title(recipe['title'])
        callback_data = f"recipe_{recipe['id']}"

        button_text = f"🎲 {translated_title[:35]}"

        button = telebot.types.InlineKeyboardButton(
            text=button_text,
            callback_data=callback_data
        )
        markup.add(button)

    markup.add(telebot.types.InlineKeyboardButton(
        "🏠 В главное меню",
        callback_data="back_to_main"
    ))

    info_text = (
        f"👇 *Выберите рецепт:*"
    )

    bot.send_message(
        message.chat.id,
        info_text,
        parse_mode='Markdown',
        reply_markup=markup
    )


def translate_ingredients_to_english(ingredients: List[str]) -> List[str]:
    """Перевод списка продуктов на английский для поиска"""
    ingredients_text = ", ".join(ingredients)

    instruction = (
        "Переведи следующие продукты на английский язык для поиска рецептов. "
        "Верни ТОЛЬКО переведенные слова через запятую, без пояснений, без цифр, без точек. "
        "Пример формата: chicken, potato, onion"
        "Ингредиенты состоящие из двух и более слов должны считаться как один ингредиент"
    )

    result = translate_with_gigachat(ingredients_text, instruction)

    translated = [item.strip().lower() for item in result.split(',') if item.strip()]

    if not translated:
        return [ing.lower() for ing in ingredients]

    logger.info(f"GigaChat перевел: {ingredients} -> {translated}")
    return translated


def search_recipes_by_ingredients(ingredients: List[str], number: int = 10) -> Optional[List[Dict]]:
    """Поиск рецептов по ингредиентам с сортировкой по совпадениям"""

    translated = translate_ingredients_to_english(ingredients)

    params = {
        'apiKey': SPOONACULAR_API_KEY,
        'ingredients': ','.join(translated),
        'number': number,
        'ranking': 1,
        'ignorePantry': True,
        'limitLicense': False
    }

    try:
        response = requests.get(
            f"{SPOONACULAR_BASE_URL}/recipes/findByIngredients",
            params=params,
            timeout=15
        )
        response.raise_for_status()
        recipes = response.json()

        if recipes:
            sorted_recipes = sorted(
                recipes,
                key=lambda x: (x['usedIngredientCount'], -x['missedIngredientCount']),
                reverse=True
            )
            logger.info(f"Найдено и отсортировано {len(sorted_recipes)} рецептов")
            return sorted_recipes[:5]
        return recipes

    except Exception as e:
        logger.error(f"Ошибка Spoonacular API: {e}")
        return None



@bot.callback_query_handler(func=lambda call: call.data == "back_to_main")
def back_to_main_callback(call):
    """Возврат в главное меню"""
    bot.answer_callback_query(call.id, "🏠 Возврат в меню")
    try:
        bot.delete_message(call.message.chat.id, call.message.message_id)
    except Exception as e:
        logger.error(f"Ошибка при удалении сообщения: {e}")

    class TempMessage:
        def __init__(self, chat_id, user_id):
            self.chat = type('obj', (object,), {'id': chat_id})
            self.from_user = type('obj', (object,), {'id': user_id})
            self.text = "/start"
            self.message_id = None

    temp_message = TempMessage(call.message.chat.id, call.from_user.id)
    start_command(temp_message)


@bot.message_handler(func=lambda message: message.text == "🔎 Рецепт по названию")
def find_name_button_handler(message):
    """Кнопка поиска рецепта"""
    global selected_command
    selected_command = "search_name"
    bot.reply_to(
        message,
        "📝 *Введите название :*\n"
        "Например: `борщ`",
        parse_mode='Markdown'
    )


@bot.message_handler(func=lambda message: message.text == "🔍 Рецепт по ингредиентам")
def find_button_handler(message):
    """Кнопка поиска рецепта"""
    global selected_command
    selected_command = "search_ingredients"
    bot.reply_to(
        message,
        "📝 *Введите продукты через пробел:*\n"
        "Например: `курица картошка лук`",
        parse_mode='Markdown'
    )


@bot.message_handler(func=lambda message: message.text == "🍴 Рецепты с учетом ограничений")
def diet_button_handler(message):
    """Кнопка поиска рецепта с учетом ограничений"""
    global selected_command
    bot.reply_to(
        message,
        "🥗 *Диетический поиск*\n\n"
        "Введите ваши ограничения в одном сообщении.\n\n"
        "*Форматы:*\n"
        "• С продуктами: `веган без хлеба`\n"
        "• Только диета: `палео`\n"
        "• С похудением: `худею без глютена`\n\n",
        parse_mode='Markdown'
    )
    selected_command = "diet_search"


@bot.message_handler(commands=['exit'])
def exit_command(message):
    """Обработчик команды /exit - выход из бота"""
    bot.send_message(
        message.chat.id,
        "До свидания! Был рад помочь. Возвращайтесь за новыми рецептами!"
    )


@bot.message_handler(func=lambda message: message.text == "🚪 Выход")
def exit_button_handler(message):
    """Обработчик кнопки выхода"""
    bot.send_message(
        message.chat.id,
        "До свидания! Был рад помочь. Возвращайтесь за новыми рецептами!"
    )


@bot.message_handler(func=lambda message: message.text == "❓ Помощь")
def help_button_handler(message):
    """Кнопка помощи"""
    help_command(message)


@bot.message_handler(func=lambda message: message.text == "🏠 Главное меню")
def main_menu_button_handler(message):
    """Кнопка главного меню"""
    start_command(message)


@bot.message_handler(func=lambda message: True)
@handle_api_errors
def text_handler(message):
    """Обработка текстовых сообщений - поиск рецептов с сортировкой"""
    global selected_command
    if message.text.startswith('/'):
        return
    recipes = []
    status_msg = bot.reply_to(
        message,
        f"🔍 *Ищу и сортирую рецепты...*\n\n",
        parse_mode='Markdown'
    )

    logger.info(f"selected command - {selected_command}")
    if selected_command == "search_ingredients":
        ingredients = [ing.strip() for ing in message.text.split()]

        if len(ingredients) > 10:
            bot.reply_to(
                message,
                "⚠️ *Слишком много продуктов*\n"
                "Укажите не более 10 основных ингредиентов.",
                parse_mode='Markdown'
            )
            return

        try:
            bot.edit_message_text(
                "🔍 *Ищу подходящие рецепты...*",
                message.chat.id,
                status_msg.message_id,
                parse_mode='Markdown'
            )
        except Exception as e:
            logger.error(f"Ошибка при редактировании сообщения: {e}")

        recipes = search_recipes_by_ingredients(ingredients, number=10)
        logger.info(recipes)

    elif selected_command == "diet_search":
        diet_analysis = diet_detector.analyze(message.text)

        if diet_analysis['all_restrictions']:
            restrictions = "\n".join(f"• {r}" for r in diet_analysis['all_restrictions'])
            bot.send_message(
                message.chat.id,
                f"✅ *Понял ваши ограничения:*\n{restrictions}",
                parse_mode='Markdown'
            )

        try:
            bot.edit_message_text(
                "🔍 *Ищу подходящие рецепты...*",
                message.chat.id,
                status_msg.message_id,
                parse_mode='Markdown'
            )
        except Exception as e:
            logger.error(f"Ошибка при редактировании сообщения: {e}")

        recipes = search_with_diet(diet_analysis)
        logger.info(recipes)

    elif selected_command == "search_name":
        search_query = message.text

        try:
            bot.edit_message_text(
                "🔍 *Ищу подходящие рецепты...*",
                message.chat.id,
                status_msg.message_id,
                parse_mode='Markdown'
            )
        except Exception as e:
            logger.error(f"Ошибка при редактировании сообщения: {e}")

        recipes = search_recipe_by_name(search_query)

    if len(recipes) == 0 or not recipes:
        logger.info(f"Найдено рецептов: {len(recipes)}")
        try:
            bot.delete_message(message.chat.id, status_msg.message_id)
        except Exception as e:
            logger.error(f"Ошибка при удалении сообщения: {e}")

        bot.send_message(
            message.chat.id,
            "😔 *Рецепты не найдены*\n\n"
            "Попробуйте ввести по другому или нажмите /help",
            parse_mode='Markdown',
            reply_markup=create_main_keyboard()
        )
        return

    logger.info("continue")
    try:
        bot.delete_message(message.chat.id, status_msg.message_id)
    except Exception as e:
        logger.error(f"Ошибка при удалении сообщения: {e}")

    markup = telebot.types.InlineKeyboardMarkup(row_width=1)

    for recipe in recipes[:5]:
        translated_title = translate_recipe_title(recipe['title'])
        callback_data = f"recipe_{recipe['id']}"
        logger.info(callback_data)
        button_text = f"🍽️ {translated_title[:35]}"

        button = telebot.types.InlineKeyboardButton(
            text=button_text,
            callback_data=callback_data
        )
        markup.add(button)

    markup.add(telebot.types.InlineKeyboardButton(
        "🏠 В главное меню",
        callback_data="back_to_main"
    ))

    info_text = (
        f"👇 *Выберите рецепт:*"
    )

    bot.send_message(
        message.chat.id,
        info_text,
        parse_mode='Markdown',
        reply_markup=markup
    )


def search_with_diet(diet_analysis: Dict) -> Optional[Dict]:
    """
    Поиск рецептов с учетом анализа диет
    """
    params = {
        'apiKey': SPOONACULAR_API_KEY,
        'number': 8,
        'addRecipeInformation': True,
        'fillIngredients': True,
        'instructionsRequired': True,
        'ignorePantry': True
    }

    spoonacular_params = diet_analysis['spoonacular_params']
    params.update(spoonacular_params)

    params['sort'] = 'popularity'

    logger.info(f"Параметры запроса: {params}")
    try:
        response = requests.get(
            f"{SPOONACULAR_BASE_URL}/recipes/complexSearch",
            params=params,
            timeout=15
        )
        response.raise_for_status()

        recipes = response.json().get('results', [])

        if recipes:
            logger.info(f"Найдено рецептов: {len(recipes)}")
            return recipes[:5]
        else:
            logger.info("Рецепты не найдены")
            return []
    except Exception as e:
        logger.error(f"Ошибка поиска: {e}")
        return None


def search_recipe_by_name(recipe_name: str, number: int = 8) -> Optional[List[Dict]]:
    """
    Поиск рецептов по названию через Spoonacular API
    """
    recipe_name1 = diet_detector.translate_to_english_title(recipe_name)
    logger.info(f"transleted name: {recipe_name} -> {recipe_name1}")
    params = {
        'apiKey': SPOONACULAR_API_KEY,
        'query': recipe_name1,
        'number': number,
        'addRecipeInformation': True,
        'fillIngredients': True,
        'instructionsRequired': True,
        'sort': 'popularity'
    }

    try:
        logger.info(f"Поиск рецепта по названию: {recipe_name}")
        response = requests.get(
            f"{SPOONACULAR_BASE_URL}/recipes/complexSearch",
            params=params,
            timeout=15
        )
        response.raise_for_status()

        recipes = response.json().get('results', [])

        if recipes:
            logger.info(f"Найдено рецептов: {len(recipes)}")
            return recipes
        else:
            logger.info("Рецепты не найдены")
            return []

    except requests.exceptions.Timeout:
        logger.error("Таймаут при поиске рецепта")
        return None
    except requests.exceptions.RequestException as e:
        logger.error(f"Ошибка запроса: {e}")
        return None
    except Exception as e:
        logger.error(f"Неожиданная ошибка: {e}")
        return None


@bot.message_handler(commands=['search'])
def search_recipe_command(message):
    """Обработчик команды /search для поиска рецептов по названию"""
    command_parts = message.text.split(maxsplit=1)

    if len(command_parts) < 2:
        bot.reply_to(
            message,
            "🔍 *Поиск рецептов по названию*\n\n"
            "Использование: `/search название рецепта`\n"
            "Пример: `/search борщ`\n"
            "Пример: `/search паста карбонара`",
            parse_mode='Markdown'
        )
        return

    search_query = command_parts[1]

    status_msg = bot.reply_to(
        message,
        f"🔍 *Ищу рецепты по запросу:* '{search_query}'",
        parse_mode='Markdown'
    )

    recipes = search_recipe_by_name(search_query)

    if not recipes or len(recipes) == 0:
        logger.info("recipes not found")
        try:
            bot.edit_message_text(
                f"😔 По запросу '{search_query}' ничего не найдено.\n\n"
                "Попробуйте:\n"
                "• Другое название\n"
                "• Более короткий запрос\n"
                "• Проверить орфографию",
                message.chat.id,
                status_msg.message_id,
                parse_mode='Markdown'
            )
        except Exception as e:
            logger.error(f"Ошибка при редактировании сообщения: {e}")
        return

    try:
        bot.delete_message(message.chat.id, status_msg.message_id)
    except Exception as e:
        logger.error(f"Ошибка при удалении сообщения: {e}")

    markup = telebot.types.InlineKeyboardMarkup(row_width=1)

    for recipe in recipes[:5]:
        translated_title = translate_recipe_title(recipe['title'])
        callback_data = f"recipe_{recipe['id']}"
        button_text = f"🎲 {translated_title[:35]}..."

        button = telebot.types.InlineKeyboardButton(
            text=button_text,
            callback_data=callback_data
        )
        markup.add(button)

    markup.add(telebot.types.InlineKeyboardButton(
        "🏠 В главное меню",
        callback_data="back_to_main"
    ))

    info_text = (
        f"👇 *Выберите рецепт:*"
    )

    bot.send_message(
        message.chat.id,
        info_text,
        parse_mode='Markdown',
        reply_markup=markup
    )


def main():
    """Запуск бота"""
    logger.info("Бот запущен и готов к работе!")
    bot.remove_webhook()

    while True:
        try:
            bot.infinity_polling(timeout=60, long_polling_timeout=60, logger_level=logging.ERROR)
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
