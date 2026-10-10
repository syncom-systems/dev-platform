"""Error taxonomy. Each class maps to one documented process exit code."""

EXIT_OK = 0
EXIT_UNSATISFIED = 1  # a check failed, or a mandatory obligation is unsatisfied
EXIT_USAGE = 2  # bad invocation or invalid configuration
EXIT_PLATFORM = 3  # platform version cannot be resolved or verified


class DevPlatformError(Exception):
    exit_code = EXIT_USAGE


class ConfigError(DevPlatformError):
    exit_code = EXIT_USAGE

    def __init__(self, problems: list[str]):
        self.problems = problems
        super().__init__("; ".join(problems))


class PlatformResolutionError(DevPlatformError):
    exit_code = EXIT_PLATFORM
