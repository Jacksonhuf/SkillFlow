# Skill Hub 发布与用户指南

面向 **已有 Skill Hub + 自研 Agent（OpenCode 内核）** 的团队。**业务用户不需要 clone 仓库，也不需要 `./scripts/install.sh`。**

---

## 业务用户（零安装）

1. 打开公司 **Skill Hub / 技能市场**。  
2. 搜索并安装：**Universal Browser**（技能 ID：`universal-browser`）。  
3. 在 Agent 对话里输入 **`/universal-browser`** 或「列出浏览器任务」。  
4. 按提示选模板、填变量；需要时在 Chrome 登录，再在 Agent 里继续。

Skill Hub 会把标准 Skill 目录（`SKILL.md` + `references/`）同步到 Agent；**与用户 PC 是否安装 Python 无关**。

---

## 平台管理员（Skill Hub 上架，一次性）

### 方式 A：上传 ZIP（通用）

在 SkillFlow 仓库（仅维护者需要 clone）执行：

```bash
./scripts/build-skill-package.sh
```

产物：

```text
dist/universal-browser-0.1.0.zip
  ├── hub.manifest.json
  └── universal-browser/
        ├── SKILL.md
        ├── references/
        ├── QUICKSTART.zh.md
        └── SKILL-HUB.zh.md
```

把 **`dist/universal-browser-0.1.0.zip`** 上传到内部 Skill Hub（或按 Hub 要求的字段填写 `hub.manifest.json` 中的 id / version / package_dir）。

### 方式 B：Hub 直接拉 Git 目录

若 Hub 支持从 Git 子路径导入，指向：

```text
skill-package/universal-browser/
```

manifest 使用仓库内 `skill-package/hub.manifest.json`。

### 服务器运行时（与 Skill 包分开，一次性）

| 组件 | 装在哪里 | 用户是否要装 |
|------|----------|--------------|
| Skill 指令（SKILL.md） | Skill Hub → Agent | **否** |
| `browser_skill` Python + 模板 | Agent **服务端** / Worker 镜像 | **否** |
| chrome-use | 已有，绑用户 Chrome | **否** |

服务端安装示例（DevOps，非终端用户）：

```bash
pip install /path/to/SkillFlow   # 或内部 PyPI 镜像
# 模板目录与 runs 目录挂载在平台配置中
```

执行层接入见 `examples/opencode_minimal_tool.py`（把 `BrowserSkillApp` 注册为平台工具，与 Hub 里的 Skill 指令配合）。

---

## Hub manifest 字段说明

文件：`skill-package/hub.manifest.json`

| 字段 | 含义 |
|------|------|
| `id` | `universal-browser`，与 SKILL.md frontmatter `name` 一致 |
| `package_dir` | ZIP 内目录名 |
| `slash_command` | 建议 `/universal-browser` |
| `runtime.user_local_install` | `false`，表示不要求用户本机安装 |

若你们 Hub 有自己的 schema，保留 **`id` + `package_dir` + 版本** 映射到上述 ZIP 即可。

---

## 与本地 `install.sh` 的关系

| 场景 | 用法 |
|------|------|
| **公司有 Skill Hub（你的情况）** | 用户只从 Hub 安装；维护者用 `build-skill-package.sh` 上架 |
| 无 Hub、本地 OpenCode 工程 | 可选 `./scripts/install.sh` |

---

## 验收

Hub 安装后，在 Agent 中应能：

- 发现技能 `universal-browser`  
- 加载 `SKILL.md` 全文  
- 在平台已接 `BrowserSkillApp` + chrome-use 时，完成一次模板 Run  

探针：`SkillRequest(action="probe")` 或内部等价健康检查。
