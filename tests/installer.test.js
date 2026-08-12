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
const hookCommand =
  '/usr/bin/python3 "$(git rev-parse --show-toplevel)/.codex/hooks/harness/file_size_hint.py"';

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

function handlers(config, event) {
  return config.hooks[event].flatMap((group) => group.hooks);
}

test('installs the hook and project configuration', (t) => {
  const path = repository(t);
  const result = runInstall(path);

  assert.equal(result.status, 0, result.stderr);
  assert.match(
    readFileSync(join(path, '.codex/hooks/harness/file_size_hint.py'), 'utf8'),
    /MAX_UNPROMPTED_GROWTH = 30/,
  );
  assert.match(
    readFileSync(join(path, '.agents/skills/imp/SKILL.md'), 'utf8'),
    /run `\/implement`/,
  );
  assert.match(
    readFileSync(join(path, '.agents/skills/imp/scripts/start.py'), 'utf8'),
    /task\/\{issue\}/,
  );
  assert.match(
    readFileSync(join(path, '.agents/skills/imp/agents/openai.yaml'), 'utf8'),
    /allow_implicit_invocation: false/,
  );
  const config = JSON.parse(readFileSync(join(path, '.codex/hooks.json'), 'utf8'));
  for (const event of ['PreToolUse', 'PostToolUse']) {
    assert.deepEqual(config.hooks[event], [
      {
        matcher: '^apply_patch$',
        hooks: [{ type: 'command', command: hookCommand, timeout: 5 }],
      },
    ]);
  }
});

test('preserves existing hooks', (t) => {
  const path = repository(t);
  const hooksPath = join(path, '.codex/hooks.json');
  mkdirSync(dirname(hooksPath), { recursive: true });
  writeFileSync(
    hooksPath,
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

  const result = runInstall(path);

  assert.equal(result.status, 0, result.stderr);
  const config = JSON.parse(readFileSync(hooksPath, 'utf8'));
  assert.equal(config.description, 'Existing configuration.');
  assert.equal(config.custom, true);
  assert.equal(handlers(config, 'PreToolUse')[0].command, './check-bash');
  assert.equal(handlers(config, 'PreToolUse')[1].command, hookCommand);
});

test('reinstall is idempotent', (t) => {
  const path = repository(t);
  assert.equal(runInstall(path).status, 0);
  const hooksPath = join(path, '.codex/hooks.json');
  const first = readFileSync(hooksPath, 'utf8');

  const result = runInstall(path);

  assert.equal(result.status, 0, result.stderr);
  assert.equal(readFileSync(hooksPath, 'utf8'), first);
  const config = JSON.parse(first);
  for (const event of ['PreToolUse', 'PostToolUse']) {
    assert.equal(handlers(config, event).filter((hook) => hook.command === hookCommand).length, 1);
  }
});

test('installs at the Git root when invoked from a subdirectory', (t) => {
  const path = repository(t);
  const subdirectory = join(path, 'src/feature');
  mkdirSync(subdirectory, { recursive: true });

  const result = runInstall(subdirectory);

  assert.equal(result.status, 0, result.stderr);
  assert.match(result.stdout, new RegExp(`Installed @limchihi/harness@${packageVersion} in `));
  assert.equal(readFileSync(join(path, '.codex/hooks.json'), 'utf8').length > 0, true);
});

test('fails before writing when hooks.json is invalid', (t) => {
  const path = repository(t);
  const hooksPath = join(path, '.codex/hooks.json');
  mkdirSync(dirname(hooksPath), { recursive: true });
  writeFileSync(hooksPath, '{');

  const result = runInstall(path);

  assert.equal(result.status, 1);
  assert.match(result.stderr, /^harness:/);
  assert.throws(() => readFileSync(join(path, '.codex/hooks/harness/file_size_hint.py')));
  assert.equal(readFileSync(hooksPath, 'utf8'), '{');
});
