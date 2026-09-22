# 一键安装 chrome-use（CLI + 扩展桥接）

这不是 Skill Hub 上传包，而是 **Windows 本机一次性环境安装**。

## 能一键做什么 / 不能做什么

| 步骤 | 一键脚本 | 说明 |
|------|----------|------|
| 安装 **chrome-use.exe** | ✅ | 复制到 `%LOCALAPPDATA%\UniversalBrowser\chrome-use\` 并加入用户 PATH |
| 注册 **native bridge** | ✅ | 执行 `chrome-use extension install` |
| 安装 **Chrome 扩展** | ⚠️ 半自动 | 脚本会打开 Chrome 网上应用店；用户需点一次 **「添加至 Chrome」**（Google 不允许普通 exe 静默装扩展） |
| 自检 | ✅ | 可选 `chrome-use doctor` |

企业环境若已用 **Chrome 组策略** 强制安装扩展 ID `knfcmbamhjmaonkfnjhldjedeobeafmk`，可跳过商店步骤。

## 准备文件

1. 下载 Sidecar（含 `chrome-use.exe`）：  
   `universal-browser-chrome-use-sidecar-*.zip`
2. 解压后得到 `universal-browser/vendor/chrome-use/chrome-use.exe`
3. 将 **`scripts/windows/`** 与 **`vendor/chrome-use/`** 放在同一层级，例如：

```text
chrome-use-installer/
├── install-chrome-use-stack.bat
├── Install-ChromeUseStack.ps1
└── vendor/
    └── chrome-use/
        └── chrome-use.exe
```

或运行仓库构建产物 **`universal-browser-chrome-use-installer-*.zip`**（见下）。

## 使用

双击 **`install-chrome-use-stack.bat`**，或在 PowerShell：

```powershell
.\Install-ChromeUseStack.ps1
```

参数：

- `-SkipExtensionPage` — 不打开 Web Store（扩展已装时）
- `-SkipDoctor` — 跳过 doctor

## 与 Skill 的关系

- **Skill 包**（≤5MB）：仍只上传 `universal-browser-full-*.zip` 到 Hub  
- **本安装器**：每台 Windows 运维/用户 **装一次** CLI+桥接；Skill 里的 `invoke.py` 会自动找到 PATH 上的 `chrome-use` 或 `CHROME_USE_BIN`
