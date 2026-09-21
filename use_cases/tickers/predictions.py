import csv
from asyncio import Semaphore
from datetime import date
from io import StringIO
from itertools import count
from typing import Annotated

from asyncstdlib import zip as azip
from httpxyz import AsyncClient
from pydantic import BaseModel, Field, field_validator
from tqdm import tqdm
from whatever import that

from use_cases.utils import Request, get_batch, has_prefixes, indicate_work

from .base import Db, Prediction, PredictionsUpdateMode

CONFIG = {
    "cbr": {
        "url": "https://ratings.cbr.ru/bitrix/services/main/ajax.php",
        "concurrency": 15,
        "method": "POST",
    },
    "moex": {
        "url": (
            "https://web.moex.com/moex-web-icdb-api/api/v2/export/ru_securities-list"
        ),
        "concurrency": 15,
    },
}


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
        if v is None:
            return v

        return date.strptime(v, "%d.%m.%Y")


async def set_predictions(
    client: AsyncClient,
    db: Db,
    *,
    isins: list[str],
    update_predictions: PredictionsUpdateMode,
) -> dict:
    config = CONFIG["cbr"]

    if update_predictions == PredictionsUpdateMode.OUTDATED:
        isins = [
            isin
            for isin in isins
            if db[isin]
            and (not db[isin].prediction or db[isin].has_outdated_prediction)
        ]
    elif update_predictions == PredictionsUpdateMode.SKIP:
        return None

    if not isins:
        return None

    await _set_inns(client, db, isins=isins)
    csrf = await _get_cbr_csrf(client)

    caption = "Loading ratings from CBR"
    for isin in tqdm(isins, caption):
        predictions = []
        ticker = db[isin]

        if not ticker:
            continue

        for page in count(1):
            data = {"fields[pageNumber]": page, "fields[inn]": ticker.inn}

            if page > 1:
                del data["fields[inn]"]
                action = "searchRatingNavigation"
            else:
                action = "searchRating"

            response = await client.request(
                method=config["method"],
                url=config["url"],
                headers={"X-Bitrix-Csrf-Token": csrf},
                params={"mode": "ajax", "c": "prr.form", "action": action},
                data=data,
            )

            if not response.json()["data"]:
                break

            cbr_data = CbrData(**response.json()["data"])
            predictions.extend(cbr_data.item_list)

            if cbr_data.page_count == page:
                break

        ticker = db[isin]
        predictions = sorted(
            predictions,
            key=that.release_date,
            reverse=True,
        )

        company_predictions = [
            p for p in predictions if not has_prefixes(p.object_type, ("TBND", "TMNB"))
        ]
        isin_predictions = [p for p in predictions if p.isin == isin]

        data = _get_last_prediction(company_predictions or isin_predictions)
        ticker.prediction = data[0]
        ticker.prediction_date = data[1]

    return db


async def _set_inns(client, db, *, isins):
    config = CONFIG["moex"]
    sem = Semaphore(config["concurrency"])
    isins = [isin for isin in isins if db[isin] and not db[isin].inn]

    if not isins:
        return

    reqs = [
        Request(
            sem=sem,
            url=config["url"],
            params={
                "Format.Type": "csv",
                "Format.Delimiter": "comma",
                "Data.Filter": f"query={isin}",
            },
        )
        for isin in isins
    ]
    caption = "Loading INNs from MOEX"

    async for isin, response in azip(isins, get_batch(caption, client, reqs)):
        with StringIO(response.text) as f:
            reader = csv.DictReader(f)
            db[isin].inn = next(reader)["INN"]


def _get_last_prediction(predictions: list[CbrItem]) -> tuple[Prediction, date]:
    withdrawn_kra = []
    withdrawn_date = None

    if not predictions:
        return (Prediction.STABLE, date.today())

    for data in predictions:
        kra = data.kra_name
        if kra in withdrawn_kra:
            continue

        if data.rating_action.startswith("WD"):
            withdrawn_kra.append(kra)
            withdrawn_date = data.release_date
        else:
            return (_parse_prediction(data.prediction), data.release_date)

    return (Prediction.WITHDRAWN, withdrawn_date or date.today())


def _parse_prediction(s: str) -> Prediction:
    if has_prefixes(s, ("STA", "NA")):
        return Prediction.STABLE

    if has_prefixes(s, ("UN", "DEV", "UNW")) or not s:
        return Prediction.UNKNOWN

    if has_prefixes(s, ("NEG", "OP")):
        return Prediction.NEGATIVE

    if has_prefixes(s, ("POS",)):
        return Prediction.POSITIVE

    raise ValueError(s)


async def _get_cbr_csrf(client):
    with indicate_work("Getting CSRF token for CBR"):
        response = await client.post(
            CONFIG["cbr"]["url"],
            params={"mode": "ajax", "c": "prr.form", "action": "searchRating"},
            data={"fields[ratingName]": "RU000A10B2D2"},
        )
        return response.json()["errors"][0]["customData"]["csrf"]
