# Claude Code Agent 隔离开发环境（Lima VM 方案）

把 Claude Code CLI 及所有开发/测试活动放进一个本地 Lima VM，宿主机只保留数据库服务与存储。agent 的 Bash/Read/Write/MCP 调用全部落在 VM 内，**宿主机文件系统除挂载目录外完全不可见**。

---

## 1. 为什么需要这个方案

### 1.1 问题背景

AI Agent（Claude Code、Gemini、Codex 等）在日常使用中有三个已观察到的风险/摩擦：

1. **agent 偏好一次性脚本**：训练先验让 LLM 倾向用 `python -c "..."`、`bash -c "..."`、`source xxx`、heredoc 来探测代码行为；这类命令在 zsh 下会触发人工授权弹窗，打断工作流
2. **工具层沙箱管不住子进程**：Claude Code 的 `dangerouslyDisableSandbox` 只约束工具进程本身，`python tmp/probe.py` 子进程以当前 macOS 用户身份执行，能做 `rm -rf ~/`、读 `~/.ssh/id_rsa`、访问 Keychain 等任何宿主机资源
3. **软约束（CLAUDE.md / permissions.deny）不可靠**：memory 对 sub-agent 不继承；skill 模板里没强制；permissions 的 deny 规则覆盖不全时仍可绕过

### 1.2 真正的隔离边界

有效的 agent 隔离只能来自三个层面：

| 层级 | 机制 | 本方案 |
|---|---|---|
| 进程身份 | OS 权限 / 容器 / 独立用户 / VM | **✅ VM**（独立 Linux 用户 + 独立 kernel 视图） |
| 文件系统 | 挂载粒度 | ✅ 显式 virtiofs，敏感目录不挂 |
| 网络 | namespace / 防火墙 | ⚠️ 默认允许出站（Claude API 需要），DB 限 Lima 子网 |

---

## 2. 架构选型

### 2.1 两种候选

**方案 A：Claude Code 在 VM 内（本方案）**
```
┌─ macOS ─────────────────────┐
│  Postgres / Redis           │  ← 只跑数据服务
│                             │
│  ┌─ Ubuntu VM ──────────┐   │
│  │ claude (CLI)         │   │  ← agent 在这里
│  │ pytest / node / py   │   │  ← 测试也在这里
│  │ log-mcp / postgres-mcp│  │  ← MCP server 在这里
│  │                      │   │
│  │ 挂载: ~/Desktop/code │   │
│  │       ~/.claude      │   │
│  │       ~/.lima-cache  │   │
│  └──────────────────────┘   │
└─────────────────────────────┘
```

**方案 B：Claude Code 在 macOS + Lima MCP 沙箱转发**
- Claude Code 跑在宿主机，通过 `limactl mcp serve` 把文件与 shell 操作转发进 VM
- 需要 `permissions.deny` 禁用所有内置 `Bash/Read/Write/Edit/Grep/Glob`
- **隔离靠软约束**，任何 deny 漏项或 skill 自带工具都会破坏隔离

### 2.2 选方案 A 的理由

| 维度 | 方案 A | 方案 B |
|---|---|---|
| 隔离机制 | **物理**（agent 进程在 VM 内） | 软约束（靠 permissions） |
| UI 体验 | `limactl shell` + tmux 或 VS Code Remote-SSH | macOS 原生 |
| 认证 | VM 内 `claude login` 或挂载 `~/.claude` | 宿主机 token 直接复用 |
| MCP server 位置 | 必须在 VM 内 | 可灵活 |
| 混用风险 | 无 | 高（内置工具漏掉即破） |

**隔离可靠性优于便利性**。方案 A 的 UI 摩擦通过 VS Code Remote-SSH 可消除。

---

## 3. Lima VM 配置

### 3.1 前置条件

```
macOS >= 14（支持 vz + virtiofs）
Apple Silicon
Lima >= 2.0（limactl mcp 插件要求）
  brew install lima
```

### 3.2 `~/claude-agent.yaml`

```yaml
images:
  - location: "https://cloud-images.ubuntu.com/releases/24.04/release/ubuntu-24.04-server-cloudimg-arm64.img"
    arch: "aarch64"

vmType: "vz"
mountType: "virtiofs"

cpus: 4
memory: "8GiB"
disk: "40GiB"

mounts:
  # 1. 代码根
  - location: "~/Desktop/code"
    writable: true
  # 2. Agent 状态（token / memory / plans / skills / projects/*.jsonl）
  - location: "~/.claude"
    writable: true
  # 3. 包管理器共享缓存（加速 VM 重建）
  - location: "~/.lima-cache"
    writable: true
    mountPoint: "/home/<VM_USER>/.cache"   # VM_USER 通常为 <macos_user>.linux

hostResolver:
  enabled: true
  ipv6: false

provision:
  # 系统基础
  - mode: system
    script: |
      #!/bin/bash
      set -eux
      apt-get update
      DEBIAN_FRONTEND=noninteractive apt-get install -y \
        curl git jq build-essential ca-certificates \
        python3 python3-pip python3-venv pipx \
        ripgrep fd-find tmux vim less htop direnv httpie \
        postgresql-client redis-tools
      # yq
      curl -fsSL https://github.com/mikefarah/yq/releases/latest/download/yq_linux_arm64 \
        -o /usr/local/bin/yq && chmod +x /usr/local/bin/yq
      # GitHub CLI
      curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
        | dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg
      echo "deb [arch=arm64 signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] \
        https://cli.github.com/packages stable main" \
        > /etc/apt/sources.list.d/github-cli.list
      apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y gh
      # gitleaks
      curl -fsSL https://github.com/gitleaks/gitleaks/releases/latest/download/gitleaks_linux_arm64.tar.gz \
        | tar -xz -C /usr/local/bin gitleaks
      # Node.js 20 LTS
      curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
      DEBIAN_FRONTEND=noninteractive apt-get install -y nodejs

  # 用户层
  - mode: user
    script: |
      #!/bin/bash
      set -eux
      sudo npm install -g @anthropic-ai/claude-code
      sudo npm install -g @modelcontextprotocol/server-postgres
      # Python 现代工具链
      curl -LsSf https://astral.sh/uv/install.sh | sh
      # Node 现代包管理器
      curl -fsSL https://get.pnpm.io/install.sh | sh -
      # pipx 常用 CLI
      pipx install ruff
      pipx install pre-commit
      # 缓存目录环境变量
      cat >> ~/.bashrc <<'EOF'
      export PIP_CACHE_DIR="$HOME/.cache/pip"
      export UV_CACHE_DIR="$HOME/.cache/uv"
      export NPM_CONFIG_CACHE="$HOME/.cache/npm"
      eval "$(direnv hook bash)"
EOF
      pnpm config set store-dir "$HOME/.cache/pnpm-store" || true

message: |
  VM 已就绪。
    limactl shell claude-agent   进入 VM
    cd ~/Desktop/code/log-mcp
    claude                        启动 Claude Code CLI
  访问宿主机数据库：
    psql      -h host.lima.internal -U <user> -d <db>
    redis-cli -h host.lima.internal -p 6379
```

### 3.3 首次创建

```bash
mkdir -p ~/.lima-cache
limactl create --name=claude-agent ~/claude-agent.yaml
limactl start  claude-agent                # 首次约 5~10 分钟（下镜像 + provision）
```

---

## 4. 宿主机数据库配置

让 Postgres/Redis 只监听 Lima 子网，**不要监听 `0.0.0.0`**（会暴露到 Wi-Fi 网卡）。

### 4.1 找 Lima 子网网关 IP

VM 启动后，macOS 上会出现 `bridge10x` 接口：

```bash
ifconfig | grep -A 3 'bridge1' | grep 'inet '
# 示例：inet 192.168.105.1 netmask 0xffffff00 broadcast 192.168.105.255
```

### 4.2 Postgres（brew `postgresql@16`）

编辑 `/opt/homebrew/var/postgresql@16/postgresql.conf`：
```
listen_addresses = 'localhost,192.168.105.1'
```

编辑 `/opt/homebrew/var/postgresql@16/pg_hba.conf`：
```
host    all    all    192.168.105.0/24    scram-sha-256
```

重启：
```bash
brew services restart postgresql@16
lsof -i :5432    # 验证只监听 127.0.0.1 和 192.168.105.1
```

### 4.3 Redis

编辑 `/opt/homebrew/etc/redis.conf`：
```
bind 127.0.0.1 192.168.105.1
protected-mode yes
# requirepass <strong-pass>   # 可选
```
```bash
brew services restart redis
```

### 4.4 在 VM 里连接

工程配置 / MCP server / 脚本里把 `localhost` 换成 `host.lima.internal`：
```
postgres://user:pass@host.lima.internal:5432/mydb
redis://host.lima.internal:6379/0
```

Lima 的 `hostResolver` 会把 `host.lima.internal` 解析到上述子网 IP。

---

## 5. 工具链分层

按用途分 6 层，yaml provision 已覆盖"必装"项。

### 5.1 语言工具链（必装）

| 工具 | 作用 |
|---|---|
| `uv` | Python 包/环境管理，替代 pip + venv + pip-tools |
| `pipx` | 隔离安装 Python CLI |
| `pnpm` | Node 包管理，替代 npm |

### 5.2 代码质量（必装）

| 工具 | 作用 |
|---|---|
| `ruff` | Python lint + format + import 排序 |
| `pre-commit` | 钩子统一入口 |
| `prettier` / `eslint` | 工程级安装，不全局 |

### 5.3 Git 生态（必装）

| 工具 | 作用 |
|---|---|
| `git` | — |
| `gh` | GitHub CLI（PR / issue / review） |
| `gitleaks` | 提交前 secret 扫描 |

### 5.4 MCP Server（按需）

| MCP | 安装 | 连接 |
|---|---|---|
| `log-mcp` | `uv pip install -e ~/Desktop/code/log-mcp` | stdio |
| postgres MCP | `npm i -g @modelcontextprotocol/server-postgres` | `host.lima.internal:5432` |
| redis MCP | 第三方包 | `host.lima.internal:6379` |
| github MCP | 与 `gh` 功能重叠，择一 | — |
| **不装** filesystem MCP | 与 Claude Code 内置 Read/Write 重叠 | — |

### 5.5 Shell / 运维（必装）

| 工具 | 作用 |
|---|---|
| `tmux` | agent 后台长任务 |
| `direnv` | 工程级环境变量隔离 |
| `jq` / `yq` | JSON / YAML |
| `httpie` | 可读性好的 HTTP 客户端 |
| `htop` | 资源监控 |
| `dig` / `nc` | 网络诊断 |

### 5.6 治理（配置）

- `~/.claude/settings.json` 的 `permissions.allow` / `deny`
- `.claude/settings.local.json` 的 `hooks`
- 工程 `CLAUDE.md` 硬约束（禁止内联 shell 等）

### 5.7 明确不装

| 工具 | 原因 |
|---|---|
| `docker` / `containerd` | VM 套 VM 过重；如需容器用宿主 OrbStack |
| `kubectl` / `k9s` | 无 K8s 集群时是死重量 |
| `nodemon` / `pm2` 全局 | 工程内 devDependencies |
| GUI / X server / DE | VM 无图形需求 |

---

## 6. 数据与挂载策略

| 层 | 示例 | 策略 |
|---|---|---|
| 1. 代码 | `~/Desktop/code/*` | ✅ 挂 virtiofs |
| 2. Agent 状态 | `~/.claude/*` | ✅ 挂 virtiofs |
| 3. 工程内构建产物 | `node_modules/` `.venv/` `__pycache__/` | ⚠️ 随代码走 virtiofs；性能可接受 |
| 4. 包管理器缓存 | `~/.cache/{pip,uv,npm,pnpm}` | ✅ 映射到宿主 `~/.lima-cache` |
| 5. VM 内配置 | `~/.bashrc` `~/.ssh/` `~/.config/gh` `~/.gitconfig` | ❌ VM 独立；销毁即销毁 |
| 6. 系统包 | `/usr/` `/etc/` | ❌ provision 重建 |
| 7. 宿主机 DB 数据 | `/opt/homebrew/var/postgresql@16/` | ❌ 不挂；VM 走网络访问 |

### 6.1 为什么工程内构建产物不单独分离

符号链接/环境变量改路径引入复杂度；virtiofs 在 Apple Silicon 实测性能接受。保持"工程目录整块挂载"最简。

### 6.2 为什么缓存要单独挂

`limactl delete` → `limactl start` 是日常操作。缓存随 VM 销毁意味着每次重建要重下载数 GB。单独挂 `~/.lima-cache` 让缓存与 VM 生命周期解耦。

### 6.3 `~/.claude.json` 处理

Lima 不能挂单文件。VM 里首次 `claude` 会自动生成；登录信息已在挂载的 `~/.claude/` 里，通常无需同步这个文件。真要同步用 `limactl cp ~/.claude.json claude-agent:~`。

---

## 7. 安全要点

### 7.1 SSH key

**不挂载 `~/.ssh`**。VM 内独立生成：
```bash
ssh-keygen -t ed25519 -f ~/.ssh/id_ed25519
# 公钥加到 GitHub 作为第二把
```

### 7.2 不做的挂载

| ❌ | 原因 |
|---|---|
| `~/.ssh` | 等于放弃隔离 |
| `~/Library` / `~/` | 敏感暴露 + virtiofs 性能崩 |
| DB 数据目录 | 双进程写可能损坏；一律走网络 |
| `~/.gitconfig` | VM 独立身份更干净 |

### 7.3 DB 监听

- ❌ `listen_addresses = '*'`
- ✅ `listen_addresses = 'localhost,192.168.105.1'`

### 7.4 `~/.claude` 是挂载目录

Claude Code 的 auth token 在挂载目录里，意味着 VM 内的 agent 可读。这是"便利换隔离"的折中。若担心 VM 被攻陷时 token 泄露：
- VM 内独立 `claude login`，**不挂载** `~/.claude`
- 代价：mem ory / plans / skills 每 VM 独立

---

## 8. 日常命令

```bash
# 启停
limactl start  claude-agent
limactl stop   claude-agent
limactl shell  claude-agent          # 进入 VM
limactl shell claude-agent -- bash -c 'cmd'   # 单条命令

# 重置（保留 ~/.claude 与代码，仅重建 VM）
limactl delete claude-agent -f
limactl start  --name=claude-agent ~/claude-agent.yaml

# 在 VM 里
cd ~/Desktop/code/log-mcp
claude                               # 启动 Claude Code CLI
pytest                               # 运行测试
psql -h host.lima.internal -U alpha  # 连宿主 DB
```

---

## 9. VS Code Remote-SSH 接入

```bash
limactl show-ssh --format=config claude-agent >> ~/.ssh/config
```

VS Code → Remote-SSH → `lima-claude-agent` → 打开 `/Users/alpha/Desktop/code/log-mcp`。终端、Extension、调试器全在 VM 里跑，文件在 virtiofs 上，体验接近本地开发。

---

## 10. 验证清单

VM 启动并进入后：

```bash
# 基础工具
which uv pnpm ruff gh direnv gitleaks httpie yq tmux

# Claude Code
claude --version

# 网络：连宿主 DB
nc -zv host.lima.internal 5432
nc -zv host.lima.internal 6379

# 挂载：代码可读写、agent 状态同步
ls ~/Desktop/code/log-mcp
ls ~/.claude
touch ~/.cache/test-write && rm ~/.cache/test-write

# 隔离验证（应报错 / 不存在）
ls ~/.ssh 2>&1                       # VM 独立 ~/.ssh（仅包含自己生成的 key）
ls /Users/alpha/Library 2>&1         # 应不存在
```

---

## 11. 维护

| 场景 | 命令 |
|---|---|
| 升级 Claude Code CLI | VM 内 `sudo npm update -g @anthropic-ai/claude-code` |
| 升级系统包 | VM 内 `sudo apt update && sudo apt upgrade` |
| 彻底重置 VM | `limactl delete claude-agent -f && limactl start --name=claude-agent ~/claude-agent.yaml` |
| 查 VM 磁盘 | `du -sh ~/.lima/claude-agent/` |
| 快照备份 | `cp -c ~/.lima/claude-agent/diffdisk ~/.lima/claude-agent/diffdisk.snap`（APFS 克隆） |
