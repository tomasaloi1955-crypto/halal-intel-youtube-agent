# haram.py — харам-ниши, с которыми мы не работаем: ни каналы под автопостинг,
# ни заказы на фрилансе. Общий список для channel_hunter и lead_finder.
#
# Каждое слово — начало слова (\b слева), иначе «таро» ловится в «старое»,
# «бар» — в «барабан», а «вино» — в «невиновен». Совпадение сразу после
# «без», «не», «нет», «no», «free» не считается: «халяль без алкоголя»,
# «видео без музыки», «free of pork» — это как раз наши.
import re

# (код, название, ловить ли в постах, разрешено ли исламским каналам, слова)
# «в постах» — только для явных тем: в постах обычного канала «кредит» или
# «песня» мелькают безобидно. «Исламским можно» — исламская ипотека/финансы без
# рибы и знакомства для никаха.
CATEGORIES = [
    ("shirk", "астрология, гадания, магия", True, False, [
        r"астролог", r"астропсихолог", r"гороскоп", r"натальн", r"зодиак", r"ретроград",
        r"транзит\w* планет", r"синастри", r"джйотиш", r"таро\b", r"таролог", r"оракул",
        r"ленорман", r"расклад", r"гадан", r"гадалк", r"нумеролог", r"матриц\w* судьбы",
        r"дизайн человека", r"human design", r"хиромант", r"рун(ы|ам|ах|олог|ическ)",
        r"эзотери", r"магия", r"магии", r"магическ", r"маг(ом|у)?\b", r"колдов", r"ведьм",
        r"чародей", r"приворот", r"отворот", r"снятие порчи", r"порчу", r"экстрасенс",
        r"ясновид", r"ченнелинг", r"чакр", r"космоэнергет", r"амулет", r"талисман",
        r"обереги?\b", r"регрессолог", r"прошлые жизни",
        r"astrolog", r"horoscope", r"zodiac", r"tarot", r"numerolog", r"esoteric",
        r"psychic", r"fortune.tell", r"witchcraft", r"occult", r"spell caster",
    ]),
    ("gambling", "азартные игры и ставки", True, False, [
        r"казино", r"ставк\w* на спорт", r"ставки\b", r"ставок на", r"букмекер", r"беттинг",
        r"азартн", r"покер", r"слот", r"рулетк", r"лотере", r"тотализатор", r"каппер",
        r"casino", r"gambl", r"betting", r"bookmaker", r"sportsbook", r"poker",
        r"slot machine", r"lotter",
    ]),
    ("alcohol", "алкоголь", True, False, [
        r"алкогол", r"спиртн", r"вин(о|а|у|ом|ный|ная|ное|ные|ных|ной)\b", r"винн\w*",
        r"винотек", r"винодел", r"сомелье", r"пив(о|а|у|ом|ной|ная|ное|ные|ных)\b",
        r"пивовар", r"крафтов\w* пив", r"бар\b", r"бары\b", r"баров\b", r"барн(ая|ое|ой)\b",
        r"коктейл", r"виски", r"водк", r"коньяк", r"ликёр", r"ликер", r"шампанск",
        r"самогон", r"текил", r"глинтвейн",
        r"alcohol", r"liquor", r"whisk", r"vodka", r"brewer", r"distiller", r"wine",
        r"beer", r"cocktail", r"\bpub\b", r"tequila",
    ]),
    ("pork", "свинина", True, False, [
        r"свинин", r"свин(ой|ая|ое|ые|ых|ую)\b", r"бекон", r"ветчин", r"сало\b", r"хамон",
        r"прошутто", r"pork", r"bacon", r"ham\b", r"prosciutto",
    ]),
    ("riba", "банки, кредиты, проценты, спекуляции", False, True, [
        r"банк(?!ет)", r"кредит", r"займ", r"микрозайм", r"ипотек", r"ломбард", r"страхов",
        r"форекс", r"трейд", r"бинарн\w* опцион", r"инвестиц", r"криптовалют", r"биткоин",
        r"bank", r"loan", r"microloan", r"payday", r"mortgage", r"insurance", r"forex",
        r"trading", r"crypto", r"bitcoin", r"pawn", r"binary option",
    ]),
    ("tobacco", "табак, кальяны, вейпы, наркотики", True, False, [
        r"кальян", r"вейп", r"табак", r"табач", r"сигарет", r"сигар(ы|а)?\b", r"снюс",
        r"iqos", r"айкос", r"никотин", r"каннабис", r"марихуан", r"cbd\b",
        r"hookah", r"shisha", r"vape", r"vaping", r"tobacco", r"cigar", r"nicotine",
        r"cannabis", r"marijuana",
    ]),
    ("indecency", "18+, эротика, стриптиз", True, False, [
        r"18\+", r"эротик", r"эротич", r"порно", r"интим", r"секс", r"стриптиз",
        r"онлифанс", r"вебкам", r"эскорт", r"тантр", r"ночн\w* клуб", r"караоке",
        r"porn", r"erotic", r"nsfw", r"onlyfans", r"escort", r"strip club", r"stripper",
        r"webcam model", r"adult content", r"sex", r"nightclub", r"night club",
    ]),
    ("dating", "знакомства и свидания", False, True, [
        r"знакомств", r"свидани", r"тиндер", r"dating", r"hookup", r"tinder",
    ]),
    ("lgbt", "ЛГБТ", True, False, [
        r"лгбт", r"гей", r"квир", r"трансгендер", r"lgbt", r"gay\b", r"queer", r"transgender",
    ]),
    ("music", "музыка", False, False, [
        r"музык", r"вокал", r"диджей", r"dj\b", r"концерт", r"песн", r"гитар", r"фортепиан",
        r"пианин", r"барабан", r"music", r"musician", r"singer", r"vocal", r"concert",
        r"song", r"guitar", r"piano", r"drummer",
    ]),
    ("tattoo", "тату, пирсинг, наращивание волос", False, False, [
        r"тату\b", r"тату-", r"татуир", r"татуаж", r"пирсинг", r"наращивани\w* волос",
        r"tattoo", r"piercing", r"hair extension",
    ]),
    ("mlm", "сетевой маркетинг", False, False, [
        r"сетев\w* маркетинг", r"млм\b", r"mlm\b", r"network marketing",
    ]),
    ("holidays", "чужие праздники", False, False, [
        r"хэллоуин", r"хеллоуин", r"halloween",
    ]),
]

# «без алкоголя и свинины», «no alcohol or pork» — отрицание действует на всё
# перечисление до точки/запятой; «не» — только на соседнее слово.
NEGATION_RE = re.compile(
    r"(\b(без|нет|no|non|free of|free from)\b[^.,;:!?\n]{0,40}|\bне[\s-]+)$", re.I)
_COMPILED = [
    (code, name, in_posts, muslim_ok,
     re.compile(r"\b(?:" + "|".join(words) + r")", re.I))
    for code, name, in_posts, muslim_ok, words in CATEGORIES
]


def haram_reason(text, muslim=False, posts=False):
    """Название харам-ниши, найденной в тексте, или None.
    muslim — канал/заказ исламский: исламские финансы и знакомства для никаха можно.
    posts — текст из постов, а не описание: ищем только явные темы."""
    for code, name, in_posts, muslim_ok, regex in _COMPILED:
        if (posts and not in_posts) or (muslim and muslim_ok):
            continue
        for m in regex.finditer(text or ""):
            if not NEGATION_RE.search(text[max(0, m.start() - 60):m.start()]):
                return name
    return None
