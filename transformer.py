import os
import re
import requests
import time
from typing import Dict, List, Optional, Any
import logging
from dotenv import load_dotenv

logger = logging.getLogger(__name__)


class UniversalDietDetector:
    """
    Универсальный детектор диетических ограничений
    """

    def __init__(self, hf_token: str):
        self.headers = {"Authorization": f"Bearer {hf_token}"}

        self.base_url = "https://router.huggingface.co"

        self.zero_shot_url = f"{self.base_url}/hf-inference/models/facebook/bart-large-mnli"
        self.ner_url = f"{self.base_url}/hf-inference/models/Davlan/bert-base-multilingual-cased-ner-hrl"
        self.translation_url = f"{self.base_url}/hf-inference/models/Helsinki-NLP/opus-mt-ru-en"
        self.cache = {}

        print(f"HuggingFace клиент инициализирован")
        print(f" Zero-shot: {self.zero_shot_url}")
        print(f" NER: {self.ner_url}")
        print(f" Перевод: {self.translation_url}")

    def _query_model(self, url: str, inputs: Any,
                     parameters: Dict = None, max_retries: int = 3) -> Optional[Any]:
        """
        Универсальный метод для запросов к моделям
        """
        payload = {"inputs": inputs}
        if parameters:
            payload["parameters"] = parameters

        for attempt in range(max_retries):
            try:
                print(f"🔄 Запрос к {url.split('/')[-1]} (попытка {attempt + 1})")

                response = requests.post(
                    url,
                    headers=self.headers,
                    json=payload,
                    timeout=30
                )

                if response.status_code == 200:
                    return response.json()

                elif response.status_code == 503:
                    print(f" Модель загружается, жду 2 сек...")
                    time.sleep(2)
                    continue

                elif response.status_code == 404:
                    print(f"Модель не найдена: {url}")
                    return None

                else:
                    print(f" Ошибка {response.status_code}: {response.text[:200]}")
                    return None

            except Exception as e:
                print(f"Ошибка запроса: {e}")
                time.sleep(1)

        return None

    def analyze(self, text: str) -> Dict[str, Any]:
        """
        Полный анализ всех ограничений
        """
        result = {
            'diet_types': [],
            'excluded_foods': [],
            'weight_loss': None,
            'all_restrictions': [],
            'spoonacular_params': {}
        }

        print(f"\n📝 Анализ текста: {text}")


        diet_info = self._detect_diet(text)
        if diet_info:
            result['diet_types'].append(diet_info['diet'])
            result['all_restrictions'].append(f"🥗 диета: {diet_info['original']}")


        weight_loss = self._detect_weight_loss(text)
        if weight_loss:
            result['weight_loss'] = weight_loss
            result['all_restrictions'].append(f"🏋️ {weight_loss['description']}")


        self._detect_exclusions(text, result)


        self._generate_spoonacular_params(result)

        return result

    def _detect_diet(self, text: str) -> Optional[Dict]:
        """Определяет диету через zero-shot"""
        diet_candidates = ["веган", "вегетарианец", "кето", "без глютена", "без лактозы", "палео"]

        result = self._query_model(self.zero_shot_url, text, {"candidate_labels": diet_candidates})
        print(result)
        if result and isinstance(result, list) and len(result) > 0:


            diet_map = {
                'веган': 'vegan',
                'вегетарианец': 'vegetarian',
                'кето': 'ketogenic',
                'без глютена': 'gluten free',
                'без лактозы': 'dairy free',
                'палео': 'paleo',
                'пескетариан': 'pescetatian'
            }

            best_item = max(result, key=lambda x: x['score'])
            best_label = best_item['label']
            best_score = best_item['score']

            if best_score > 0.35:
                print({
                    'diet': diet_map.get(best_label),
                    'original': best_label,
                    'confidence': best_score
                })
                return {
                    'diet': diet_map.get(best_label),
                    'original': best_label,
                    'confidence': best_score
                }
        return None

    def _detect_weight_loss(self, text: str) -> Optional[Dict]:
        """Определяет похудение"""
        text_lower = text.lower()
        weight_keywords = ['худею', 'похудеть', 'сбросить вес', 'диета']

        for keyword in weight_keywords:
            if keyword in text_lower:
                intensity = 'medium'
                if any(word in text_lower for word in ['сильно', 'срочно', 'быстро']):
                    intensity = 'high'
                elif any(word in text_lower for word in ['немного', 'слегка']):
                    intensity = 'low'

                return {'intensity': intensity, 'description': f'похудение'}
        return None

    def _detect_exclusions(self, text: str, result: Dict):
        """Находит исключаемые продукты"""
        text_lower = text.lower()
        patterns = [
            (r'не (?:ем|ест|употребляю) (\w+)', 'не ест'),
            (r'без (\w+)', 'без'),
            (r'исключаю (\w+)', 'исключает'),
            (r'аллергия на (\w+)', 'аллергия')
        ]

        for pattern, reason in patterns:
            matches = re.findall(pattern, text_lower)
            for match in matches:
                if len(match) > 2:
                    result['excluded_foods'].append(match)
                    result['all_restrictions'].append(f"🚫 {reason}: {match}")

    def _translate_to_english(self, text: str) -> str:
        """Переводит текст на английский"""
        try:
            result = self._query_model(self.translation_url, text)
            print("translate_result", result)
            if result and isinstance(result, list) and len(result) > 0:
                if isinstance(result[0], dict):
                    return result[0].get('translation_text', text).lower()
                elif isinstance(result[0], str):
                    return result[0].lower()
        except Exception as e:
            print(f"Ошибка перевода: {e}")

        fallback = {
            'курица': 'chicken', 'мясо': 'meat', 'рыба': 'fish',
            'яйца': 'egg', 'молоко': 'milk', 'сыр': 'cheese',
            'сахар': 'sugar', 'хлеб': 'bread', 'масло': 'oil',
            'рис': 'rice', 'картошка': 'potato', 'лук': 'onion',
            'орехи': 'nuts', 'глютен': 'gluten', 'лактоза': 'dairy'
        }
        return fallback.get(text.lower(), text.lower())

    def _generate_spoonacular_params(self, result: Dict):
        """Генерирует параметры для Spoonacular"""
        params = {}

        if result['diet_types']:
            params['diet'] = result['diet_types'][0]

        if result['excluded_foods']:
            translated = []
            for food in result['excluded_foods'][:5]:
                eng = self._translate_to_english(food)
                if eng and eng not in translated:
                    translated.append(eng)
            if translated:
                params['excludeIngredients'] = ','.join(translated)

        if result['weight_loss']:
            intensity = result['weight_loss']['intensity']
            if intensity == 'high':
                params.update({'maxCalories': 200, 'maxFat': 10})
            elif intensity == 'medium':
                params.update({'maxCalories': 300, 'maxFat': 15})
            else:
                params.update({'maxCalories': 400, 'maxFat': 20})

        result['spoonacular_params'] = params

    def translate_to_english_title(self, text: str) -> str:
        """Переводит текст на английский"""
        try:
            result = self._query_model(self.translation_url, text)
            print("translate_result", result)
            if result and isinstance(result, list) and len(result) > 0:
                if isinstance(result[0], dict):
                    return result[0].get('translation_text', text).lower()
                elif isinstance(result[0], str):
                    return result[0].lower()
        except Exception as e:
            print(f"Ошибка перевода: {e}")


