from datetime import date, timedelta
from enum import StrEnum, auto
from functools import cached_property

from pydantic import BaseModel, ConfigDict, computed_field, field_validator

type Db = dict[str, Ticker | None]


class PredictionsUpdateMode(StrEnum):
    SKIP = auto()
    OUTDATED = auto()
    ALL = auto()


class Ticker(BaseModel):
    isin: str
    company: str
    series: str
    inn: str | None = None
    grade: str | None = None
    nominal: str | None = None
    maturity_date: date | None = None
    sector: Sector | None = None
    coupon: float | None = None
    quote: float | None = None
    prediction: Prediction | None = None
    prediction_date: date | None = None

    model_config = ConfigDict(use_enum_values=True)

    @field_validator("prediction_date", mode="before")
    @classmethod
    def parse_prediction_date(cls, v):
        if v is None:
            return v

        try:
            return date.strptime(v, "%d.%m.%Y")
        except ValueError:
            return date.strptime(v, "%Y-%m-%d")

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
    def has_outdated_prediction(self):
        cutoff = date.today() - timedelta(days=200)
        return self.prediction_date < cutoff


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
    C_PLUS = "C+"
    C = "C"
    C_MINUS = "C-"


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
