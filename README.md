# Claude Auto-Dev

> 🚀 Hybrid Multi-Agent Development Orchestrator for Claude Code

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![Claude Code](https://img.shields.io/badge/Claude%20Code-2.0+-blue)](https://claude.ai/code)
[![Claude Flow](https://img.shields.io/badge/Claude%20Flow-v3.1.0-green)](https://github.com/ruvnet/claude-flow)

---

## 🎯 What is Claude Auto-Dev?

Claude Auto-Dev is an **autonomous multi-agent development system** that transforms natural language task descriptions into production-ready code with quality guarantees.

It combines:
- **Claude-Flow v3** — Q-Learning routing, model selection, HNSW memory
- **Custom Quality Gates** — Security, Visual QA, human checkpoints
- **Existing Claude Code plugins** — 25+ specialized agents

```
/auto-dev "Add OAuth authentication to the FastAPI backend"

[ROUTING] → feature workflow, fastapi-pro agent, sonnet model
[DISCOVER] → Found auth/ module, existing patterns
[PLAN] → 4 tasks created
  ⭐ Approve? [Yes]
[BUILD] → OAuth service, endpoints, middleware created
[TEST] → 12/12 passing, 91% coverage
[REVIEW] → OK
[SECURITY] → OK
[DEPLOY] →
  ⭐ Action? [Create PR]

✅ PR created: https://github.com/user/repo/pull/42
```

---

## ✨ Key Features

| Feature | Description |
|---------|-------------|
| **8-Phase Pipeline** | Discover → Plan → Build → Test → Review → Security → Visual QA → Deploy |
| **Smart Routing** | Q-Learning agent selection (87% accuracy) |
| **Model Optimization** | Auto-select Haiku/Sonnet/Opus (up to 80% cost savings) |
| **Quality Gates** | Automatic retry with escalation |
| **Security Phase** | Mandatory OWASP checks, secrets detection |
| **Visual QA** | Screenshot comparison, accessibility audit |
| **Human Checkpoints** | Plan approval, deploy approval |
| **Pattern Learning** | HNSW vector search (28ms) |

---

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                    HYBRID ORCHESTRATOR                               │
├─────────────────────────────────────────────────────────────────────┤
│                                                                       │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │                   CLAUDE-FLOW LAYER                          │    │
│  │  • Q-Learning routing (hooks_route)                          │    │
│  │  • Model selection (hooks_model-route)                       │    │
│  │  • HNSW memory search (memory_search) — 28ms                 │    │
│  │  • Learning (hooks_pre/post-task)                            │    │
│  └─────────────────────────────────────────────────────────────┘    │
│                             │                                         │
│                             ▼                                         │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │                   QUALITY GATES LAYER                        │    │
│  │  • Test coverage ≥ 80%                                       │    │
│  │  • Code review (no critical/high)                            │    │
│  │  • Security audit (no vulnerabilities)                       │    │
│  │  • Visual QA (no regressions)                                │    │
│  │  • Human checkpoints (plan, deploy)                          │    │
│  └─────────────────────────────────────────────────────────────┘    │
│                                                                       │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 📦 Installation

### Prerequisites

- [Claude Code](https://claude.ai/code) 2.0+
- Node.js 20+
- [Claude-Flow](https://github.com/ruvnet/claude-flow) v3.1.0+

### Quick Install

```bash
# 1. Install Claude-Flow
npm install -g claude-flow@alpha

# 2. Add MCP server
claude mcp add claude-flow -- npx -y claude-flow@alpha mcp start

# 3. Copy the skill
cp skills/auto-dev.md ~/.claude/commands/

# 4. Initialize Claude-Flow in your project
cd your-project
claude-flow init
claude-flow memory init --force
claude-flow hooks pretrain

# 5. Done! Use the skill
/auto-dev "your task description"
```

### Manual Installation

1. Clone this repository:
   ```bash
   git clone https://github.com/aptyp78/claude-auto-dev.git
   ```

2. Copy skill to Claude Code commands:
   ```bash
   cp claude-auto-dev/skills/auto-dev.md ~/.claude/commands/
   ```

3. Follow Claude-Flow setup in [docs/SETUP.md](docs/SETUP.md)

---

## 🔄 Workflow Phases

### Phase 0: Smart Routing (Claude-Flow)

```bash
claude-flow hooks route --task "Add PDF export"
# → Agent: fastapi-pro (85% confidence)

claude-flow hooks model-route --task "Code review"
# → Model: sonnet (80% cost savings vs opus)
```

### Phase 1-2: Discover & Plan

- Explore codebase with specialized agents
- Load relevant patterns from memory
- Create task list with dependencies
- **⭐ Human approval required**

### Phase 3-4: Build & Test

- Execute tasks with routed agents
- Parallel execution for independent tasks
- Automatic test generation
- **Gate: coverage ≥ 80%**

### Phase 5-6: Review & Security

- Code review (code-reviewer, silent-failure-hunter)
- Security audit (OWASP, secrets, dependencies)
- **Gate: no critical/high issues**

### Phase 7-8: Visual QA & Deploy

- Screenshot comparison (if frontend)
- Accessibility audit
- **⭐ Human approval for deploy**
- Create PR or deploy

---

## 📊 Quality Gates

| Phase | Gate | Criteria | Retry |
|-------|------|----------|-------|
| 4 | Tests Passing | All pass, coverage ≥ 80% | 5 |
| 5 | Review Passed | No critical/high issues | 3 |
| 6 | Security Cleared | No vulnerabilities | 3 |
| 7 | Visual QA Passed | No regressions | 2 |

### Retry Logic

```
[FAILURE] → debugger agent → fix → retest → [SUCCESS or RETRY]
                                         ↓
                              [MAX RETRIES] → escalate to human
```

---

## 🤖 Integrated Agents

| Category | Agents |
|----------|--------|
| **Discovery** | Explore, Plan |
| **Backend** | backend-architect, fastapi-pro, django-pro |
| **Frontend** | frontend-developer, web-dev |
| **Testing** | test-automator, debugger |
| **Review** | code-reviewer, silent-failure-hunter, type-design-analyzer |
| **Security** | security-auditor |
| **Deploy** | deployment-engineer |

---

## ⚙️ Configuration

### Global Config

`~/.claude/orchestrator.yaml`:

```yaml
orchestrator:
  version: "1.0"

  hybrid:
    claude_flow:
      routing: true
      model_selection: true
      learning: true
      memory: true
    custom:
      security_phase: true
      visual_qa_phase: true
      human_checkpoints: true

  gates:
    test_coverage: 80
    max_retries: 5

  checkpoints:
    plan_approval: required
    deploy_approval: required
```

### Project Config

`your-project/.claude-flow/config.yaml`:

```yaml
orchestrator:
  skip_phases:
    - visual_qa  # No frontend
  coverage_threshold: 90  # Higher for this project
```

---

## 📈 Performance

| Metric | Value |
|--------|-------|
| Routing latency | 0.7ms |
| Memory search | 28ms |
| Model routing | 80% cost savings |
| Routing accuracy | 87% |
| Test success rate | 94% |

---

## 🆚 Comparison with Alternatives

| Feature | Auto-Dev | claude-flow | claude-sub-agent | Devin |
|---------|----------|-------------|------------------|-------|
| Security Phase | ✅ Mandatory | ⚠️ Optional | ❌ | ❌ |
| Visual QA | ✅ MCP | ❌ | ❌ | ✅ |
| Human Checkpoints | ✅ 2 points | ⚠️ Ad-hoc | ❌ | ❌ |
| Q-Learning Routing | ✅ | ✅ | ❌ | ? |
| Setup Complexity | Low | High | Medium | N/A |
| Open Source | ✅ | ✅ | ✅ | ❌ |

---

## 📚 Documentation

- [Full Specification](docs/AGENT_ORCHESTRATOR_SPEC.md)
- [Competitive Analysis](docs/COMPETITIVE_ANALYSIS.md)
- [Hybrid Integration Plan](docs/HYBRID_INTEGRATION_PLAN.md)
- [Setup Guide](docs/SETUP.md)

---

## 🛠️ Development

### Testing the Skill

```bash
# Simple test
/auto-dev "Add a hello world endpoint"

# Feature test
/auto-dev "Add user authentication with JWT"

# Bugfix test
/auto-dev "Fix: users can't login after password change"
```

### Contributing

1. Fork the repository
2. Create your feature branch
3. Run tests
4. Submit a pull request

---

## 📄 License

MIT License — see [LICENSE](LICENSE)

---

## 🙏 Acknowledgments

- [Claude-Flow](https://github.com/ruvnet/claude-flow) — Enterprise AI orchestration
- [Claude Code](https://claude.ai/code) — The foundation
- [Anthropic](https://anthropic.com) — For Claude

---

## 📞 Support

- Issues: [GitHub Issues](https://github.com/aptyp78/claude-auto-dev/issues)
- Discussions: [GitHub Discussions](https://github.com/aptyp78/claude-auto-dev/discussions)

---

*Built with ❤️ for autonomous development*
