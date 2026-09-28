from datetime import date
from enum import StrEnum, auto
from itertools import count
from typing import Annotated

from funcy import autocurry, lsplit
from httpxyz import AsyncClient
from pydantic import BaseModel, ConfigDict, Field, field_validator
from tqdm import tqdm
from whatever import that

from utils import has_prefixes, indicate_work, keys_dict, parse_date

from .moex import MoexInfo

CONFIG = {
    "cbr": {
        "url": "https://ratings.cbr.ru/bitrix/services/main/ajax.php",
        "concurrency": 15,
        "method": "POST",
    },
}


class PredictionsUpdateMode(StrEnum):
    SKIP = auto()
    OUTDATED = auto()
    ALL = auto()


class Prediction(StrEnum):
    STABLE = auto()
    UNKNOWN = auto()
    NEGATIVE = auto()
    POSITIVE = auto()
    WITHDRAWN = auto()


class CbrInfo(BaseModel):
    prediction: Prediction
    prediction_date: date

    model_config = ConfigDict(extra="ignore")


class CbrData(BaseModel):
    item_list: Annotated[list[CbrItem], Field(alias="itemList")]
    page_count: Annotated[int, Field(alias="pageCount")]


class CbrItem(BaseModel):
    isin: str
    kra_name: Annotated[str, Field(alias="kraName")]
    object_id: Annotated[str, Field(alias="objectId")]
    object_type: Annotated[str, Field(alias="objectType")]
    object_name: Annotated[str, Field(alias="objectName")]
    prediction: str
    rating_action: Annotated[str, Field(alias="ratingAction")]
    release_date: Annotated[date | None, Field(alias="releaseDate")]

    @field_validator("release_date", mode="before")
    @classmethod
    def parse_release_date(cls, v):
        return parse_date(v, "%d.%m.%Y")


async def get_cbr_info(
    client: AsyncClient,
    db: dict,
    inns_db: dict[str, MoexInfo],
    isins: list[str],
    *,
    update_predictions: PredictionsUpdateMode,
) -> dict[str, CbrInfo]:
    if update_predictions == PredictionsUpdateMode.OUTDATED:
        missing_isins, cached_isins = lsplit(_needs_update(db), isins)
    elif update_predictions == PredictionsUpdateMode.SKIP:
        missing_isins, cached_isins = [], isins
    else:
        missing_isins, cached_isins = isins, []

    infos = {}
    csrf_token = await get_cbr_csrf(client)

    caption = "Loading ratings from CBR"
    for isin in tqdm(missing_isins, caption):
        ticker = inns_db[isin]
        items = await get_predictions(client, csrf_token=csrf_token, inn=ticker.inn)
        company_items = get_company_predictions(items)
        isin_items = [item for item in items if item.isin == isin]

        infos[isin] = _get_last_prediction(company_items or isin_items)

    return infos | keys_dict(db, cached_isins, cast_to=CbrInfo)


async def get_predictions(client, *, csrf_token, inn: str) -> list[CbrItem]:
    items = await _get_cbr_items(client, csrf_token, inn)
    return sorted(items, key=that.release_date, reverse=True)


def get_company_predictions(items: list[CbrItem]) -> list[CbrItem]:
    return [
        item for item in items if not has_prefixes(item.object_type, ("TBND", "TMNB"))
    ]


def _get_last_prediction(predictions: list[CbrItem]) -> CbrInfo:
    withdrawn_kra = []
    withdrawn_date = None

    if not predictions:
        return CbrInfo(prediction=Prediction.STABLE, prediction_date=date.today())

    for data in predictions:
        kra = data.kra_name
        if kra in withdrawn_kra:
            continue

        if data.rating_action.startswith("WD"):
            withdrawn_kra.append(kra)
            withdrawn_date = data.release_date
        else:
            return CbrInfo(
                prediction=_parse_prediction(data.prediction),
                prediction_date=data.release_date,
            )

    return CbrInfo(
        prediction=Prediction.WITHDRAWN,
        prediction_date=withdrawn_date or date.today(),
    )


def _parse_prediction(s: str) -> Prediction:
    if has_prefixes(s, ("STA", "NA")):
        return Prediction.STABLE

    if has_prefixes(s, ("UN", "DEV", "UNW")) or not s:
        return Prediction.UNKNOWN

    if has_prefixes(s, ("NEG", "OP")):
        return Prediction.NEGATIVE

    if has_prefixes(s, ("POS",)):
        return Prediction.POSITIVE

    msg = f"{s=}"
    raise ValueError(msg)


async def _get_cbr_items(client: AsyncClient, csrf_token, inn: str) -> list[CbrData]:
    config = CONFIG["cbr"]

    predictions = []
    for page in count(1):
        data = {"fields[pageNumber]": page, "fields[inn]": inn}

        if page > 1:
            del data["fields[inn]"]
            action = "searchRatingNavigation"
        else:
            action = "searchRating"

        response = await client.request(
            method=config["method"],
            url=config["url"],
            headers={"X-Bitrix-Csrf-Token": csrf_token},
            params={"mode": "ajax", "c": "prr.form", "action": action},
            data=data,
        )

        if not response.json()["data"]:
            break

        cbr_data = CbrData(**response.json()["data"])
        predictions.extend(cbr_data.item_list)

        if cbr_data.page_count == page:
            break

    return predictions


async def get_cbr_csrf(client):
    with indicate_work("Getting CSRF token for CBR"):
        response = await client.post(
            CONFIG["cbr"]["url"],
            params={"mode": "ajax", "c": "prr.form", "action": "searchRating"},
            data={"fields[ratingName]": "RU000A10B2D2"},
        )
        return response.json()["errors"][0]["customData"]["csrf"]


@autocurry
def _needs_update(db: dict, isin: list[str]) -> bool:
    ticker = db.get(isin)
    return ticker is None or not ticker.prediction or ticker.has_outdated_prediction
