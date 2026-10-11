# meta_ads/targeting.py — таргетинг на страны СНГ.
#
# Страны по умолчанию — те страны СНГ, где Meta показывает рекламу:
#   KZ Казахстан, UZ Узбекистан, KG Киргизия, TJ Таджикистан, AZ Азербайджан,
#   AM Армения, BY Беларусь, MD Молдова.
# Россия (RU) не включена: с марта 2022 Meta не показывает рекламу пользователям в России,
# и группа объявлений с RU не наберёт показов. Туркменистан (TM) не включён: Facebook и
# Instagram там заблокированы, охват близок к нулю.
#
# ID языков и интересов в Meta не постоянные строки, а числовые id из справочника —
# поэтому агент ищет их через /search по названию и кэширует в состоянии. Интерес,
# которого нет (Meta регулярно удаляет «чувствительные» интересы — религия, здоровье),
# пропускается с предупреждением, а не роняет запуск.

CIS_COUNTRIES = ["KZ", "UZ", "KG", "TJ", "AZ", "AM", "BY", "MD"]
UNSERVED = {"RU": "Meta не показывает рекламу в России", "TM": "Facebook/Instagram заблокированы"}


def clean_countries(countries):
    out = []
    for c in countries or CIS_COUNTRIES:
        c = c.upper()
        if c in UNSERVED:
            print(f"[TARGET] {c} пропущена: {UNSERVED[c]}")
        elif c not in out:
            out.append(c)
    return out


def _lookup(api, cache, kind, name):
    key = f"{kind}:{name.lower()}"
    if key in cache:
        return cache[key]
    found = None
    try:
        if kind == "locale":
            rows = api.search("adlocale", name)
            found = next((r["key"] for r in rows if r.get("name", "").lower().startswith(name.lower())), None)
        else:
            rows = api.search("adinterest", name, limit=5)
            exact = [r for r in rows if r.get("name", "").lower() == name.lower()]
            best = (exact or rows or [None])[0]
            found = {"id": best["id"], "name": best["name"]} if best else None
    except Exception as e:
        print(f"[TARGET] поиск {kind} «{name}» не удался: {e}")
        return None  # не кэшируем сбой — попробуем в следующий раз
    cache[key] = found
    if found is None:
        print(f"[TARGET] {kind} «{name}» не найден в справочнике Meta — пропускаю")
    return found


def build_targeting(api, cfg, camp, cache):
    """Спецификация targeting для группы объявлений."""
    targeting = {
        "geo_locations": {"countries": clean_countries(camp.get("countries") or cfg.get("countries"))},
        "age_min": int(camp.get("age_min", 18)),
        "age_max": int(camp.get("age_max", 65)),
        # Advantage+ audience выключен: аудитории узкие (язык, ниша), и мы не хотим, чтобы
        # Meta расширяла их за пределы заданного. Плейсменты — автоматические.
        "targeting_automation": {"advantage_audience": 0},
    }
    if camp.get("genders"):
        targeting["genders"] = camp["genders"]

    locales = [_lookup(api, cache, "locale", n) for n in camp.get("locales") or cfg.get("locales") or []]
    locales = [l for l in locales if l is not None]
    if locales:
        targeting["locales"] = locales

    interests = [_lookup(api, cache, "interest", n) for n in camp.get("interests", [])]
    interests = [i for i in interests if i]
    if interests:
        # Интересы внутри одного flexible_spec объединяются через ИЛИ.
        targeting["flexible_spec"] = [{"interests": interests}]
    return targeting
