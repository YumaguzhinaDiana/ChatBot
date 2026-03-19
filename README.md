# ChatBot ChiefAssistant
ChiefAssistant - бот-помощник для выбора рецепта для приготовления.
Список функций: 
* Найти рецепт по названию - вы вводите название, и бот выдает рецепты с таким или похожим названием.
* Найти рецепт по ингредиентам - вы вводите продукты, которые у вас есть, и бот выдает рецепты, содержащие эти продукты.
* Найти рецепт с учетом ограничений - вы вводите вашу диету, например (вегетарианство), или список продуктов которые нужно исключить, и бот выводит соответствующие рецепты.
* Случайный рецепт - бот выводит произвольный рецепт.
* Рецепт под настроение - вы выбираете из списка свое текущее настроение, например (грусть), и бот выводит рецепты которые подошли бы под ваше состояние.
* Помощь - вывод справки по всем функциям.
* Выход - вывод сообщения о выходе

## Команды
### Главное меню

<img width="1747" height="718" alt="image" src="https://github.com/user-attachments/assets/ed39593f-4d89-439e-8cd7-1bbf918397f5" />

### Случайный рецепт

<img width="1463" height="904" alt="image" src="https://github.com/user-attachments/assets/ed82df38-324b-40e0-947c-141e998a6302" />

### Рецепт по настроению

<img width="1460" height="639" alt="image" src="https://github.com/user-attachments/assets/28169d6b-86c3-4f0c-91ff-ef71697e3e0e" />
<img width="963" height="806" alt="image" src="https://github.com/user-attachments/assets/48b4dd80-6800-4013-b78c-c6f5ab03f897" />

### Рецепт по названию

<img width="754" height="574" alt="image" src="https://github.com/user-attachments/assets/3b436be1-7e62-473e-a124-3761f7e4b651" />

### Рецепт по ингредиентам

<img width="570" height="620" alt="image" src="https://github.com/user-attachments/assets/727f377c-5d30-4966-aa1a-41400d9a4187" />

### Рецепт с учетом ограничений

<img width="1014" height="839" alt="image" src="https://github.com/user-attachments/assets/c1bf1243-f04a-419b-9dd0-8f114fc39be1" />

### Помощь

<img width="876" height="847" alt="image" src="https://github.com/user-attachments/assets/fff9cd47-35e4-408e-ac16-05b7da7fa345" />

### Выход

<img width="652" height="143" alt="image" src="https://github.com/user-attachments/assets/8798ef2b-1e36-465f-81d0-47ab5258bdb8" />

## Использованное API

 SpoonAcularApi - предоставляет доступ к базе данных рецептов, информации о питании и пищевых продуктов.


## Использованная ИИ модель

 GigaChat для перевода рецептов на русский и мер весов на метрическую систему, определения блюда под настроение.


## Использованные трансформеры
* facebook/bart-large-mnli - Предсказывание диеты пользователя по введенному тексту
* Helsinki-NLP/opus-mt-ru-en - Перевод названий с русского на английский






