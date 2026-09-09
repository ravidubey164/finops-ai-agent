# finops-ai-agent

Companion repository for the blog post “How to build a custom AI agent with GitHub Copilot.”

It demonstrates a read-only Azure FinOps agent composed of:

- [AGENTS.md](AGENTS.md): repository-wide safety rules.
- [.github/agents/finops-analyst.agent.md](.github/agents/finops-analyst.agent.md): the custom VS Code agent and its allowed tools.
- [.github/skills/](.github/skills/): reusable investigation workflows.
- [scripts/azure_read.py](scripts/azure_read.py): the read-only Azure CLI wrapper.
- [.github/hooks/block-azure-writes.json](.github/hooks/block-azure-writes.json): a best-effort guard against unapproved `az` commands.

The wrapper uses only the Python standard library and the Azure CLI. Authenticate with `az login`,
then run it from the repository root:

```bash
python3 scripts/azure_read.py subscriptions --out working/subscriptions.json
```

Results and local credentials are ignored by Git. The wrapper is a behavioural guardrail, not an
Azure permission boundary: use a read-only identity whenever possible.
