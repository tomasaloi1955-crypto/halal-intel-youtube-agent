# meta_ads_agent.py — точка входа агента рекламы в Meta (Facebook/Instagram).
#
#   python meta_ads_agent.py setup [ключ ...]     создать кампании (на паузе)
#   python meta_ads_agent.py activate [ключ ...]  включить кампании
#   python meta_ads_agent.py optimize             ежедневная оптимизация бюджета и объявлений
#   python meta_ads_agent.py report               отчёт без изменений
#
# Ключи кампаний: fitness20, tajweed, tamra, automation (см. meta_ads/campaigns.json).
# Без META_ADS_LIVE=true все записи в Meta только печатаются (dry-run).
import sys
from dotenv import load_dotenv

load_dotenv()

from meta_ads import agent  # noqa: E402  — после load_dotenv, чтобы модули видели .env

COMMANDS = {"setup": agent.setup, "activate": agent.activate, "optimize": agent.optimize, "report": agent.report}

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in COMMANDS:
        print("Использование: python meta_ads_agent.py {" + "|".join(COMMANDS) + "} [ключ ...]")
        sys.exit(1)
    cmd, keys = sys.argv[1], sys.argv[2:]
    if cmd in ("setup", "activate"):
        COMMANDS[cmd](keys or None)
    else:
        COMMANDS[cmd]()
