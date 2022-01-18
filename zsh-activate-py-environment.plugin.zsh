# Add this directory to PATH env s.t. we can call the python script form anywhere
PATH=$(dirname "$0"):$PATH

function activate_py_environment_if_existing()
{
    deactivate_py_environment
    eval $(zsh-activate-py-environment.py "activate")
}

function deactivate_py_environment()
{
    eval $(zsh-activate-py-environment.py "deactivate")
}

function link_py_environment()
{
    zsh-activate-py-environment.py "link" "$@"
    if [ $? -eq 0 ]; then
        activate_py_environment_if_existing
    fi
}

function unlink_py_environment()
{
    deactivate_py_environment
    zsh-activate-py-environment.py "unlink"
}

autoload -Uz add-zsh-hook
add-zsh-hook -D chpwd activate_py_environment_if_existing
add-zsh-hook chpwd activate_py_environment_if_existing