# meta_ads/copywriter.py — тексты объявлений через Claude.
#
# На вход: бриф кампании, правила площадки и (если есть) статистика прошлых текстов.
# На выход: варианты {primary_text, headline, description} строго по JSON-схеме.
# Без ANTHROPIC_API_KEY или при сбое — берутся готовые seed_copy из campaigns.json,
# чтобы кампания всё равно запустилась.
import json
import os

MODEL = os.getenv("META_ADS_MODEL", "claude-opus-5-5")

# Рекомендуемые Meta длины: длиннее — текст обрезается «…ещё» и теряет конверсию.
LIMITS = {"primary_text": 125, "headline": 40, "description": 30}

SYSTEM = """Ты — performance-копирайтер рекламы в Facebook и Instagram для аудитории стран СНГ \
(Казахстан, Узбекистан, Кыргызстан, Таджикистан, Азербайджан, Армения, Беларусь, Молдова). \
Пишешь на русском: просто, тепло, конкретно, без канцелярита и без капслока.

Правила рекламы Meta, нарушение которых блокирует объявление:
- Нельзя утверждать или намекать на личные характеристики читателя: религию, национальность, \
здоровье, вес, финансовое положение («Вы мусульманин?», «Устали от лишнего веса?» — запрещено).
- Никаких гарантий результата, дохода или сроков похудения; никаких «до/после».
- Без кликбейта, фальшивой срочности и восклицательных знаков подряд.

Каждый вариант — отдельная гипотеза: разные углы (выгода, боль-задача, формат, социальное \
доказательство, простота старта), а не перефразирование одного текста.
Лимиты: primary_text до 125 знаков, headline до 40, description до 30."""

SCHEMA = {
    "type": "object",
    "properties": {
        "variants": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "angle": {"type": "string"},
                    "primary_text": {"type": "string"},
                    "headline": {"type": "string"},
                    "description": {"type": "string"},
                },
                "required": ["angle", "primary_text", "headline", "description"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["variants"],
    "additionalProperties": False,
}


def _fit(text, limit):
    text = " ".join(str(text).split())
    if len(text) <= limit:
        return text
    cut = text[:limit - 1].rsplit(" ", 1)[0].rstrip(",.;:—-")
    return cut + "…"


def _clean(v):
    return {k: _fit(v.get(k, ""), lim) for k, lim in LIMITS.items()} | {"angle": v.get("angle", "")}


def _seed(camp, n, skip=()):
    pool = [s for s in camp.get("seed_copy", []) if s["primary_text"] not in skip] or camp.get("seed_copy", [])
    return [_clean(s | {"angle": "seed"}) for s in pool[:n]]


def generate(camp, n=3, performance=None, avoid=()):
    """n вариантов текста для кампании. performance — строки вида
    {"primary_text", "ctr", "cpa"} по прошлым объявлениям, avoid — уже использованные тексты."""
    if not os.getenv("ANTHROPIC_API_KEY"):
        print("[COPY] ANTHROPIC_API_KEY не задан — беру готовые тексты из campaigns.json")
        return _seed(camp, n, avoid)

    import anthropic

    parts = [
        f"Кампания: {camp['name']}",
        f"Бриф: {camp['brief']}",
        f"Особые ограничения: {camp.get('policy_notes', '—')}",
        f"Кнопка призыва: {camp.get('cta', 'LEARN_MORE')}",
    ]
    if performance:
        parts.append("Как работали прошлые тексты (CTR — доля кликов, CPA — цена результата):\n"
                     + json.dumps(performance, ensure_ascii=False, indent=1))
        parts.append("Развивай углы лучших текстов, не повторяй худшие.")
    if avoid:
        parts.append("Эти тексты уже крутятся — не повторяй их:\n" + "\n".join(f"- {a}" for a in avoid))
    parts.append(f"Напиши {n} вариантов.")

    try:
        client = anthropic.Anthropic()
        resp = client.beta.messages.create(
            model=MODEL,
            max_tokens=8000,
            system=SYSTEM,
            messages=[{"role": "user", "content": "\n\n".join(parts)}],
            output_config={"effort": "medium", "format": {"type": "json_schema", "schema": SCHEMA}},
            # При отказе классификатора запрос сам повторяется на подходящей модели.
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )
        if resp.stop_reason in ("refusal", "max_tokens"):
            raise RuntimeError(f"stop_reason={resp.stop_reason}")
        text = next(b.text for b in resp.content if b.type == "text")
        variants = [_clean(v) for v in json.loads(text)["variants"]]
        variants = [v for v in variants if v["primary_text"] not in avoid][:n]
        if variants:
            return variants
        raise RuntimeError("пустой ответ")
    except Exception as e:
        print(f"[COPY] Claude не сработал ({e}) — беру готовые тексты")
        return _seed(camp, n, avoid)
