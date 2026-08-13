#!/usr/bin/env node

import { execFileSync } from 'node:child_process';
import { randomUUID } from 'node:crypto';
import { mkdir, readFile, rename, rm, writeFile } from 'node:fs/promises';
import { basename, dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

const packageRoot = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const packageJson = JSON.parse(await readFile(join(packageRoot, 'package.json'), 'utf8'));

function hookCommand(relativePath) {
  return `/usr/bin/python3 "$(git rev-parse --show-toplevel)/${relativePath}"`;
}

const codexHooksRelativePath = '.codex/hooks.json';
const cursorHooksRelativePath = '.cursor/hooks.json';
const fileSizeHookSource = join(packageRoot, 'hooks/file_size_hint.py');
const fileSizeHookRelativePath = '.agents/hooks/harness/file_size_hint.py';
const fileSizeHookCommand = hookCommand(fileSizeHookRelativePath);
const handoffHookSource = join(packageRoot, 'hooks/handoff.py');
const handoffHookRelativePath = '.agents/hooks/harness/handoff.py';
const handoffHookCommand = hookCommand(handoffHookRelativePath);
const deliverySource = join(packageRoot, 'hooks/delivery.py');
const cleanupSource = join(packageRoot, 'hooks/cleanup.py');
const codexEditMatcher = '^apply_patch$';
const cursorEditMatcher = '^(Write|Delete)$';
const obsoleteFileSizeHookPaths = [
  '.codex/hooks/file_size_hint.py',
  '.codex/hooks/harness/file_size_hint.py',
];
const obsoleteHandoffHookPaths = ['.codex/hooks/harness/handoff.py'];
const obsoleteFileSizeHookCommands = obsoleteFileSizeHookPaths.map(hookCommand);
const obsoleteHandoffHookCommands = obsoleteHandoffHookPaths.map(hookCommand);

function usage() {
  return `Usage: harness <command> [options]

Commands:
  install  Install the project-local agent tools into a Git repository
  state    Report the current Git and GitHub handoff state
  await    Block until the current branch's pull request needs its author
  cleanup  Remove worktrees whose pull request merged

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
  const rest = [];
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
    rest.push(argument);
  }
  return { repo, rest };
}

async function readHooksConfig(path, defaults) {
  let source;
  try {
    source = await readFile(path, 'utf8');
  } catch (error) {
    if (error.code === 'ENOENT') {
      return { ...defaults, hooks: {} };
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

function installCodexEvent(config, event, command, timeout, matcher, obsoleteCommands) {
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
    const handlers = group.hooks.filter(
      (handler) => handler.command !== command && !obsoleteCommands.includes(handler.command),
    );
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
}

function installCursorEvent(config, event, handler, obsoleteCommands) {
  const handlers = config.hooks[event] ?? [];
  if (!Array.isArray(handlers)) {
    throw new Error(`hooks.${event} must be an array`);
  }

  const retained = handlers.filter((entry) => {
    if (entry === null || Array.isArray(entry) || typeof entry !== 'object') {
      throw new Error(`hooks.${event} entries must be objects`);
    }
    return entry.command !== handler.command && !obsoleteCommands.includes(entry.command);
  });
  retained.push(handler);
  config.hooks[event] = retained;
}

async function atomicWrite(path, contents, mode) {
  await mkdir(dirname(path), { recursive: true });
  const temporary = join(dirname(path), `.${basename(path)}.${process.pid}.${randomUUID()}`);
  await writeFile(temporary, contents, { mode });
  await rename(temporary, path);
}

async function install(repo) {
  const root = repositoryRoot(repo);

  const codexHooksPath = join(root, codexHooksRelativePath);
  const codexConfig = await readHooksConfig(codexHooksPath, {
    description: 'Project-local Codex hooks.',
  });
  for (const event of ['PreToolUse', 'PostToolUse']) {
    installCodexEvent(
      codexConfig,
      event,
      fileSizeHookCommand,
      5,
      codexEditMatcher,
      obsoleteFileSizeHookCommands,
    );
  }
  installCodexEvent(
    codexConfig,
    'Stop',
    handoffHookCommand,
    30,
    undefined,
    obsoleteHandoffHookCommands,
  );

  const cursorHooksPath = join(root, cursorHooksRelativePath);
  const cursorConfig = await readHooksConfig(cursorHooksPath, { version: 1 });
  for (const event of ['preToolUse', 'postToolUse']) {
    installCursorEvent(
      cursorConfig,
      event,
      { command: fileSizeHookCommand, matcher: cursorEditMatcher, timeout: 5 },
      obsoleteFileSizeHookCommands,
    );
  }
  installCursorEvent(
    cursorConfig,
    'stop',
    { command: handoffHookCommand, timeout: 30, loop_limit: null },
    obsoleteHandoffHookCommands,
  );

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
  await atomicWrite(codexHooksPath, `${JSON.stringify(codexConfig, null, 2)}\n`, 0o644);
  await atomicWrite(cursorHooksPath, `${JSON.stringify(cursorConfig, null, 2)}\n`, 0o644);
  for (const relativePath of [...obsoleteFileSizeHookPaths, ...obsoleteHandoffHookPaths]) {
    await rm(join(root, relativePath), { force: true });
  }
  console.log(`Installed ${packageJson.name}@${packageJson.version} in ${root}`);
  console.log(`  ${fileSizeHookRelativePath}`);
  console.log(`  ${handoffHookRelativePath}`);
  console.log(`  ${codexHooksRelativePath}`);
  console.log(`  ${cursorHooksRelativePath}`);
  console.log('Review and trust the project hook with /hooks in Codex.');
  console.log('Add the skills with: npx skills@latest add limchihi/harness');
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

function delegate(source, repo, args, failure) {
  const root = repositoryRoot(repo);
  try {
    execFileSync('/usr/bin/python3', [source, '--repo', root, ...args], {
      stdio: 'inherit',
    });
  } catch (error) {
    throw new Error(`${failure}: ${error.message}`);
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
  if (!['install', 'state', 'await', 'cleanup'].includes(command)) {
    throw new Error(`unknown command: ${command}`);
  }

  const options = parseRepositoryArguments(args);
  if (options === null) {
    return;
  }
  if (command === 'await') {
    delegate(deliverySource, options.repo, options.rest, 'cannot await the pull request');
    return;
  }
  if (command === 'cleanup') {
    delegate(cleanupSource, options.repo, options.rest, 'cannot clean up worktrees');
    return;
  }
  if (options.rest.length > 0) {
    throw new Error(`unknown argument: ${options.rest[0]}`);
  }
  if (command === 'install') {
    await install(options.repo);
    return;
  }
  state(options.repo);
}

main().catch((error) => {
  console.error(`harness: ${error.message}`);
  process.exitCode = 1;
});
