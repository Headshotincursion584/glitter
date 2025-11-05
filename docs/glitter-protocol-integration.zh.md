# Glitter 协议接入与复用指南

本文档面向希望与 Glitter CLI 共用局域网发现与文件传输协议的外部程序，整理核心要点与推荐集成步骤。示例与字段名基于当前 `main` 分支实现（`glitter/discovery.py`、`glitter/transfer.py`）。

## 1. 概览
- UDP 广播端口：`45845`（默认）
- TCP 传输端口：默认 `45846`，可配置
- 传输握手协议版本：`PROTOCOL_VERSION = 2`
- 数据编码：JSON 报文均使用 UTF-8，文件数据按原始二进制流发送
- 加密：可选（默认启用），使用 Diffie-Hellman 推导密钥 + 自定义流加密(`StreamCipher`)

## 2. 局域网发现（UDP Presence）

### 2.1 周期与线程
- Beacon 周期：`BEACON_INTERVAL = 2.5` 秒，对广播地址 `255.255.255.255` 发送 Presence 报文
- Peer 过期时间：`PEER_TIMEOUT = 7.5` 秒，需定期清理超时节点
- Reply 冷却：`REPLY_COOLDOWN = 5` 秒，相同对等节点在间隔内只回应一次

### 2.2 Presence 报文结构
```json
{
  "type": "presence",
  "peer_id": "<唯一标识>",
  "name": "<设备名>",
  "language": "<语言代码>",
  "transfer_port": 45846,
  "timestamp": 1700000000.0,
  "reply": false,
  "version": "1.2.3"
}
```

**必选字段说明**
- `peer_id`：建议使用 UUID，确保跨程序不冲突
- `transfer_port`：TCP 握手端口，需与实际监听一致
- `reply`：当收到无 `reply` 的广播时，如果首次发现或超过冷却时间，应向源地址发送 `reply=true` 的定向报文

### 2.3 集成步骤
1. 启动监听线程，`SO_REUSEADDR` 绑定 `("", 45845)`。
2. 每个 Beacon 周期向广播地址发送 Presence。
3. 收到报文后校验 `type`，忽略自身 `peer_id`，更新或新增 `PeerInfo`。
4. 需要与 Glitter 互通时，字段命名与类型必须保持一致；多语言/版本可按需扩展，但请保留原字段。

## 3. TCP 文件传输握手

### 3.1 发送方流程
1. 连接目标 `target_ip:transfer_port`，超时建议 ≤10 秒。
2. 发送首个 JSON 行（带换行 `\n`），字段见下表。
3. 设置读超时（示例：0.5 秒），轮询等待 `ACCEPT…` 或 `DECLINE`。
4. 收到 `ACCEPT` 后进行数据流发送，并在结束时 `shutdown(SHUT_WR)`。

### 3.2 元数据字段

| 字段名 | 类型 | 说明 |
| --- | --- | --- |
| `type` | str | 固定为 `"transfer"` |
| `protocol` | int | 当前版本 `2` |
| `request_id` | str | UUID；用于后续关联 |
| `filename` | str | 基础文件名 |
| `filesize` | int | 字节数（若发送目录，为 zip 大小） |
| `sender_name` | str | 显示名称 |
| `sender_language` | str | 语言代码 |
| `version` | str | 客户端版本 |
| `sha256` | str | 32 字节十六进制摘要 |
| `content_type` | str | `"file"` 或 `"directory"` |
| `encryption` | str/bool | `"enabled"`/`"disabled"` 或布尔值 |
| `sender_id` | str, 可选 | 基于 `config.device_id` 的稳定标识 |
| `identity` | dict, 可选 | 参见下文身份指纹 |
| `nonce` | str(Base64) | 加密启用时必选 |
| `dh_public` | str(Base64) | 加密启用时必选 |
| `archive` | str, 可选 | 目录时为 `"zip-store"` |
| `original_size` | int, 可选 | 压缩前总字节数 |

### 3.3 接收方响应
- `DECLINE`：发送方应立即终止。
- `ACCEPT`：可带附加 JSON，例如：
  ```text
  ACCEPT {"dh_public": "...", "identity": {"public": "...", "fingerprint": "..."}, "peer_id": "..."}
  ```
- 若启用加密，必须携带接收方 `dh_public`，双方共同使用 `nonce` 和对方公钥推导会话密钥。

### 3.4 状态与超时
- 连接建立后，接收端通过 `TransferTicket.wait_for_decision()` 等待用户或规则决策；若连接空闲且对端关闭，则视为 `sender_cancelled`。
- 发送端应实现取消机制，必要时向套接字写入结束标识。

## 4. 身份与信任 (TOFU)
- 身份字段 `identity.public`：Base64 编码的 Ed25519 公钥（私钥存于配置中）。
- `identity.fingerprint`：派生指纹字符串（可显示，最终以 `fingerprint_from_public_key` 计算结果为准）。
- 推荐策略：初次接入记录指纹，后续若变更需提示或拒绝，逻辑可参考 `TrustedPeerStore`。

## 5. 文件与目录处理
- `content_type="directory"` 时，发送端先将目录打包为 Zip（无压缩），接收端需在临时目录解压并校验。
- 文件写入过程中需实时校验 SHA-256；不匹配即宣告失败。
- 目标路径冲突时，接收端以 `filename(1).ext`、`filename(2).ext` 递增命名。

## 6. 错误与状态对照

| 状态 | 触发场景 | 建议处理 |
| --- | --- | --- |
| `pending` | 等待接收方决定 | 轮询/回调触发 UI 或自动规则 |
| `receiving` | 已接受，开始收流 | 可提供进度回调 |
| `completed` | 正常完成 | 记录历史 |
| `declined` | 接收方拒绝 | 终止发送 |
| `cancelled` | 发送方断开或被动取消 | 清理凭据 |
| `failed` | 网络/校验异常 | 提示并移除临时文件 |

## 7. 兼容性建议
- **常量统一**：建议复用 Glitter 提供的端口、协议版本常量，或在双方程序中集中管理。
- **版本协商**：保持 `protocol` 字段，必要时根据版本降级流程（例如未携带身份字段时按 V1 处理）。
- **资源互斥**：若同机运行多个程序监听同一端口，需自行实现端口协商或多路复用。
- **线程安全**：`TransferService` 使用 `threading`; 若外部程序采用异步框架，需在阻塞调用与事件循环间建立桥接。
- **日志与审计**：建议记录所有握手元数据与指纹变更，便于排错与安全审计。

## 8. 推荐接入步骤总结
1. 抽取/复制 Discovery 与 Transfer 常量、工具函数到共用模块。
2. 实现 UDP Presence 监听与广播逻辑，确保字段一致。
3. 按表格构造 TCP 握手首包，并在接收端返回 `ACCEPT/DECLINE`。
4. 集成 Diffie-Hellman 密钥推导与 `StreamCipher`，保持与 Glitter 相同算法。
5. 管理信任数据（可直接复用 `TrustedPeerStore` 文件格式）。
6. 编写集成测试：模拟 sender/receiver，验证兼容性、取消、失败、目录传输等场景。
