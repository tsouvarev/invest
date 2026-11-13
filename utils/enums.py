from ordered_enum import OrderedEnum


class ReverseOrderedEnum(OrderedEnum):
    def __lt__(self, *args, **kwargs):
        return not super().__lt__(*args, *kwargs)
