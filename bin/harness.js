#!/usr/bin/env node

import { execFileSync } from 'node:child_process';
import { randomUUID } from 'node:crypto';
import { mkdir, readFile, rename, writeFile } from 'node:fs/promises';
import { basename, dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const packageRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const packageJson = JSON.parse(await readFile(join(packageRoot, 'package.json'), 'utf8'));
const hookSource = join(packageRoot, 'hooks/file_size_hint.py');
const hookRelativePath = '.codex/hooks/harness/file_size_hint.py';
const hookCommand =
  '/usr/bin/python3 "$(git rev-parse --show-toplevel)/.codex/hooks/harness/file_size_hint.py"';
const hookMatcher = '^apply_patch$';
const hookEvents = ['PreToolUse', 'PostToolUse'];

function usage() {
  return `Usage: harness install [--repo <path>]

Install the project-local Codex hooks into a Git repository.

Options:
  --repo <path>  Repository or subdirectory to install from (default: cwd)
  -h, --help     Show this help
  -v, --version  Show the package version`;
}

function repositoryRoot(start) {
  try {
    return execFileSync(
      'git',
      ['-C', resolve(start), 'rev-parse', '--show-toplevel'],
      { encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] },
    ).trim();
  } catch (error) {
    const detail = error.stderr?.toString().trim() || error.message;
    throw new Error(`cannot resolve Git repository: ${detail}`);
  }
}

function parseInstallArguments(args) {
  let repo = process.cwd();
  for (let index = 0; index < args.length; index += 1) {
    const argument = args[index];
    if (argument === '--repo') {
      if (index + 1 >= args.length) {
        throw new Error('--repo requires a path');
      }
      repo = args[index + 1];
      index += 1;
      continue;
    }
    if (argument === '--help' || argument === '-h') {
      console.log(usage());
      return null;
    }
    throw new Error(`unknown argument: ${argument}`);
  }
  return { repo };
}

async function readHooksConfig(path) {
  let source;
  try {
    source = await readFile(path, 'utf8');
  } catch (error) {
    if (error.code === 'ENOENT') {
      return {
        description: 'Project-local Codex hooks.',
        hooks: {},
      };
    }
    throw error;
  }

  const config = JSON.parse(source);
  if (config === null || Array.isArray(config) || typeof config !== 'object') {
    throw new Error(`${path} must contain a JSON object`);
  }
  if (config.hooks === undefined) {
    config.hooks = {};
  }
  if (config.hooks === null || Array.isArray(config.hooks) || typeof config.hooks !== 'object') {
    throw new Error(`${path} field "hooks" must be a JSON object`);
  }
  return config;
}

function installEvent(config, event) {
  const groups = config.hooks[event] ?? [];
  if (!Array.isArray(groups)) {
    throw new Error(`hooks.${event} must be an array`);
  }

  const retainedGroups = [];
  for (const group of groups) {
    if (group === null || Array.isArray(group) || typeof group !== 'object') {
      throw new Error(`hooks.${event} entries must be objects`);
    }
    if (!Array.isArray(group.hooks)) {
      throw new Error(`hooks.${event} entry field "hooks" must be an array`);
    }
    for (const handler of group.hooks) {
      if (handler === null || Array.isArray(handler) || typeof handler !== 'object') {
        throw new Error(`hooks.${event} handlers must be objects`);
      }
    }
    const handlers = group.hooks.filter((handler) => handler?.command !== hookCommand);
    if (handlers.length > 0) {
      retainedGroups.push({ ...group, hooks: handlers });
    }
  }

  retainedGroups.push({
    matcher: hookMatcher,
    hooks: [
      {
        type: 'command',
        command: hookCommand,
        timeout: 5,
      },
    ],
  });
  config.hooks[event] = retainedGroups;
}

async function atomicWrite(path, contents, mode) {
  await mkdir(dirname(path), { recursive: true });
  const temporary = join(dirname(path), `.${basename(path)}.${process.pid}.${randomUUID()}`);
  await writeFile(temporary, contents, { mode });
  await rename(temporary, path);
}

async function install(repo) {
  const root = repositoryRoot(repo);
  const hooksPath = join(root, '.codex/hooks.json');
  const destination = join(root, hookRelativePath);
  const config = await readHooksConfig(hooksPath);
  const hook = await readFile(hookSource);

  for (const event of hookEvents) {
    installEvent(config, event);
  }

  await atomicWrite(destination, hook, 0o644);
  await atomicWrite(hooksPath, `${JSON.stringify(config, null, 2)}\n`, 0o644);

  console.log(`Installed ${packageJson.name}@${packageJson.version} in ${root}`);
  console.log(`  ${hookRelativePath}`);
  console.log('  .codex/hooks.json');
  console.log('Review and trust the project hook with /hooks in Codex.');
}

async function main() {
  const [command, ...args] = process.argv.slice(2);
  if (command === '--help' || command === '-h' || command === undefined) {
    console.log(usage());
    return;
  }
  if (command === '--version' || command === '-v') {
    console.log(packageJson.version);
    return;
  }
  if (command !== 'install') {
    throw new Error(`unknown command: ${command}`);
  }

  const options = parseInstallArguments(args);
  if (options !== null) {
    await install(options.repo);
  }
}

main().catch((error) => {
  console.error(`harness: ${error.message}`);
  process.exitCode = 1;
});
