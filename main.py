import os
import telebot
import requests
from dotenv import load_dotenv
import logging
from typing import List, Dict, Optional
import time
from functools import wraps
import re
from transformer import UniversalDietDetector


logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

load_dotenv()

TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
SPOONACULAR_API_KEY = os.getenv('SPOONACULAR_API_KEY')
DEEPSEEK_API_KEY = os.getenv('DEEPSEEK_API_KEY')
HUGGINGFACE_API_KEY = os.getenv('HUGGINGFACE_API_KEY')


if not TELEGRAM_TOKEN or not SPOONACULAR_API_KEY or not DEEPSEEK_API_KEY or not HUGGINGFACE_API_KEY:
    raise ValueError("Не найдены токены в .env файле")

bot = telebot.TeleBot(TELEGRAM_TOKEN)

SPOONACULAR_BASE_URL = "https://api.spoonacular.com"
DEEPSEEK_URL = "https://openrouter.ai/api/v1/chat/completions"
DEEPSEEK_MODEL = "deepseek/deepseek-r1"
diet_detector = UniversalDietDetector(HUGGINGFACE_API_KEY)


selected_command = ""


def clean_deepseek_response(text: str) -> str:
    """Очистка ответа DeepSeek от тегов и лишнего текста"""
    text = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL)
    text = re.sub(r'<[^>]+>', '', text)
    text = re.sub(r'\s+', ' ', text)
    return text.strip()


def translate_with_deepseek(text: str, instruction: str) -> str:
    """Универсальная функция для перевода/обработки текста через DeepSeek"""
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


def translate_ingredients_to_english(ingredients: List[str]) -> List[str]:
    """Перевод списка продуктов на английский для поиска"""
    ingredients_text = ", ".join(ingredients)

    instruction = (
        "Переведи следующие продукты на английский язык для поиска рецептов. "
        "Верни ТОЛЬКО переведенные слова через запятую, без пояснений, без цифр, без точек. "
        "Пример формата: chicken, potato, onion"
        "Ингредиенты состоящие из двух и более слов должны считаться как один ингредиент"
    )

    result = translate_with_deepseek(ingredients_text, instruction)

    translated = [item.strip().lower() for item in result.split(',') if item.strip()]

    if not translated:
        return [ing.lower() for ing in ingredients]

    logger.info(f"DeepSeek перевел: {ingredients} -> {translated}")
    return translated


def translate_recipe_title(title: str) -> str:
    """Перевод названия рецепта на русский"""
    instruction = (
        "Переведи название рецепта на русский язык. "
        "Верни ТОЛЬКО переведенное название, без пояснений."
    )
    return translate_with_deepseek(title, instruction)


def format_full_recipe(recipe: Dict) -> str:
    """Форматирование полного рецепта с переводом на русский"""

    translated_title = translate_recipe_title(recipe['title'])

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
            ingredients_list.append(f"• {ing['original']}")

        ingredients_text = "\n".join(ingredients_list)

        translated_ingredients = translate_with_deepseek(
            ingredients_text,
            "Переведи список ингредиентов на русский язык. Сохрани формат с точками в начале строки. "
            "Переведи меры (teaspoon -> чайная ложка, cup -> стакан, tablespoon -> столовая ложка, cloves -> зубчики). "
            "Названия продуктов переведи на русский. Сохрани все числа и меры."
        )

        recipe_parts.append(translated_ingredients)
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

        recipe_parts.append(translated_instructions)
        recipe_parts.append("")

    if recipe.get('sourceUrl'):
        recipe_parts.append(f"[Полный рецепт (оригинал)]({recipe['sourceUrl']})")

    full_recipe = "\n".join(recipe_parts)

    return f"*{translated_title}*\n\n{full_recipe}"


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
    logger.info(params)
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
        response.raise_for_status()
        return response.json()
    except Exception as e:
        logger.error(f"Ошибка получения деталей: {e}")
        return None


def create_main_keyboard():
    """Создание главной клавиатуры"""
    markup = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(
        telebot.types.KeyboardButton("🔎 Найти рецепт по названию"),
        telebot.types.KeyboardButton("🔍 Найти рецепт по ингредиентам"),
        telebot.types.KeyboardButton("🍴 Найти рецепты с учетом ограничений"),
        telebot.types.KeyboardButton("❓ Помощь"),
        telebot.types.KeyboardButton("🏠 Главное меню")
    )
    return markup


def handle_api_errors(func):
    @wraps(func)
    def wrapper(message, *args, **kwargs):
        try:
            return func(message, *args, **kwargs)
        except requests.exceptions.Timeout:
            bot.reply_to(message, "Превышено время ожидания. Попробуйте позже.")
        except requests.exceptions.ConnectionError:
            bot.reply_to(message, "Ошибка соединения. Проверьте интернет.")
        except Exception as e:
            logger.error(f"Ошибка: {e}")
            bot.reply_to(message, "Произошла ошибка. Попробуйте еще раз.")

    return wrapper


@bot.message_handler(commands=['start'])
def start_command(message):
    """Обработчик команды /start"""
    welcome_text = (
        "👨‍🍳 *Добро пожаловать в Кулинарного бота!*\n\n"
        "🍽️ *Что я умею:*\n"
        "• Понимать продукты на любом языке\n"
        "• Искать рецепты по всему миру\n"
        "• Переводить рецепты на русский\n"
        "• Показывать подробные инструкции\n"
        "• **Сортирую рецепты по количеству совпадений**\n\n"
        "📋 *Команды:*\n"
        "/start - это меню\n"
        "/search название - поиск рецепта по названию\n"
        "/find продукты - поиск рецептов\n"
        "/diet_find ограничения - поиск рецептов по диете\n"
        "/help - подробная справка\n\n"
        "*Пример:* `/find курица картошка лук`\n\n"
        "Приятного аппетита)"
    )
    global selected_command
    selected_command="start"
    bot.send_message(
        message.chat.id,
        welcome_text,
        parse_mode='Markdown',
        reply_markup=create_main_keyboard()
    )


@bot.message_handler(commands=['help'])
def help_command(message):
    """Подробная справка"""
    global selected_command
    selected_command = "help"

    help_text = (
        "📚 *Подробная справка*\n\n"
        "*Как это работает:*\n"
        "1️⃣ Вы пишете продукты (на любом языке)\n"
        "2️⃣ DeepSeek AI переводит их для поиска\n"
        "3️⃣ Spoonacular находит рецепты\n"
        "4️⃣ **Рецепты сортируются по количеству совпадений**\n"
        "5️⃣ DeepSeek AI переводит рецепт на русский\n"
        "6️⃣ Вы получаете готовый рецепт!\n\n"
        "*Команды:*\n"
        "• `/start` - Главное меню\n"
        "• `/find [продукты]` - Поиск рецептов\n"
        "  Пример: `/find курица рис лук`\n"
        "• `/diet_find [ограничения]` - Поиск рецептов с учетом диет\n"
        "  Пример: `/diet_find вегетерианство без сахара`\n"
        "• `/help` - Эта справка\n\n"
        "*Кнопки:*\n"
        "• 🔎 Найти рецепт по названию - быстрый поиск по названию\n"
        "• 🔍 Найти рецепт по ингредиентам - быстрый поиск по введенным ингредиентам\n"
        "• 🍴 Найти рецепты с учетом ограничений - диетический поиск\n"
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
        reply_markup=create_main_keyboard()
    )


@bot.message_handler(commands=['find'])
@handle_api_errors
def find_command(message):
    """Обработчик команды /find - поиск рецептов с сортировкой"""

    global selected_command
    selected_command = "search_ingredients"
    command_parts = message.text.split(maxsplit=1)

    if len(command_parts) < 2:
        bot.reply_to(
            message,
            "*Напишите продукты после /find*\n\n"
            "Пример: `/find курица картошка лук`",
            parse_mode='Markdown',
            reply_markup=create_main_keyboard()
        )
        return

    ingredients = [ing.strip() for ing in command_parts[1].split()]

    bot.send_chat_action(message.chat.id, 'typing')
    status_msg = bot.reply_to(
        message,
        f"🔍 *Ищу и сортирую рецепты...*\n\n"
        f"Продукты: {', '.join(ingredients)}",
        parse_mode='Markdown'
    )

    recipes = search_recipes_by_ingredients(ingredients, number=10)

    if not recipes:
        bot.edit_message_text(
            "😔 *Рецепты не найдены*\n\n"
            "Попробуйте:\n"
            "• Другие продукты\n"
            "• Меньше ингредиентов\n"
            "• Основные продукты (мясо, овощи)",
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

        match_text = f"✅ {recipe['usedIngredientCount']} совп."

        button_text = f"🍽️ {translated_title[:35]}... ({match_text})"

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
        f"✅ *Найдено рецептов:* {len(recipes)}\n"
        f"👇 *Выберите рецепт для просмотра:*"
    )

    bot.send_message(
        message.chat.id,
        info_text,
        parse_mode='Markdown',
        reply_markup=markup
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
    selected_command ="diet_search"
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

        match_text = f"✅ {recipe['usedIngredientCount']} совп."

        button_text = f"🍽️ {translated_title[:35]}... ({match_text})"

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
        f"✅ *Найдено рецептов:* {len(recipes)}\n"
        f"👇 *Выберите рецепт:*"
    )

    bot.send_message(
        message.chat.id,
        info_text,
        parse_mode='Markdown',
        reply_markup=markup
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

        bot.delete_message(call.message.chat.id, status_msg.message_id)

        if recipe_details.get('image'):
            if len(recipe_text) > 1000:
                bot.send_photo(
                    call.message.chat.id,
                    recipe_details['image']
                )
                bot.send_message(
                    call.message.chat.id,
                    recipe_text,
                    parse_mode='Markdown',
                    reply_markup=create_main_keyboard()
                )
            else:
                bot.send_photo(
                    call.message.chat.id,
                    recipe_details['image'],
                    caption=recipe_text,
                    parse_mode='Markdown',
                    reply_markup=create_main_keyboard()
                )
        else:
            bot.send_message(
                call.message.chat.id,
                recipe_text,
                parse_mode='Markdown',
                reply_markup=create_main_keyboard()
            )
    else:
        bot.edit_message_text(
            "😔 *Не удалось загрузить рецепт*",
            call.message.chat.id,
            status_msg.message_id,
            parse_mode='Markdown',
            reply_markup=create_main_keyboard()
        )


@bot.callback_query_handler(func=lambda call: call.data == "back_to_main")
def back_to_main_callback(call):
    """Возврат в главное меню"""
    bot.answer_callback_query(call.id, "🏠 Возврат в меню")
    bot.delete_message(call.message.chat.id, call.message.message_id)

    start_command(call.message)


@bot.message_handler(func=lambda message: message.text == "🔎 Найти рецепт по названию")
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


@bot.message_handler(func=lambda message: message.text == "🔍 Найти рецепт по ингредиентам")
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

@bot.message_handler(func=lambda message: message.text == "🍴 Найти рецепты с учетом ограничений")
def find_button_handler(message):
    """Кнопка поиска рецепта"""
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

        bot.edit_message_text(
            "🔍 *Ищу подходящие рецепты...*",
            message.chat.id,
            status_msg.message_id,
            parse_mode='Markdown'
        )

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

        bot.edit_message_text(
            "🔍 *Ищу подходящие рецепты...*",
            message.chat.id,
            status_msg.message_id,
            parse_mode='Markdown'
        )

        recipes = search_with_diet( diet_analysis)
        logger.info(recipes)

    elif selected_command == "search_name":
        search_query = message.text

        bot.edit_message_text(
            "🔍 *Ищу подходящие рецепты...*",
            message.chat.id,
            status_msg.message_id,
            parse_mode='Markdown'
        )

        recipes = search_recipe_by_name(search_query)

    if len(recipes)==0  or not recipes:
        logger.info(f"Найдено рецептов: {len(recipes)} отсовтсовтсл")
        bot.delete_message(message.chat.id, status_msg.message_id)

        bot.send_message(
            message.chat.id,
            "😔 *Рецепты не найдены*\n\n"
            "Попробуйте ввести по другому или нажмите /help",
            parse_mode='Markdown',
            reply_markup=create_main_keyboard()
        )
        return

    logger.info("continue")
    bot.delete_message(message.chat.id, status_msg.message_id)

    markup = telebot.types.InlineKeyboardMarkup(row_width=1)

    for recipe in recipes[:5]:
        translated_title = translate_recipe_title(recipe['title'])
        callback_data = f"recipe_{recipe['id']}"
        match_text = ""

        if recipe['usedIngredientCount'] is not None:
            match_text = f"✅ {recipe['usedIngredientCount']} совп."

        button_text = f"🍽️ {translated_title[:35]}... ({match_text})"

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
        f"✅ *Найдено рецептов:* {len(recipes)}\n"
        f"👇 *Выберите рецепт:*"
    )

    bot.send_message(
        message.chat.id,
        info_text,
        parse_mode='Markdown',
        reply_markup=markup
    )


def search_with_diet( diet_analysis: Dict) -> Optional[Dict]:
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
    logger.info(f"Параметры запроса: {type(params)}")
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

    if not recipes or len(recipes)==0:
        logger.info("recipes not found")
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
        return

    bot.delete_message(message.chat.id, status_msg.message_id)

    markup = telebot.types.InlineKeyboardMarkup(row_width=1)

    for recipe in recipes[:5]:
        translated_title = translate_recipe_title(recipe['title'])
        callback_data = f"recipe_{recipe['id']}"
        button_text = f"🍽️ {translated_title[:35]}..."

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
        f"✅ *Найдено рецептов:* {len(recipes)}\n"
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
    logger.info("🚀 Бот запущен и готов к работе!")

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