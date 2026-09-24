from datetime import date, datetime, timedelta
from enum import StrEnum, auto
from functools import cached_property
from typing import Annotated

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    FieldSerializationInfo,
    computed_field,
    field_serializer,
    field_validator,
)

from use_cases.utils import (
    localize_date,
    localize_digits,
    localize_percents,
    now,
    parse_date,
    str_percent_to_float,
)

type Db = dict[str, Ticker | None]
OUTDATED_PREDICTION_CUTOFF = timedelta(days=200)
OUTDATED_CUTOFF = timedelta(hours=2)


class Ticker(BaseModel):
    ts: Annotated[datetime, Field(default_factory=now)]
    isin: str
    company: str | None = None
    series: str | None = None
    inn: str | None = None
    grade: Grade | None = None
    nominal: float | None = None
    maturity_date: date | None = None
    sector: Sector | None = None
    coupon: float | None = None
    quote: float | None = None
    prediction: Prediction | None = None
    prediction_date: date | None = None

    model_config = ConfigDict(use_enum_values=True)

    @field_validator("prediction_date", "maturity_date", mode="before")
    @classmethod
    def parse_dt(cls, v):
        if isinstance(v, date | None):
            return v
        return parse_date("%d.%m.%Y", "%d-%m-%Y", "%Y-%m-%d")(v)

    @field_validator("sector", mode="before")
    @classmethod
    def parse_sector(cls, v):
        if isinstance(v, date | None):
            return v
        return Sector.from_value(v)

    @field_validator("coupon", "quote", mode="before")
    @classmethod
    def parse_percents(cls, v):
        if isinstance(v, float):
            return v
        return str_percent_to_float(v)

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

    @field_serializer("prediction", mode="plain")
    @classmethod
    def serialize_prediction(cls, v, info: FieldSerializationInfo):
        if info.mode_is_json():
            return v
        return Prediction.humanize(v)

    @computed_field
    @property
    def name(self) -> str:
        return f"{self.company} {self.series}"

    @cached_property
    def _company(self):
        return self.company.lower()

    @cached_property
    def _isin(self):
        return self.isin.lower()

    @property
    def has_outdated_prediction(self) -> bool:
        return self.is_outdated and (
            now().date() - self.prediction_date > OUTDATED_PREDICTION_CUTOFF
        )

    @property
    def is_outdated(self) -> bool:
        return now() - self.ts > OUTDATED_CUTOFF


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

    @classmethod
    def humanize(cls, v):
        match v:
            case cls.STABLE:
                return "Стабильный"
            case cls.UNKNOWN:
                return "Неопределенный"
            case cls.NEGATIVE:
                return "Негативный"
            case cls.POSITIVE:
                return "Позитивный"
            case cls.WITHDRAWN | None:
                return "Отозван"
            case _:
                raise ValueError(v)


class Sector(StrEnum):
    BANKING = "Банки"
    GOV = "Гос"
    FOOD = "Еда"
    LEASING = "Лизинг"
    INDUSTRY = "Производство"
    OTHER = "Прочее"
    RESOURCES = "Ресурсы"
    DEVELOPMENT = "Строительство"
    TRADING = "Торговля"
    TRANSPORT = "Транспорт"
    SERVICES = "Услуги"
    FARMA = "Фармацевтика"

    @classmethod
    def from_value(cls, v: str) -> Sector:
        return {
            "Машиностроение": Sector.INDUSTRY,
            "МФО": Sector.SERVICES,
            "Другие услуг": Sector.SERVICES,
            "Электроэнергетика": Sector.INDUSTRY,
            "Нефтегазовая отрасль": Sector.RESOURCES,
            "Горнодобывающие": Sector.RESOURCES,
            "Ломбарды": Sector.SERVICES,
            "Недвижимость": Sector.SERVICES,
            "Хим.пром": Sector.INDUSTRY,
            "Пищевая пром.": Sector.FOOD,
            "Сельское хозяйство": Sector.FOOD,
            "Черная металлургия": Sector.INDUSTRY,
            "Оборонная промышленность": Sector.INDUSTRY,
            "Потреб.услуги": Sector.SERVICES,
            "Телекомы": Sector.SERVICES,
            "IT компании": Sector.OTHER,
            "Высокие технологии": Sector.OTHER,
            "Другая промышленность": Sector.INDUSTRY,
            "Финансы прочие": Sector.BANKING,
            "Цветная Металлургия": Sector.INDUSTRY,
            "Холдинг": Sector.OTHER,
            "Субфедеральные": Sector.GOV,
            "Медицина": Sector.FARMA,
        }.get(v, v)


class Grade(StrEnum):
    AAA = "AAA"
    AA_PLUS = "AA+"
    AA = "AA"
    AA_MINUS = "AA-"
    A_PLUS = "A+"
    A = "A"
    A_MINUS = "A-"
    BBB_PLUS = "BBB+"
    BBB = "BBB"
    BBB_MINUS = "BBB-"
    BB_PLUS = "BB+"
    BB = "BB"
    BB_MINUS = "BB-"
    B_PLUS = "B+"
    B = "B"
    B_MINUS = "B-"
    CCC_PLUS = "CCC+"
    CCC = "CCC"
    CCC_MINUS = "CCC-"
    CC_PLUS = "CC+"
    CC = "CC"
    CC_MINUS = "CC-"
    C_PLUS = "C+"
    C = "C"
    C_MINUS = "C-"
    D_PLUS = "D+"
    D = "D"


class GradeQuality(StrEnum):
    HIGH = auto()
    MEDIUM_HIGH = auto()
    AVERAGE = auto()
    MEDIUM_LOW = auto()
    LOW = auto()

    @classmethod
    def humanize(cls, v):
        match v:
            case cls.HIGH:
                return "Высокий"
            case cls.MEDIUM_HIGH:
                return "Умеренно высокий"
            case cls.AVERAGE:
                return "Средний"
            case cls.MEDIUM_LOW:
                return "Умеренно низкий"
            case cls.LOW:
                return "Низкий"
            case _:
                raise ValueError(v)

    def from_grade(self, v: Grade) -> GradeQuality:
        match v:
            case self.AAA | self.AA_PLUS | self.AA:
                return GradeQuality.HIGH
            case self.AA_MINUS | self.A_PLUS | self.A:
                return GradeQuality.MEDIUM_HIGH
            case self.A_MINUS | self.BBB_PLUS | self.BBB | self.BBB_MINUS:
                return GradeQuality.AVERAGE
            case self.BB_PLUS | self.BB | self.BB_MINUS:
                return GradeQuality.MEDIUM_LOW
            case self.B_PLUS | self.B:
                return GradeQuality.LOW
            case _:
                raise ValueError(v)


# updates forward refs
Ticker.model_rebuild(force=True)
