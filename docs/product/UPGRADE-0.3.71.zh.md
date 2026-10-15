# Universal Browser 0.3.71 升级说明

## 修复：双击 open-console.bat 后页面提示 "Failed to fetch"

**现象**：控制台页面打开后一直提示 `Failed to fetch`，黑色窗口里出现
`FileNotFoundError: [Errno 2] No such file or directory: ...minimum-contract.json`。

**原因**：运行时在读取平台能力契约 `fixtures/platform/minimum-contract.json` 时，按
git 仓库目录结构向上查找；完整包 zip 里只有 `runtime/src/browser_skill`，没有 `fixtures/`，
所以 `/api/setup`（环境检查）接口抛出异常，连接被直接断开，前端只能看到 "Failed to fetch"。

**修复**：

- 契约文件随运行时一起打包到 `runtime/src/browser_skill/platform/minimum-contract.json`，
  不再依赖仓库里的 `fixtures/` 目录。
- 控制台任何接口出现未预期异常时，现在返回 JSON 500（页面会显示具体错误原因），并把完整
  堆栈追加到 `runs/console-error.log`，不再让浏览器只看到 "Failed to fetch"。
- 新增组件测试：真实构建完整 zip → 解压到临时目录 → 用独立解释器从解压后的 `runtime/` 启动
  控制台并请求 `/`、`/api/meta`、`/api/setup`、`/api/templates`、`/api/runs`、`/api/doctor`，
  全部必须返回 200 且无 Traceback。

## 安装

下载并解压完整包，双击 `open-console.bat`：

```text
https://github.com/Jacksonhuf/SkillFlow/releases/download/v0.3.71/universal-browser-full-0.3.71.zip
```

若页面仍报错，请把 `runs\console-start.log` 与 `runs\console-error.log` 一起反馈。
