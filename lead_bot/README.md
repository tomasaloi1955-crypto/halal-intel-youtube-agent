# Бот для заявок: Telegram + WhatsApp

Клиент пишет бизнесу в Telegram или WhatsApp → бот по очереди задаёт вопросы
(имя, услуга, телефон, удобное время) → готовая заявка сразу приходит владельцу в Telegram.
В WhatsApp номер клиента уже известен, поэтому телефон там не спрашивается.

Под нового клиента меняется только `config.json`: название, приветствие, вопросы и
варианты ответа. Код трогать не нужно.

## Что нужно от клиента (бизнеса)

| Что | Где взять |
|---|---|
| Telegram-бот | @BotFather → `/newbot` → токен |
| Куда слать заявки | свой chat_id: написать боту @userinfobot; для группы — добавить бота в группу |
| WhatsApp | номер, который **не** используется в обычном приложении WhatsApp / WhatsApp Business (Cloud API забирает номер себе) |

## Подключение WhatsApp (WhatsApp Cloud API от Meta)

1. developers.facebook.com → **Create App** → тип **Business** → добавить продукт **WhatsApp**.
2. В разделе WhatsApp → **API Setup** добавить номер бизнеса и подтвердить его по SMS.
   Отсюда берутся `WHATSAPP_PHONE_NUMBER_ID` и временный токен.
3. Постоянный токен: business.facebook.com → Настройки → **Системные пользователи** →
   создать пользователя, выдать ему приложение и права `whatsapp_business_messaging`,
   `whatsapp_business_management` → **Сгенерировать токен** → это `WHATSAPP_TOKEN`.
4. **App Secret** (Настройки приложения → Основное) → `WHATSAPP_APP_SECRET`.
5. WhatsApp → **Configuration** → Webhook:
   - Callback URL: `https://ВАШ-СЕРВИС.onrender.com/whatsapp`
   - Verify token: любая строка, та же, что в `WHATSAPP_VERIFY_TOKEN`
   - Подписаться на поле **messages**.
6. Чтобы писать реальным клиентам, а не только тестовым номерам, бизнес-аккаунт
   нужно подтвердить (Business Verification) и перевести приложение в режим **Live**.

Про оплату: бот только отвечает клиенту, который написал первым. Такие переписки
(в течение 24 часов после сообщения клиента) у Meta сейчас бесплатные. Платными
были бы рассылки по шаблонам, а их бот не делает. Тарифы Meta меняются —
перед запуском проверьте на developers.facebook.com/docs/whatsapp/pricing.

## Деплой на Render

1. Render → **New Web Service** → этот репозиторий, **Root Directory**: `lead_bot`
2. Build: `pip install -r requirements.txt`
3. Start: `gunicorn -w 1 -b 0.0.0.0:$PORT app:app`
4. Environment Variables:

| Переменная | Что это |
|---|---|
| `TELEGRAM_BOT_TOKEN` | токен бота от @BotFather |
| `TELEGRAM_WEBHOOK_SECRET` | любая длинная строка (защита от чужих запросов) |
| `OWNER_CHAT_ID` | куда слать заявки |
| `PUBLIC_URL` | адрес сервиса, например `https://leads-salon.onrender.com` |
| `WHATSAPP_TOKEN` | постоянный токен (шаг 3) |
| `WHATSAPP_PHONE_NUMBER_ID` | ID номера (шаг 2) |
| `WHATSAPP_VERIFY_TOKEN` | строка для проверки вебхука (шаг 5) |
| `WHATSAPP_APP_SECRET` | App Secret (шаг 4) |
| `LEADS_WEBHOOK_URL` | необязательно: куда ещё отправить заявку JSON-ом (Google Таблица, CRM) |
| `ADMIN_KEY` | необязательно: пароль для выгрузки `/leads.csv?key=...` |

Telegram-вебхук ставится сам при старте. Если WhatsApp не нужен — просто не задавайте
`WHATSAPP_*`, бот будет работать только в Telegram (и наоборот).

⚠️ На бесплатном Render сервис засыпает после 15 минут простоя, и первый ответ приходит
через ~30–50 секунд. Для клиента, который платит, лучше тариф Starter ($7/мес) — включите его
в цену абонемента. Диск на Render тоже временный: все заявки сразу уходят владельцу в
Telegram, а для надёжного архива подключите `LEADS_WEBHOOK_URL` к Google Таблице.

## Заявки в Google Таблицу

Таблица → Расширения → **Apps Script** → вставить и **Deploy → Web app** (доступ: Anyone):

```javascript
function doPost(e) {
  const d = JSON.parse(e.postData.contents);
  SpreadsheetApp.getActiveSheet().appendRow(
    [d.created, d.channel, d.name, d.service, d.phone, d.time]);
  return ContentService.createTextOutput("ok");
}
```

Полученный URL веб-приложения → в `LEADS_WEBHOOK_URL`.

## Локальный запуск

```bash
pip install -r requirements.txt
TELEGRAM_BOT_TOKEN=... OWNER_CHAT_ID=... python app.py
```
Для проверки вебхуков снаружи нужен публичный адрес (например, `ngrok http 10000`) в `PUBLIC_URL`.
