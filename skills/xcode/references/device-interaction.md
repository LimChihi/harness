# Device interaction

Xcode supplies the `device-interaction` skill through its supported export command.
Export it from the selected installation into a task-specific temporary directory:

```sh
xcode_skill_export=$(mktemp -d)
xcrun agent skills export "$xcode_skill_export/skills"
```

Read `$xcode_skill_export/skills/device-interaction/SKILL.md`. It owns the
interaction syntax and verification workflow. Resolve tool names and argument
fields through this CLI's `list` and `describe`; the exported skill's examples
can use names from another interface.

Start the required session according to its current tool contract. Give the
interaction subagent the returned session key, this CLI's absolute path, the
exported skill's absolute path, and a concrete verification task. The subagent
reads that skill independently before interacting and reports its observations
with the screenshot and hierarchy paths.

After the subagent finishes, end the session created for this task using its
returned key, then remove the task's export directory.
