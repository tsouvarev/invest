set dotenv-load

RUN := 'uv run --frozen --env-file .env'
RUN_INVEST := RUN + ' python -u main.py'
WITH_CUTOFF := '--exclude-newer "7 days ago"'

format:
    {{ RUN }} ruff format .
    {{ RUN }} ruff check . --fix-only --unsafe-fixes
    just --fmt
    {{ RUN }} toml-sort *.toml --in-place --all --sort-first preview,select,project,name,version,requires-python

check:
    {{ RUN }} ruff check .

install *packages:
    uv add {{ WITH_CUTOFF }} {{ packages }}

sync:
    uv sync --frozen

upgrade:
    uv lock --upgrade {{ WITH_CUTOFF }}
    just sync
    uv pip list --outdated {{ WITH_CUTOFF }}

show *args:
    {{ RUN_INVEST }} bonds show {{ args }}

dupes:
    {{ RUN_INVEST }} bonds duplicates

diff *args:
    {{ RUN_INVEST }} snaps diff {{ args }}

update *args:
    {{ RUN_INVEST }} db update {{ args }}

search *args:
    {{ RUN_INVEST }} bonds search {{ args }}
