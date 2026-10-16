from async_typer import Option


def env_option(*, common_envs, env, prefix):
    if env.startswith("<"):
        common_env = common_envs[env]
        envs = [common_env, f"{prefix}_{common_env}"]
    else:
        envs = f"{prefix}_{env}"
    return Option(envvar=envs)
