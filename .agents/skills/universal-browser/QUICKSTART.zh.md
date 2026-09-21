# Universal Browser — 怎么用？

## 公司有 Skill Hub（推荐，不用本地安装）

1. 在 **技能市场** 安装 **Universal Browser**（`universal-browser`）。  
2. 在 Agent 里输入 **`/universal-browser`** 或「列出浏览器任务」。  
3. 按提示操作；登录请在 **Chrome** 完成。

详细说明：**[docs/SKILL-HUB.zh.md](SKILL-HUB.zh.md)**（给管理员的上架步骤也在里面）。

---

## 没有 Skill Hub（仅开发/运维）

```bash
git clone https://github.com/Jacksonhuf/SkillFlow.git && cd SkillFlow
./scripts/install.sh
```

然后 `/universal-browser`。

---

## 平台同事

- **上架 Skill：** `./scripts/build-skill-package.sh` → 上传 `dist/universal-browser-0.1.0.zip` 到 Hub  
- **接执行层：** `examples/opencode_minimal_tool.py` + 服务端 `pip install` SkillFlow  

用户永远不需要执行 pip 或 install.sh。
