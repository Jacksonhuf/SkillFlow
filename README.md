# Universal Browser Skill — 快速开始

**业务用户三步：** 解压 `universal-browser-full-*.zip` → 双击 `open-console.bat`（macOS / Linux：`open-console.sh`）→ 在网页里点任务、填信息、开始运行。
浏览器驱动自动准备（默认 Playwright 驱动本机 Chrome，无需任何插件），第一次运行在弹出的 Chrome 里登录一次即可。详见 **`docs/QUICKSTART.zh.md`**。

**Agent 内使用：** Hub 上传完整技能包（≤5MB），对话里 `/universal-browser`。构建：`./scripts/build-skill-package.sh --full`。

**IT / 运维：** 引擎、内网镜像、定时任务、chrome-use sidecar 见 **`docs/STANDALONE.zh.md`**；有服务端平台工具时见 `docs/SKILL-HUB.zh.md`。

**本地开发（可选）：** `./scripts/install.sh`

---

# Universal Browser Skill

A platform-native Skill package for **template-driven business data automation** (Acquire → Validate → Report → Deliver). Architecture and roadmap: **`docs/PLATFORM-ARCHITECTURE.zh.md`**.

It installs into an existing Agent platform, uses that platform's chrome-use tool/plugin with the user's signed-in Chrome, treats
downloads as first-class outputs, and reports success only after business-result validation.

It is **not** an Agent platform, standalone chat application, browser automation service, or end-user
CLI. The host platform owns conversation, identity, model access, sessions, file delivery, user
confirmation, and UI rendering.

## Simple install (OpenCode / standard skills)

```bash
./scripts/install.sh              # project: .opencode/skills + .agents/skills
./scripts/install.sh --global     # machine-wide: ~/.config/opencode/skills
browser-skill setup               # same as the skill-directory step after pip install
```

Then in Agent chat: **`/universal-browser`** or ask to list browser task templates.

## Integration outline
