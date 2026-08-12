#!/usr/bin/env node

import { execFileSync } from 'node:child_process';
import { randomUUID } from 'node:crypto';
import { mkdir, readFile, rename, rm, writeFile } from 'node:fs/promises';
import { basename, dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const packageRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const packageJson = JSON.parse(await readFile(join(packageRoot, 'package.json'), 'utf8'));
const fileSizeHookSource = join(packageRoot, 'hooks/file_size_hint.py');
const fileSizeHookRelativePath = '.codex/hooks/harness/file_size_hint.py';
const fileSizeHookCommand =
  '/usr/bin/python3 "$(git rev-parse --show-toplevel)/.codex/hooks/harness/file_size_hint.py"';
const legacyFileSizeHookRelativePath = '.codex/hooks/file_size_hint.py';
const legacyFileSizeHookCommand =
  '/usr/bin/python3 "$(git rev-parse --show-toplevel)/.codex/hooks/file_size_hint.py"';
const handoffHookSource = join(packageRoot, 'hooks/handoff.py');
const handoffHookRelativePath = '.codex/hooks/harness/handoff.py';
const handoffHookCommand =
  '/usr/bin/python3 "$(git rev-parse --show-toplevel)/.codex/hooks/harness/handoff.py"';
const skillFiles = [
  { path: 'SKILL.md', mode: 0o644 },
  { path: 'agents/openai.yaml', mode: 0o644 },
  { path: 'scripts/start.py', mode: 0o755 },
];

function usage() {
  return `Usage: harness <command> [options]

Commands:
  install  Install the project-local agent tools into a Git repository
  state    Report the current Git and GitHub handoff state

Options:
  --repo <path>  Repository or subdirectory to use (default: cwd)
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

function parseRepositoryArguments(args) {
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

function installEvent(config, event, command, timeout, matcher, obsoleteCommands = []) {
  const groups = config.hooks[event] ?? [];
  if (!Array.isArray(groups)) {
    throw new Error(`hooks.${event} must be an array`);
  }

  const retainedGroups = [];
  let removedObsoleteCommand = false;
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
    const handlers = group.hooks.filter((handler) => {
      if (handler.command === command) {
        return false;
      }
      if (obsoleteCommands.includes(handler.command)) {
        removedObsoleteCommand = true;
        return false;
      }
      return true;
    });
    if (handlers.length > 0) {
      retainedGroups.push({ ...group, hooks: handlers });
    }
  }

  const group = {
    hooks: [
      {
        type: 'command',
        command,
        timeout,
      },
    ],
  };
  if (matcher !== undefined) {
    group.matcher = matcher;
  }
  retainedGroups.push(group);
  config.hooks[event] = retainedGroups;
  return removedObsoleteCommand;
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
  const config = await readHooksConfig(hooksPath);

  let removeLegacyFileSizeHook = false;
  for (const event of ['PreToolUse', 'PostToolUse']) {
    removeLegacyFileSizeHook =
      installEvent(
        config,
        event,
        fileSizeHookCommand,
        5,
        '^apply_patch$',
        [legacyFileSizeHookCommand],
      ) || removeLegacyFileSizeHook;
  }
  installEvent(config, 'Stop', handoffHookCommand, 30);

  await atomicWrite(
    join(root, fileSizeHookRelativePath),
    await readFile(fileSizeHookSource),
    0o644,
  );
  await atomicWrite(
    join(root, handoffHookRelativePath),
    await readFile(handoffHookSource),
    0o644,
  );
  await atomicWrite(hooksPath, `${JSON.stringify(config, null, 2)}\n`, 0o644);
  if (removeLegacyFileSizeHook) {
    await rm(join(root, legacyFileSizeHookRelativePath), { force: true });
  }
  for (const file of skillFiles) {
    const source = join(packageRoot, 'skills/imp', file.path);
    const target = join(root, '.agents/skills/imp', file.path);
    await atomicWrite(target, await readFile(source), file.mode);
  }

  console.log(`Installed ${packageJson.name}@${packageJson.version} in ${root}`);
  console.log(`  ${fileSizeHookRelativePath}`);
  console.log(`  ${handoffHookRelativePath}`);
  console.log('  .codex/hooks.json');
  console.log('  .agents/skills/imp/');
  console.log('Review and trust the project hook with /hooks in Codex.');
}

function state(repo) {
  const root = repositoryRoot(repo);
  try {
    const output = execFileSync(
      '/usr/bin/python3',
      [handoffHookSource, 'state', '--repo', root],
      { encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] },
    );
    process.stdout.write(output);
  } catch (error) {
    const detail = error.stderr?.toString().trim() || error.message;
    throw new Error(`cannot inspect handoff state: ${detail}`);
  }
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
  if (!['install', 'state'].includes(command)) {
    throw new Error(`unknown command: ${command}`);
  }

  const options = parseRepositoryArguments(args);
  if (options !== null) {
    if (command === 'install') {
      await install(options.repo);
    } else {
      state(options.repo);
    }
  }
}

main().catch((error) => {
  console.error(`harness: ${error.message}`);
  process.exitCode = 1;
});
