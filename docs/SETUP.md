# Claude Auto-Dev: Detailed Setup Guide

> Пошаговая инструкция по установке и настройке

---

## 📋 Prerequisites

### Required
- **Claude Code** 2.0+ — [Download](https://claude.ai/code)
- **Node.js** 20+ — `node --version`
- **npm** 10+ — `npm --version`

### Optional (for full features)
- **Git** — для деплоя через PR
- **GitHub CLI** (`gh`) — для создания PR

---

## 🚀 Installation Steps

### Step 1: Install Claude-Flow

```bash
# Global installation
npm install -g claude-flow@alpha

# Verify installation
claude-flow --version
# Expected: v3.1.0 or higher
```

### Step 2: Add MCP Server

```bash
# Add claude-flow as MCP server
claude mcp add claude-flow -- npx -y claude-flow@alpha mcp start

# Verify
claude mcp list
# Should see: claude-flow
```

### Step 3: Copy the Skill

```bash
# Create commands directory if needed
mkdir -p ~/.claude/commands

# Copy skill file
cp skills/auto-dev.md ~/.claude/commands/

# Verify
ls ~/.claude/commands/auto-dev.md
```

### Step 4: Initialize Claude-Flow in Your Project

```bash
# Navigate to your project
cd your-project

# Initialize
claude-flow init

# Initialize memory (vector search)
claude-flow memory init --force

# Pretrain routing model
claude-flow hooks pretrain
```

### Step 5: Verify Setup

```bash
# Test routing
claude-flow hooks route --task "Add authentication"
# Expected: workflow, agent, confidence

# Test model routing
claude-flow hooks model-route --task "Simple fix"
# Expected: model recommendation

# Test memory
claude-flow memory search --query "authentication patterns"
# Expected: search results (may be empty initially)
```

---

## ⚙️ Configuration

### Global Configuration

Create `~/.claude/orchestrator.yaml`:

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

### Project Configuration

Create `your-project/.claude-flow/config.yaml`:

```yaml
orchestrator:
  skip_phases:
    - visual_qa  # Skip if no frontend
  coverage_threshold: 90  # Override for this project
```

---

## 🔧 Troubleshooting

### Problem: "Cannot find package 'sql.js'"

```bash
# Reinstall claude-flow globally
npm install -g claude-flow@alpha

# Reinitialize memory
claude-flow memory init --force
```

### Problem: "file is not a database"

```bash
# Reinitialize
claude-flow init --force
claude-flow memory init --force
```

### Problem: MCP server not responding

```bash
# Check server status
claude mcp list

# Remove and re-add
claude mcp remove claude-flow
claude mcp add claude-flow -- npx -y claude-flow@alpha mcp start
```

### Problem: Routing returns low confidence

```bash
# Retrain the model
claude-flow hooks pretrain

# Check metrics
claude-flow hooks metrics
```

---

## 🧪 Testing Your Setup

### Quick Test

```bash
# In Claude Code:
/auto-dev "Add a hello world endpoint to the API"
```

Expected flow:
1. ROUTING → Determines workflow type
2. DISCOVER → Analyzes codebase
3. PLAN → Creates task list
4. **⭐ Human Approval**
5. BUILD → Implements
6. TEST → Runs tests
7. REVIEW → Code review
8. SECURITY → Security check
9. DEPLOY → **⭐ Human Approval**

### Feature Test

```bash
/auto-dev "Add user authentication with JWT"
```

### Bugfix Test

```bash
/auto-dev "Fix: users can't login after password change"
```

---

## 📊 Performance Expectations

| Metric | Expected Value |
|--------|---------------|
| Routing latency | < 1ms |
| Memory search | < 30ms |
| Routing accuracy | > 85% |
| Model cost savings | 60-80% |

---

## 🔗 Related Documentation

- [Full Specification](AGENT_ORCHESTRATOR_SPEC.md)
- [Competitive Analysis](COMPETITIVE_ANALYSIS.md)
- [Hybrid Integration Plan](HYBRID_INTEGRATION_PLAN.md)
- [Claude-Flow Documentation](https://github.com/ruvnet/claude-flow)

---

*Need help? Open an issue on GitHub!*
