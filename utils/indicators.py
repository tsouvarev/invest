from collections.abc import Generator
from contextlib import contextmanager


@contextmanager
def indicate_work(msg_enter: str, msg_exit: str = "Done") -> Generator:
    print(f"{msg_enter}... ", end="")
    yield
    print(msg_exit)
