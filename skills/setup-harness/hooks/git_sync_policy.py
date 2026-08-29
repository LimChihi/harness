#!/usr/bin/env python3
import json
import os
import re
import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path


CONTROL_TOKENS = frozenset({";", "&&", "||", "|", "&", "(", ")"})
SHELLS = frozenset({"bash", "dash", "ksh", "sh", "zsh"})
MERGE_OPTIONS_WITH_VALUES = frozenset(
    {
        "-F",
        "--file",
        "-m",
        "--message",
        "-s",
        "--strategy",
        "-X",
        "--strategy-option",
        "--into-name",
    }
)
GIT_OPTIONS_WITH_VALUES = frozenset(
    {
        "-c",
        "--config-env",
        "--exec-path",
        "--git-dir",
        "--namespace",
        "--super-prefix",
        "--work-tree",
    }
)
ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")


class PolicyError(Exception):
    pass


@dataclass(frozen=True)
class GitInvocation:
    subcommand: str
    arguments: tuple
    cwd: Path


def normalized_command(command):
    output = []
    quote = None
    index = 0
    while index < len(command):
        character = command[index]
        if character == "\\" and quote != "'" and index + 1 < len(command):
            if command[index + 1] == "\n":
                output.append(" ")
                index += 2
                continue
            output.extend((character, command[index + 1]))
            index += 2
            continue
        if character in "'\"":
            if quote is None:
                quote = character
            elif quote == character:
                quote = None
        if character == "\n" and quote is None:
            output.append(";\n")
        else:
            output.append(character)
        index += 1
    return "".join(output)


def simple_commands(command):
    lexer = shlex.shlex(
        normalized_command(command), posix=True, punctuation_chars="();|&"
    )
    lexer.whitespace_split = True
    lexer.commenters = "#"
    commands = []
    current = []
    for token in lexer:
        if token in CONTROL_TOKENS:
            if current:
                commands.append(current)
                current = []
            continue
        current.append(token)
    if current:
        commands.append(current)
    return commands


def is_redirection(token):
    return re.fullmatch(r"\d*(?:<<?|>>?|<>|>&|<&)", token) is not None


def executable(words):
    index = 0
    while index < len(words):
        token = words[index]
        if token in ("{", "}") or ASSIGNMENT.match(token):
            index += 1
            continue
        if is_redirection(token):
            index += 2
            continue
        break
    if index == len(words):
        return None, (), index

    name = os.path.basename(words[index])
    if name == "env":
        index += 1
        while index < len(words):
            token = words[index]
            if token == "-u" or token == "--unset":
                index += 2
            elif token.startswith("-") or ASSIGNMENT.match(token):
                index += 1
            else:
                break
        if index == len(words):
            return None, (), index
        name = os.path.basename(words[index])
    elif name == "command":
        index += 1
        while index < len(words) and words[index].startswith("-"):
            index += 1
        if index == len(words):
            return None, (), index
        name = os.path.basename(words[index])

    return name, tuple(words[index + 1 :]), index


def shell_script(name, arguments):
    if name not in SHELLS:
        return None
    for index, argument in enumerate(arguments):
        if argument == "-c" or (
            argument.startswith("-")
            and not argument.startswith("--")
            and "c" in argument[1:]
        ):
            if index + 1 == len(arguments):
                raise PolicyError(f"{name} -c is missing its command")
            return arguments[index + 1]
    return None


def git_invocation(arguments, cwd):
    directory = Path(cwd)
    index = 0
    while index < len(arguments):
        argument = arguments[index]
        if argument == "--":
            index += 1
            break
        if argument == "-C":
            if index + 1 == len(arguments):
                raise PolicyError("git -C is missing its path")
            value = Path(arguments[index + 1])
            directory = value if value.is_absolute() else directory / value
            index += 2
            continue
        if argument.startswith("-C") and len(argument) > 2:
            value = Path(argument[2:])
            directory = value if value.is_absolute() else directory / value
            index += 1
            continue
        name = argument.split("=", 1)[0]
        if name in GIT_OPTIONS_WITH_VALUES and "=" not in argument:
            if index + 1 == len(arguments):
                raise PolicyError(f"{name} is missing its value")
            index += 2
            continue
        if argument.startswith("-"):
            index += 1
            continue
        break
    if index == len(arguments):
        return None
    return GitInvocation(
        subcommand=arguments[index],
        arguments=tuple(arguments[index + 1 :]),
        cwd=directory.resolve(),
    )


def git_invocations(command, cwd, depth=0):
    if depth > 5:
        raise PolicyError("shell command nesting exceeds five levels")
    invocations = []
    for words in simple_commands(command):
        name, arguments, _ = executable(words)
        if name is None:
            continue
        nested = shell_script(name, arguments)
        if nested is not None:
            invocations.extend(git_invocations(nested, cwd, depth + 1))
            continue
        if name == "eval":
            invocations.extend(git_invocations(" ".join(arguments), cwd, depth + 1))
            continue
        if name != "git":
            continue
        invocation = git_invocation(arguments, cwd)
        if invocation is not None:
            invocations.append(invocation)
    return invocations


def default_ref(cwd):
    result = subprocess.run(
        [
            "git",
            "-C",
            str(cwd),
            "symbolic-ref",
            "--quiet",
            "--short",
            "refs/remotes/origin/HEAD",
        ],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0 or not result.stdout.strip():
        raise PolicyError(
            f"cannot resolve the default branch from origin/HEAD in {cwd}"
        )
    return result.stdout.strip()


def merge_targets(arguments):
    targets = []
    index = 0
    options_done = False
    while index < len(arguments):
        argument = arguments[index]
        if options_done:
            targets.append(argument)
            index += 1
            continue
        if argument == "--":
            options_done = True
            index += 1
            continue
        name = argument.split("=", 1)[0]
        if name in MERGE_OPTIONS_WITH_VALUES and "=" not in argument:
            if index + 1 == len(arguments):
                raise PolicyError(f"git merge {name} is missing its value")
            index += 2
            continue
        if argument.startswith("-"):
            index += 1
            continue
        targets.append(argument)
        index += 1
    return targets


def default_ref_names(remote_ref):
    if "/" not in remote_ref:
        raise PolicyError(f"invalid default branch ref: {remote_ref}")
    remote, branch = remote_ref.split("/", 1)
    return frozenset(
        {
            branch,
            remote_ref,
            f"refs/heads/{branch}",
            f"refs/remotes/{remote_ref}",
            f"remotes/{remote_ref}",
            f"{remote}/HEAD",
        }
    )


def targets_default_branch(targets, remote_ref):
    names = default_ref_names(remote_ref)
    ambiguous = frozenset({"FETCH_HEAD", "@{u}", "@{upstream}"})
    for target in targets:
        if target in ambiguous:
            return True
        for name in names:
            if target == name or target.startswith((f"{name}~", f"{name}^", f"{name}@{{")):
                return True
    return False


def merge_allowed(arguments):
    if "--help" in arguments or "-h" in arguments:
        return True
    if "--abort" in arguments or "--quit" in arguments:
        return True
    return "--ff-only" in arguments and not any(
        option in arguments for option in ("--no-ff", "--squash")
    )


def merge_violation(arguments, remote_ref):
    if merge_allowed(arguments):
        return False
    if "--continue" in arguments:
        return True
    targets = merge_targets(arguments)
    return not targets or targets_default_branch(targets, remote_ref)


def pull_violation(arguments):
    if "--help" in arguments or "-h" in arguments:
        return False
    if "--no-rebase" in arguments or "--rebase=false" in arguments:
        return True
    if "--ff-only" in arguments and "--no-ff" not in arguments:
        return False
    for argument in arguments:
        if argument == "--rebase" or argument.startswith("--rebase="):
            return False
        if (
            argument.startswith("-")
            and not argument.startswith("--")
            and "r" in argument[1:]
        ):
            return False
    return True


def violation_reason(invocation, remote_ref):
    if invocation.subcommand == "pull" and pull_violation(invocation.arguments):
        return (
            "Pulling must use rebase or fast-forward only. Use `git pull --rebase` "
            f"or `git fetch origin` followed by `git rebase {remote_ref}`."
        )
    if invocation.subcommand == "merge" and merge_violation(
        invocation.arguments, remote_ref
    ):
        return (
            "Updating a work branch from the default branch must use rebase. "
            f"Run `git fetch origin` followed by `git rebase {remote_ref}`."
        )
    return None


def policy_violation(command, cwd):
    refs = {}
    for invocation in git_invocations(command, cwd):
        if invocation.subcommand not in ("merge", "pull"):
            continue
        if invocation.subcommand == "pull" and not pull_violation(
            invocation.arguments
        ):
            continue
        if invocation.subcommand == "merge" and merge_allowed(
            invocation.arguments
        ):
            continue
        if invocation.cwd not in refs:
            refs[invocation.cwd] = default_ref(invocation.cwd)
        ref = refs[invocation.cwd]
        reason = violation_reason(invocation, ref)
        if reason is not None:
            return reason
    return None


def hook_cwd(payload):
    cwd = payload.get("cwd")
    if cwd:
        return Path(cwd).resolve()
    roots = payload.get("workspace_roots") or []
    if roots:
        return Path(roots[0]).resolve()
    raise PolicyError("missing cwd/workspace_roots")


def hook_command(payload):
    event = payload["hook_event_name"]
    if event == "PreToolUse":
        tool_input = payload.get("tool_input")
        if not isinstance(tool_input, dict) or not isinstance(
            tool_input.get("command"), str
        ):
            raise PolicyError("PreToolUse is missing tool_input.command")
        return tool_input["command"]
    if event == "beforeShellExecution":
        command = payload.get("command")
        if not isinstance(command, str):
            raise PolicyError("beforeShellExecution is missing command")
        return command
    raise PolicyError(f"unsupported hook event: {event}")


def block_output(event, reason):
    if event == "PreToolUse":
        return {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": reason,
            }
        }
    if event == "beforeShellExecution":
        return {
            "permission": "deny",
            "user_message": reason,
            "agent_message": reason,
        }
    raise PolicyError(f"unsupported hook event: {event}")


def main():
    payload = json.load(sys.stdin)
    try:
        reason = policy_violation(hook_command(payload), hook_cwd(payload))
    except (PolicyError, ValueError) as error:
        reason = (
            "Git synchronization policy could not analyze this shell command: "
            f"{error}. Run Git synchronization as direct commands."
        )
    if reason is not None:
        print(json.dumps(block_output(payload["hook_event_name"], reason)))


if __name__ == "__main__":
    main()
