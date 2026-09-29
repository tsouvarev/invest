from datetime import date, datetime, timedelta
from functools import cached_property

from pydantic import (
    BaseModel,
    ConfigDict,
    FieldSerializationInfo,
    computed_field,
    field_serializer,
)

from clients import BondType, Grade, Prediction, Sector
from utils import localize_date, localize_digits, localize_percents, now

type Db = dict[str, Ticker | None]

OUTDATED_PREDICTION_CUTOFF = timedelta(days=200)
OUTDATED_CUTOFF = timedelta(hours=2)


class Ticker(BaseModel):
    ts: datetime
    isin: str
    type: BondType
    company: str
    series: str
    inn: str
    grade: Grade
    nominal: float
    maturity_date: date
    sector: Sector
    coupon: float
    quote: float
    prediction: Prediction
    prediction_date: date

    model_config = ConfigDict(use_enum_values=True)

    @field_serializer("coupon", "quote", mode="plain")
    @classmethod
    def serialize_percents(cls, v, info: FieldSerializationInfo):
        if info.mode_is_json():
            return v
        return localize_percents(v)

    @field_serializer("nominal", mode="plain")
    @classmethod
    def serialize_digits(cls, v, info: FieldSerializationInfo):
        if info.mode_is_json():
            return v
        return localize_digits(v)

    @field_serializer("maturity_date", "prediction_date", mode="plain")
    @classmethod
    def serialize_date(cls, v, info: FieldSerializationInfo):
        if info.mode_is_json():
            return v
        return localize_date(v)

    @field_serializer("type", mode="plain")
    @classmethod
    def serialize_type(cls, v, info: FieldSerializationInfo):
        if info.mode_is_json():
            return v

        match v:
            case (
                BondType.FIX_KNOWN
                | BondType.FIX_UNKNOWN
                | BondType.AMORTIZED
                | BondType.LINKER
                | BondType.CONVERTIBLE
            ):
                return "Фикс"
            case BondType.FLOATER:
                return "Флоат"
            case _:
                msg = f"{v=}"
                raise ValueError(msg)

    @field_serializer("prediction", mode="plain")
    @classmethod
    def serialize_prediction(cls, v, info: FieldSerializationInfo):
        if info.mode_is_json():
            return v

        match v:
            case Prediction.STABLE:
                return "Стабильный"
            case Prediction.UNKNOWN:
                return "Неопределенный"
            case Prediction.NEGATIVE:
                return "Негативный"
            case Prediction.POSITIVE:
                return "Позитивный"
            case Prediction.WITHDRAWN | None:
                return "Отозван"
            case _:
                msg = f"{v=}"
                raise ValueError(msg)

    @computed_field
    @property
    def name(self) -> str:
        return f"{self.company} {self.series}"

    @cached_property
    def _company(self) -> str:
        company = self.company.lower()

        redundant_prefixes = ["гк ", "группа "]
        for prefix in redundant_prefixes:
            company = company.removeprefix(prefix)

        return company

    @cached_property
    def _isin(self):
        return self.isin.lower()

    @property
    def has_outdated_prediction(self) -> bool:
        return self.is_outdated or (
            now().date() - self.prediction_date > OUTDATED_PREDICTION_CUTOFF
        )

    @property
    def is_outdated(self) -> bool:
        return now() - self.ts > OUTDATED_CUTOFF

    @property
    def is_floater(self) -> bool:
        return self.type == BondType.FLOATER


# updates forward refs
Ticker.model_rebuild(force=True)
