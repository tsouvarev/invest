from pathlib import Path

from funcy.seqs import concat
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build

from .utils import indicate_work


def load_tickers_from_sheet(token: Path, sheet_id: str, col_id: str) -> list[str]:
    with indicate_work("Loading tickers from sheet"):
        creds = Credentials.from_service_account_file(
            str(token), scopes=["https://www.googleapis.com/auth/spreadsheets"]
        )
        service = build("sheets", "v4", credentials=creds)

        sheet = service.spreadsheets()
        result = sheet.values().get(spreadsheetId=sheet_id, range=col_id).execute()
        return [v for v in concat(*result.get("values", [])) if v.startswith("RU")]


# def write_info_to_sheet(
#     token: Path, sheet_id: str, start_row: int, values: list[list]
# ) -> list[str]:
#     with indicate_work("Writing tickers to sheet"):
#         creds = Credentials.from_service_account_file(
#             str(token), scopes=["https://www.googleapis.com/auth/spreadsheets"]
#         )
#         service = build("sheets", "v4", credentials=creds)

#         sheet = service.spreadsheets()
#         result = (
#             sheet.values()
#             .update(
#                 spreadsheetId=sheet_id,
#                 range=f"A{start_row}",
#                 body={"values": values},
#             )
#             .execute()
#         )
#         return [v for v in concat(*result.get("values", [])) if v.startswith("RU")]
