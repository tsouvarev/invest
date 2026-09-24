import json

from funcy import concat
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

from .utils import indicate_work


def load_isins_from_sheet(token: str, sheet_id: str, col_id: str) -> list[str]:
    with indicate_work("Loading tickers from sheet"):
        creds = Credentials.from_service_account_info(
            json.loads(token), scopes=["https://www.googleapis.com/auth/spreadsheets"]
        )
        service = build("sheets", "v4", credentials=creds)

        sheet = service.spreadsheets()
        result = sheet.values().get(spreadsheetId=sheet_id, range=col_id).execute()
        return [v for v in concat(*result.get("values", [])) if v.startswith("RU")]
