from httpxyz import AsyncClient

from clients import (
    PredictionsUpdateMode,
    get_cbr_csrf,
    get_company_predictions,
    get_predictions,
)
from utils import print_model_list

from .db import load_from_db


async def print_ratings(
    client: AsyncClient, *, isin: str, with_bond_actions: bool
) -> None:
    db = await load_from_db(
        client, isins=[isin], update_predictions=PredictionsUpdateMode.SKIP
    )

    ticker = db[isin]
    if ticker is None:
        print("No data")

    csrf_token = await get_cbr_csrf(client)
    predictions = await get_predictions(client, csrf_token=csrf_token, inn=ticker.inn)

    if not with_bond_actions:
        predictions = get_company_predictions(predictions)

    print_model_list(
        predictions,
        fields=[
            "release_date",
            "object_name",
            "kra_name",
            "rating_action",
            "prediction",
        ],
    )
