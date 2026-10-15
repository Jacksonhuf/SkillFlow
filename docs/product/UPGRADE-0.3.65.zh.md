# Universal Browser 0.3.65 升级说明

## 草稿模板 Webhook 分发

- 新增 **`update_delivery`** 动作：在未发布（`draft` / `testing`）版本上修改或关闭 Webhook 分发。
- 控制台运行面板可对当前草稿填写 URL、轮换密钥或关闭分发；密钥留空时保留已保存值。
- `delivery_spec_from_webhook` 供 Teach 编译与运行时更新共用，行为一致。

## 安装

```text
https://github.com/Jacksonhuf/SkillFlow/releases/download/v0.3.65/universal-browser-full-0.3.65.zip
```
