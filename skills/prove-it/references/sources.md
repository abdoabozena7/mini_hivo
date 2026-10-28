# Compatibility references

Checked 28 October 2026. These sources describe host features; they do not certify
this bundle. Installation schemas may change. Verify against the installed client.

- GitHub: adding skills and supported project/personal locations:
  https://docs.github.com/en/copilot/how-tos/copilot-on-github/customize-copilot/customize-cloud-agent/add-skills
- GitHub CLI: skill reload, discovery and explicit invocation:
  https://docs.github.com/en/copilot/how-tos/copilot-cli/customize-copilot/add-skills
- GitHub: hook availability and surface-specific limitations:
  https://docs.github.com/en/copilot/concepts/customizations/hooks
- GitHub: agentStop, command configuration, input/output and continuation caps:
  https://docs.github.com/en/copilot/reference/hooks-reference
- OpenAI: local skills and Codex discovery locations:
  https://learn.chatgpt.com/docs/build-skills
- Anthropic: Claude Code Stop hooks and configuration:
  https://code.claude.com/docs/en/hooks
- Playwright Python: installation and browser dependencies:
  https://playwright.dev/python/docs/intro

Do not copy host-specific commands between agents without checking their schema.
This package supplies native stop-hook adapters only for Copilot and Claude.
Codex/generic users receive portable instructions and a manually/externally
invoked evidence gate, not an invented universal stop hook.
