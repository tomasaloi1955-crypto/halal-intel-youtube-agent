# Халяль Интеллидженс — YouTube Agent

Автоматический агент: новости → скрипт → озвучка → видео → YouTube.

## Расписание

| День | Тип | Что публикуется |
|------|-----|-----------------|
| Пн | Дайджест | Shorts + длинное видео |
| Вт | Дайджест | Shorts |
| Ср | Автоматизация | Shorts + урок |
| Чт | Дайджест | Shorts |
| Пт | Дайджест | Shorts |
| Сб | Автоматизация | Shorts + урок |
| Вс | Дайджест | Shorts |

## Темы уроков по автоматизации

- Недели 1-16: 16 готовых тем (халяль бизнесы из СНГ и мира)
- Неделя 17+: агент сам исследует интернет через Gemini, находит новые бизнесы
- Харам-фильтр: банки, ломбарды, алкоголь, свинина, сигареты, казино — исключены автоматически
- Повторы исключены: агент запоминает все использованные бизнесы в used_topics.json

## Установка

```bash
pip install -r requirements.txt
cp .env.example .env
# Заполни .env своими ключами
```

## Ключи API

| Сервис | Где получить | Стоимость |
|--------|-------------|-----------|
| Gemini | aistudio.google.com | Бесплатно |
| Pexels | pexels.com/api | Бесплатно |
| ElevenLabs | elevenlabs.io | $5/мес |
| YouTube | console.cloud.google.com | Бесплатно |

## YouTube OAuth (один раз)

1. console.cloud.google.com → новый проект
2. APIs → Enable → YouTube Data API v3
3. Credentials → OAuth 2.0 Client ID → Desktop App → скачай JSON
4. Переименуй в youtube_credentials.json
5. python main.py --once → браузер → авторизуйся

## Запуск

```bash
python main.py --once          # тест один раз
python main.py --digest        # принудительно дайджест
python main.py --automation    # принудительно урок
python topic_researcher.py --prefetch  # заранее заготовить 10 тем
python main.py                 # полный режим с расписанием
```

## Деплой на Render.com

1. Загрузи на GitHub (без .env и youtube_credentials.json)
2. Render → New Web Service → подключи репо
3. Build: pip install -r requirements.txt
4. Start: python main.py
5. Environment Variables: добавь все из .env
6. Secret Files: добавь youtube_credentials.json
