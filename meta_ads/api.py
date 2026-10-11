# meta_ads/api.py — тонкий клиент Meta Marketing API (Graph API) на requests.
#
# Почему не facebook-business SDK: нужно с десяток вызовов, а SDK тянет за собой много
# зависимостей и версий. Graph API — это обычный HTTPS с access_token.
#
# Безопасность денег: по умолчанию клиент в режиме dry-run — чтения идут в API, а любая
# запись (создание кампаний, смена бюджета, пауза объявлений) только печатается в лог.
# Реальные изменения включаются переменной META_ADS_LIVE=true.
import json
import os
import time
from datetime import date, timedelta
import requests

API_VERSION = os.getenv("META_API_VERSION", "v24.0")
BASE = f"https://graph.facebook.com/{API_VERSION}"

# Коды ошибок Graph API, при которых стоит подождать и повторить: лимиты запросов
# приложения/аккаунта (4, 17, 32, 613, 80000-80014) и временные сбои (1, 2).
_RETRY_CODES = {1, 2, 4, 17, 32, 341, 613} | set(range(80000, 80015))

# Валюты без копеек: бюджет в API передаётся в «минимальных единицах» валюты аккаунта,
# для USD это центы (×100), а для этих — сами единицы.
_ZERO_DECIMAL = {"JPY", "KRW", "VND", "CLP", "COP", "CRC", "HUF", "ISK", "IDR", "PYG", "TWD"}


class MetaAPIError(Exception):
    def __init__(self, err, status=None):
        self.code = err.get("code")
        self.subcode = err.get("error_subcode")
        self.user_msg = err.get("error_user_msg") or err.get("message") or str(err)
        super().__init__(f"Meta API {status} code={self.code}/{self.subcode}: {self.user_msg}")


class MetaAPI:
    def __init__(self, token=None, account_id=None, live=None):
        self.token = token if token is not None else os.getenv("META_ACCESS_TOKEN", "").strip()
        acc = account_id if account_id is not None else os.getenv("META_AD_ACCOUNT_ID", "").strip()
        self.account = acc if acc.startswith("act_") or not acc else f"act_{acc}"
        if live is None:
            live = os.getenv("META_ADS_LIVE", "false").strip().lower() == "true"
        self.live = live
        self._dry_seq = 0
        self._account_info = None

    @property
    def configured(self):
        return bool(self.token and self.account)

    # ---------- транспорт ----------

    def _request(self, method, path, params=None, data=None, files=None, attempts=5):
        url = path if path.startswith("http") else f"{BASE}/{path.lstrip('/')}"
        enc = lambda d: {k: json.dumps(v) if isinstance(v, (dict, list)) else v for k, v in (d or {}).items()}
        params = enc(params)
        payload = enc(data)
        payload["access_token"] = self.token
        if method == "GET":
            params.update(payload)
            payload = None
        for i in range(attempts):
            try:
                r = requests.request(method, url, params=params, data=payload, files=files, timeout=60)
            except requests.RequestException as e:
                if i == attempts - 1:
                    raise
                print(f"[META] сеть: {e}; повтор через {2 ** i}с")
                time.sleep(2 ** i)
                continue
            try:
                body = r.json()
            except ValueError:
                body = {"error": {"message": r.text[:300]}}
            if r.ok and "error" not in body:
                return body
            err = body.get("error", {})
            if (err.get("code") in _RETRY_CODES or r.status_code >= 500) and i < attempts - 1:
                wait = min(60 * (i + 1), 300) if err.get("code") in (17, 32, 613, 80004) else 2 ** i
                print(f"[META] {err.get('code')}: {err.get('message')}; жду {wait}с")
                time.sleep(wait)
                continue
            raise MetaAPIError(err, r.status_code)

    def get(self, path, **params):
        return self._request("GET", path, params=params)

    def get_all(self, path, **params):
        """GET с проходом по пагинации (paging.next)."""
        out, body = [], self.get(path, **params)
        while True:
            out.extend(body.get("data", []))
            nxt = body.get("paging", {}).get("next")
            if not nxt:
                return out
            body = self._request("GET", nxt)

    def write(self, path, data, files=None, what=""):
        """POST-запись. В dry-run возвращает фиктивный id и ничего не меняет."""
        if not self.live:
            self._dry_seq += 1
            shown = {k: v for k, v in data.items() if k not in ("bytes",)}
            print(f"[META dry-run] POST {path} {what}: {json.dumps(shown, ensure_ascii=False)[:400]}")
            return {"id": f"dry_{self._dry_seq}", "success": True, "dry_run": True}
        return self._request("POST", path, data=data, files=files)

    # ---------- аккаунт ----------

    def account_info(self):
        if self._account_info is None:
            self._account_info = self.get(self.account, fields="name,currency,account_status,timezone_name")
        return self._account_info

    def money_factor(self):
        """Во сколько раз умножить сумму в валюте аккаунта, чтобы получить единицы API."""
        return 1 if self.account_info().get("currency", "USD") in _ZERO_DECIMAL else 100

    def to_minor(self, amount):
        return int(round(amount * self.money_factor()))

    def from_minor(self, minor):
        return int(minor) / self.money_factor()

    # ---------- создание ----------

    def create_campaign(self, name, objective, daily_budget):
        return self.write(f"{self.account}/campaigns", {
            "name": name,
            "objective": objective,
            "status": "PAUSED",
            "buying_type": "AUCTION",
            "special_ad_categories": [],
            # Бюджет на уровне кампании (Advantage campaign budget): Meta сама делит его
            # между группами, а агент двигает только общий бюджет кампании.
            "daily_budget": self.to_minor(daily_budget),
            "bid_strategy": "LOWEST_COST_WITHOUT_CAP",
        }, what=name)

    def create_adset(self, campaign_id, name, targeting, optimization_goal, promoted_object=None):
        data = {
            "name": name,
            "campaign_id": campaign_id,
            "status": "PAUSED",
            "billing_event": "IMPRESSIONS",
            "optimization_goal": optimization_goal,
            "targeting": targeting,
        }
        if promoted_object:
            data["promoted_object"] = promoted_object
        return self.write(f"{self.account}/adsets", data, what=name)

    def upload_image(self, path):
        """Загружает картинку в библиотеку аккаунта, возвращает image_hash."""
        if not self.live:
            print(f"[META dry-run] upload image {path}")
            return "dry_image_hash"
        with open(path, "rb") as f:
            body = self._request("POST", f"{self.account}/adimages", files={"filename": (os.path.basename(path), f)})
        images = body.get("images", {})
        return next(iter(images.values()))["hash"]

    def create_creative(self, name, page_id, link, copy, image_hash, cta, instagram_user_id=""):
        link_data = {
            "link": link,
            "message": copy["primary_text"],
            "name": copy["headline"],
            "description": copy.get("description", ""),
            "image_hash": image_hash,
            "call_to_action": {"type": cta, "value": {"link": link}},
        }
        spec = {"page_id": page_id, "link_data": link_data}
        if instagram_user_id:
            spec["instagram_user_id"] = instagram_user_id
        return self.write(f"{self.account}/adcreatives", {
            "name": name,
            "object_story_spec": spec,
            # UTM-метки: в аналитике сайта видно, какая кампания и какое объявление привели человека.
            "url_tags": "utm_source=meta&utm_medium=paid&utm_campaign={{campaign.name}}&utm_content={{ad.name}}",
        }, what=name)

    def create_ad(self, adset_id, name, creative_id, status="PAUSED"):
        return self.write(f"{self.account}/ads", {
            "name": name, "adset_id": adset_id, "creative": {"creative_id": creative_id}, "status": status,
        }, what=name)

    # ---------- управление ----------

    def set_status(self, object_id, status):
        return self.write(object_id, {"status": status}, what=status)

    def set_daily_budget(self, campaign_id, amount):
        return self.write(campaign_id, {"daily_budget": self.to_minor(amount)}, what=f"budget={amount:.2f}")

    # ---------- чтение ----------

    def campaign(self, campaign_id):
        return self.get(campaign_id, fields="name,status,effective_status,daily_budget,created_time")

    def adsets(self, campaign_id):
        return self.get_all(f"{campaign_id}/adsets", fields="id,name,effective_status,learning_stage_info")

    def ads(self, adset_id):
        return self.get_all(f"{adset_id}/ads", fields="id,name,effective_status,creative{id}")

    def daily_insights(self, campaign_id, days):
        """Статистика кампании по дням за последние `days` дней (без сегодняшнего)."""
        return self.get_all(
            f"{campaign_id}/insights",
            fields="spend,impressions,inline_link_clicks,frequency,actions",
            time_range=_time_range(days),
            time_increment=1,
        )

    def ad_insights(self, adset_id, days):
        return self.get_all(
            f"{adset_id}/insights",
            level="ad",
            fields="ad_id,ad_name,spend,impressions,inline_link_clicks,frequency,actions",
            time_range=_time_range(days),
        )

    def search(self, type_, q, **params):
        return self.get("search", type=type_, q=q, **params).get("data", [])


def _time_range(days):
    """Последние `days` полных дней: вчера и раньше (сегодняшние цифры ещё неполные)."""
    until = date.today() - timedelta(days=1)
    since = until - timedelta(days=days - 1)
    return {"since": since.isoformat(), "until": until.isoformat()}


def count_action(row, action_type):
    """Количество действий нужного типа из поля actions строки insights."""
    for a in row.get("actions", []) or []:
        if a.get("action_type") == action_type:
            return float(a.get("value", 0))
    return 0.0
