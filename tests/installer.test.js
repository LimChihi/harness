import assert from 'node:assert/strict';
import { execFileSync, spawnSync } from 'node:child_process';
import { mkdtempSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import test from 'node:test';
import { fileURLToPath } from 'node:url';

const root = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const cli = join(root, 'bin/harness.js');
const packageVersion = JSON.parse(readFileSync(join(root, 'package.json'), 'utf8')).version;

function command(relativePath) {
  return `/usr/bin/python3 "$(git rev-parse --show-toplevel)/${relativePath}"`;
}

const fileSizeHookPath = '.agents/hooks/harness/file_size_hint.py';
const handoffHookPath = '.agents/hooks/harness/handoff.py';
const hookCommand = command(fileSizeHookPath);
const handoffHookCommand = command(handoffHookPath);
const legacyHookCommand = command('.codex/hooks/file_size_hint.py');
const codexOnlyHookCommand = command('.codex/hooks/harness/file_size_hint.py');
const codexOnlyHandoffCommand = command('.codex/hooks/harness/handoff.py');

function repository(t) {
  const path = mkdtempSync(join(tmpdir(), 'harness-installer-'));
  execFileSync('git', ['init', '--quiet', path]);
  t.after(() => rmSync(path, { recursive: true, force: true }));
  return path;
}

function runInstall(path, ...args) {
  return spawnSync(process.execPath, [cli, 'install', ...args], {
    cwd: path,
    encoding: 'utf8',
  });
}

function readConfig(path, relativePath) {
  return JSON.parse(readFileSync(join(path, relativePath), 'utf8'));
}

function handlers(config, event) {
  return config.hooks[event].flatMap((group) => group.hooks);
}

test('installs the hooks and project configuration', (t) => {
  const path = repository(t);
  const result = runInstall(path);

  assert.equal(result.status, 0, result.stderr);
  assert.match(readFileSync(join(path, fileSizeHookPath), 'utf8'), /MAX_UNPROMPTED_GROWTH = 30/);
  assert.match(readFileSync(join(path, handoffHookPath), 'utf8'), /def lifecycle_hint/);
  assert.match(
    readFileSync(join(path, '.agents/skills/imp/SKILL.md'), 'utf8'),
    /run `\/implement`/,
  );
  assert.match(
    readFileSync(join(path, '.agents/skills/imp/SKILL.md'), 'utf8'),
    /npx @limchihi\/harness state/,
  );
  assert.match(
    readFileSync(join(path, '.agents/skills/imp/scripts/start.py'), 'utf8'),
    /task\/\{issue\}/,
  );
  assert.match(
    readFileSync(join(path, '.agents/skills/imp/agents/openai.yaml'), 'utf8'),
    /allow_implicit_invocation: false/,
  );

  const codex = readConfig(path, '.codex/hooks.json');
  for (const event of ['PreToolUse', 'PostToolUse']) {
    assert.deepEqual(codex.hooks[event], [
      {
        matcher: '^apply_patch$',
        hooks: [{ type: 'command', command: hookCommand, timeout: 5 }],
      },
    ]);
  }
  assert.deepEqual(codex.hooks.Stop, [
    {
      hooks: [{ type: 'command', command: handoffHookCommand, timeout: 30 }],
    },
  ]);

  const cursor = readConfig(path, '.cursor/hooks.json');
  assert.equal(cursor.version, 1);
  for (const event of ['preToolUse', 'postToolUse']) {
    assert.deepEqual(cursor.hooks[event], [
      { command: hookCommand, matcher: '^(Write|Delete)$', timeout: 5 },
    ]);
  }
  assert.deepEqual(cursor.hooks.stop, [
    { command: handoffHookCommand, timeout: 30, loop_limit: null },
  ]);
});

test('preserves existing hooks', (t) => {
  const path = repository(t);
  const codexPath = join(path, '.codex/hooks.json');
  const cursorPath = join(path, '.cursor/hooks.json');
  mkdirSync(dirname(codexPath), { recursive: true });
  mkdirSync(dirname(cursorPath), { recursive: true });
  writeFileSync(
    codexPath,
    JSON.stringify({
      description: 'Existing configuration.',
      hooks: {
        PreToolUse: [
          {
            matcher: '^Bash$',
            hooks: [{ type: 'command', command: './check-bash' }],
          },
        ],
      },
      custom: true,
    }),
  );
  writeFileSync(
    cursorPath,
    JSON.stringify({
      version: 1,
      hooks: {
        beforeShellExecution: [{ command: './audit-shell' }],
        preToolUse: [{ command: './scan-secrets', matcher: '^Write$' }],
      },
    }),
  );

  const result = runInstall(path);

  assert.equal(result.status, 0, result.stderr);
  const codex = readConfig(path, '.codex/hooks.json');
  assert.equal(codex.description, 'Existing configuration.');
  assert.equal(codex.custom, true);
  assert.equal(handlers(codex, 'PreToolUse')[0].command, './check-bash');
  assert.equal(handlers(codex, 'PreToolUse')[1].command, hookCommand);

  const cursor = readConfig(path, '.cursor/hooks.json');
  assert.deepEqual(cursor.hooks.beforeShellExecution, [{ command: './audit-shell' }]);
  assert.equal(cursor.hooks.preToolUse[0].command, './scan-secrets');
  assert.equal(cursor.hooks.preToolUse[1].command, hookCommand);
});

test('reinstall is idempotent', (t) => {
  const path = repository(t);
  assert.equal(runInstall(path).status, 0);
  const codexPath = join(path, '.codex/hooks.json');
  const cursorPath = join(path, '.cursor/hooks.json');
  const firstCodex = readFileSync(codexPath, 'utf8');
  const firstCursor = readFileSync(cursorPath, 'utf8');

  const result = runInstall(path);

  assert.equal(result.status, 0, result.stderr);
  assert.equal(readFileSync(codexPath, 'utf8'), firstCodex);
  assert.equal(readFileSync(cursorPath, 'utf8'), firstCursor);
  const codex = JSON.parse(firstCodex);
  for (const event of ['PreToolUse', 'PostToolUse']) {
    assert.equal(handlers(codex, event).filter((hook) => hook.command === hookCommand).length, 1);
  }
  assert.equal(
    handlers(codex, 'Stop').filter((hook) => hook.command === handoffHookCommand).length,
    1,
  );
  const cursor = JSON.parse(firstCursor);
  for (const event of ['preToolUse', 'postToolUse']) {
    assert.equal(cursor.hooks[event].filter((hook) => hook.command === hookCommand).length, 1);
  }
  assert.equal(
    cursor.hooks.stop.filter((hook) => hook.command === handoffHookCommand).length,
    1,
  );
});

test('migrates the legacy file-size hook', (t) => {
  const path = repository(t);
  const hooksPath = join(path, '.codex/hooks.json');
  const legacyHookPath = join(path, '.codex/hooks/file_size_hint.py');
  mkdirSync(dirname(legacyHookPath), { recursive: true });
  writeFileSync(legacyHookPath, 'legacy hook\n');
  writeFileSync(
    hooksPath,
    JSON.stringify({
      hooks: Object.fromEntries(
        ['PreToolUse', 'PostToolUse'].map((event) => [
          event,
          [
            {
              matcher: '^apply_patch$',
              hooks: [{ type: 'command', command: legacyHookCommand, timeout: 5 }],
            },
          ],
        ]),
      ),
    }),
  );

  const result = runInstall(path);

  assert.equal(result.status, 0, result.stderr);
  assert.throws(() => readFileSync(legacyHookPath));
  const config = readConfig(path, '.codex/hooks.json');
  for (const event of ['PreToolUse', 'PostToolUse']) {
    assert.deepEqual(config.hooks[event], [
      {
        matcher: '^apply_patch$',
        hooks: [{ type: 'command', command: hookCommand, timeout: 5 }],
      },
    ]);
  }
});

test('migrates hooks installed under .codex/hooks/harness', (t) => {
  const path = repository(t);
  const hooksPath = join(path, '.codex/hooks.json');
  const oldFileSizePath = join(path, '.codex/hooks/harness/file_size_hint.py');
  const oldHandoffPath = join(path, '.codex/hooks/harness/handoff.py');
  mkdirSync(dirname(oldFileSizePath), { recursive: true });
  writeFileSync(oldFileSizePath, 'old hook\n');
  writeFileSync(oldHandoffPath, 'old hook\n');
  writeFileSync(
    hooksPath,
    JSON.stringify({
      hooks: {
        PreToolUse: [
          {
            matcher: '^apply_patch$',
            hooks: [{ type: 'command', command: codexOnlyHookCommand, timeout: 5 }],
          },
        ],
        PostToolUse: [
          {
            matcher: '^apply_patch$',
            hooks: [{ type: 'command', command: codexOnlyHookCommand, timeout: 5 }],
          },
        ],
        Stop: [{ hooks: [{ type: 'command', command: codexOnlyHandoffCommand, timeout: 30 }] }],
      },
    }),
  );

  const result = runInstall(path);

  assert.equal(result.status, 0, result.stderr);
  assert.throws(() => readFileSync(oldFileSizePath));
  assert.throws(() => readFileSync(oldHandoffPath));
  const config = readConfig(path, '.codex/hooks.json');
  assert.deepEqual(handlers(config, 'PreToolUse').map((hook) => hook.command), [hookCommand]);
  assert.deepEqual(handlers(config, 'Stop').map((hook) => hook.command), [handoffHookCommand]);
});

test('installs at the Git root when invoked from a subdirectory', (t) => {
  const path = repository(t);
  const subdirectory = join(path, 'src/feature');
  mkdirSync(subdirectory, { recursive: true });

  const result = runInstall(subdirectory);

  assert.equal(result.status, 0, result.stderr);
  assert.match(result.stdout, new RegExp(`Installed @limchihi/harness@${packageVersion} in `));
  assert.equal(readFileSync(join(path, '.codex/hooks.json'), 'utf8').length > 0, true);
  assert.equal(readFileSync(join(path, '.cursor/hooks.json'), 'utf8').length > 0, true);
});

test('fails before writing when a hooks configuration is invalid', (t) => {
  for (const relativePath of ['.codex/hooks.json', '.cursor/hooks.json']) {
    const path = repository(t);
    const hooksPath = join(path, relativePath);
    mkdirSync(dirname(hooksPath), { recursive: true });
    writeFileSync(hooksPath, '{');

    const result = runInstall(path);

    assert.equal(result.status, 1);
    assert.match(result.stderr, /^harness:/);
    assert.throws(() => readFileSync(join(path, fileSizeHookPath)));
    assert.throws(() => readFileSync(join(path, handoffHookPath)));
    assert.equal(readFileSync(hooksPath, 'utf8'), '{');
  }
});
