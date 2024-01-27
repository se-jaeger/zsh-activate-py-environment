#!/usr/bin/env python3

import contextlib
import errno
import re
import sys
from argparse import ArgumentParser
from os import environ, getcwd, listdir, remove
from os.path import abspath, isdir, isfile, join, split
from shutil import which
from subprocess import DEVNULL, CalledProcessError, check_call, run
from sys import stderr

with contextlib.suppress(ModuleNotFoundError):
    import yaml

##########################
##### Some Constants #####

CONDA_TYPE = "conda"
VENV_TYPE = "venv"
POETRY_TYPE = "poetry"
LINKED_TYPE = "linked"

SUPPORTED_ENVIRONMENT_TYPES = [CONDA_TYPE, VENV_TYPE, POETRY_TYPE]

LINKED_ENV_FILES = [".linked_env"]
POETRY_FILES = ["poetry.lock", "pyproject.toml"]
VENV_FILES = ["venv", ".venv"]
CONDA_FILES = ["environment.yaml", "environment.yml"]

TYPE_TO_FILES = {
    LINKED_TYPE: LINKED_ENV_FILES,
    POETRY_TYPE: POETRY_FILES,
    VENV_TYPE: VENV_FILES,
    CONDA_TYPE: CONDA_FILES,
}

FILE_TO_TYPE = {
    environment_file: type_
    for type_, environment_files_list in TYPE_TO_FILES.items()
    for environment_file in environment_files_list
}

# conda env names are not allowed to contain: "/", " ", ":", "#"
# see: https://github.com/conda/conda/blob/e23cd61c12a68149ab9387baea5fb9b4f34b40aa/conda/base/context.py#L1767-L1772
YAML_ENV_NAME_REGEX = re.compile(r"^\s*name:\s*([^\/\s:#]*)")

RED = "\033[0;31m"
GREEN = "\033[0;32m"
GRAY = "\033[1;30m"
NC = "\033[0m"

IS_FIRST_MESSAGE = True

##########################
##### Main Functions #####


def main():
    # TODO(se-jaeger): add custom print usage function
    parser = ArgumentParser(
        description="Automagically detect and activate python environments (poetry, virtualenv, conda)",
    )
    subparsers = parser.add_subparsers()

    # activate command
    # TODO(se-jaeger): after linking directory, this is called again and we print the message pre-fix twice
    parser_activate = subparsers.add_parser("activate")
    parser_activate.set_defaults(command_function=activate)

    # deactivate command
    parser_activate = subparsers.add_parser("deactivate")
    parser_activate.set_defaults(command_function=deactivate)

    # link command
    parser_link = subparsers.add_parser("link")
    parser_link.set_defaults(command_function=link)

    parser_link.add_argument("environment_type", choices=[VENV_TYPE, CONDA_TYPE])
    parser_link.add_argument("name_or_path", type=str)

    # unlink command
    parser_unlink = subparsers.add_parser("unlink")
    parser_unlink.set_defaults(command_function=unlink)

    args = parser.parse_args()
    args.command_function(
        # call given command function with parameters
        **{parameter: value for parameter, value in vars(args).items() if parameter != "command_function"},
    )


def activate():
    type_and_environment_file = __find_nearest_environment_file()

    if type_and_environment_file:
        __handle_environment_file(type_and_environment_file[0], type_and_environment_file[1])


def deactivate():
    conda_environment_name = environ.get("CONDA_DEFAULT_ENV", "")

    if environ.get("VIRTUAL_ENV", ""):
        __return_command("deactivate")

    # Do not deactivate conda base environment.
    # TODO(se-jaeger): expose possibility to change this
    elif conda_environment_name and conda_environment_name != "base":
        __return_command("conda deactivate")


def link(environment_type, name_or_path):
    if any(linked_env_file in listdir() for linked_env_file in LINKED_ENV_FILES):
        __print_error_and_fail(
            "This directory is already linked! You can remove this by using 'unlink_py_environment'",
            error_code=errno.EEXIST,
        )

    if environment_type == VENV_TYPE:
        with open(LINKED_ENV_FILES[0], "w") as file:
            file.write(f"{environment_type};{abspath(name_or_path)}")

    elif environment_type == CONDA_TYPE:
        with open(LINKED_ENV_FILES[0], "w") as file:
            file.write(f"{environment_type};{name_or_path}")

    __print_success("Directory linked!", flush=True)


def unlink():
    linked_files_in_working_directory = [file for file in LINKED_ENV_FILES if isfile(file)]

    if linked_files_in_working_directory:
        for file in linked_files_in_working_directory:
            remove(file)

    else:
        __print_information(
            f"No file found that explicitly links this directory, looked for: {', '.join(LINKED_ENV_FILES)}",
            flush=False,
        )

    __print_success("Directory unlinked!", flush=True)


############################
##### Helper Functions #####


def __print_information(message, flush, color=GRAY):
    global IS_FIRST_MESSAGE

    message_prefix = (f"{GRAY}" + "\n[ZSH Activate Python Environment]:\n") if IS_FIRST_MESSAGE else ""
    after_newline = "\n" if flush else ""
    msg = f"{message_prefix}{color}---> {message}{NC}{after_newline}"

    print(msg, file=stderr)  # noqa: T201
    IS_FIRST_MESSAGE = False


def __print_success(message, flush):
    __print_information(message, flush=flush, color=GREEN)


def __print_error_and_fail(message, error_code=errno.EPERM):
    __print_information(message, flush=True, color=RED)
    sys.exit(error_code)


def __return_command(shell_command):
    print(shell_command)  # noqa: T201


def __find_nearest_environment_file(directory=None, priority=None):
    if directory is None:
        directory = getcwd()

    if priority is None:
        priority = [CONDA_TYPE, LINKED_TYPE, POETRY_TYPE, VENV_TYPE]

    if any(environment_type not in TYPE_TO_FILES for environment_type in priority) or any(
        not isinstance(environment_type, str) for environment_type in priority
    ):
        __print_error_and_fail(
            f"Only the following environment types (given as `str`) are supported! - {', '.join(TYPE_TO_FILES.keys())}",
            error_code=errno.EINVAL,
        )

    if not isdir(directory):
        __print_error_and_fail(
            "Parameter `directory` need to be a valid directory!",
            error_code=errno.EINVAL,
        )

    directory_content = listdir(directory)

    # iterate over list of lists that contain the actual files to look for
    for environment_files_list in [TYPE_TO_FILES[type_] for type_ in priority]:
        for environment_file in environment_files_list:
            if environment_file in directory_content:
                return FILE_TO_TYPE[environment_file], join(directory, environment_file)

    parent_directory, not_root_directory = split(directory)
    if not_root_directory:
        return __find_nearest_environment_file(directory=parent_directory, priority=priority)

    return None


def __parse_conda_env_file_and_get_name(environment_file):
    try:
        with open(environment_file) as file:
            if "yaml" in sys.modules:
                env = yaml.safe_load(file)
                return env["name"]

            for line in file:
                match = re.match(YAML_ENV_NAME_REGEX, line)
                if match:
                    return match.group(1)

            # jump to `except` block
            raise Exception

    except:
        __print_error_and_fail(
            f"Something went wrong! Is the environment file malformed? - Check: {environment_file}",
            error_code=errno.EPERM,
        )


def __parse_linked_environment_file(linked_environment_file):
    if not isfile(linked_environment_file):
        __print_error_and_fail(
            f"Found linked environment file is not a file. Check: {linked_environment_file}",
            error_code=errno.ENOENT,
        )

    try:
        with open(linked_environment_file) as file:
            environment_type, environment_path_or_name = file.read().split(";")

    except:
        __print_error_and_fail(
            f"Something went wrong! Is the linked environment file malformed? - Check: {linked_environment_file}",
            error_code=errno.EPERM,
        )

    if environment_type not in SUPPORTED_ENVIRONMENT_TYPES:
        __print_error_and_fail(
            "The given environment type in the linked environment file is not supported. "
            + "Type: {environment_type} found in: {linked_environment_file}",
            error_code=errno.EINVAL,
        )

    return environment_type.strip(), environment_path_or_name.strip()


def __check_dependencies(command):
    if which(command):
        return True

    __print_information(
        f"Necessary dependency '{command}' not installed, omitting this!",
        flush=False,
    )
    return False


def __print_activation_message(environment_type):
    __print_information(f"Try to activate '{environment_type}' environment ... 🐍🐍", flush=True)


def __handle_environment_file(type_, environment_path_file_or_name):
    if type_ == LINKED_TYPE:
        # either path to poetry/virtualenv or conda environment name.
        environment_type, environment_path_or_name = __parse_linked_environment_file(environment_path_file_or_name)
        __handle_environment_file(environment_type, environment_path_or_name)

    elif type_ == POETRY_TYPE:
        if __check_dependencies(POETRY_TYPE):
            __print_activation_message(type_)
            run(["poetry", "shell"])

    elif type_ == VENV_TYPE:
        __print_activation_message(type_)
        run(["source", f"{environment_path_file_or_name}/bin/activate"], check=False)

    elif type_ == CONDA_TYPE:
        if __check_dependencies(CONDA_TYPE):
            # It is env file, we parse it to get env name
            if isfile(environment_path_file_or_name):
                environment_path_file_or_name = __parse_conda_env_file_and_get_name(environment_path_file_or_name)

            __print_activation_message(TYPE_TO_FILES)
            run(["conda", "activate", f"{environment_path_file_or_name}"], check=False)

    else:
        __print_error_and_fail(
            f"Something went wrong! Do not know environment type '{type_}'. "
            "Maybe this was extracted from file that links this directory?",
            error_code=0,
        )


if __name__ == "__main__":
    main()
