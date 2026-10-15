# 飞书妙搭触发 GitHub 测试

测试在 GitHub Actions 上执行。飞书妙搭只负责识别指令并调用 GitHub，不需要本机或 Mac Mini 常驻监听。

仓库：`Heatherwyz/jujubit-web-automation-ci`

## 1. 准备 GitHub Token

1. 打开 GitHub → Settings → Developer settings → Personal access tokens。
2. 创建 Fine-grained token。
3. Repository access 只选 `jujubit-web-automation-ci`。
4. Permissions 里给 Actions 打开 `Read and write`。
5. 把 Token 填进妙搭的密钥配置，名称为 `GITHUB_TOKEN`。

不要把 Token 发到飞书群，也不要写进仓库。

## 2. 妙搭请求

请求方法：`POST`

请求头：

```http
Authorization: Bearer {{GITHUB_TOKEN}}
Accept: application/vnd.github+json
Content-Type: application/json
```

GitHub 返回 `204` 表示任务已排队，不是测试通过。真正的结果仍由现有「web UI自动化」机器人发回飞书群。

## 3. 指令对应关系

| 触发说法 | 工作流文件 | 请求体 |
| --- | --- | --- |
| 跑一下首页、首页回归 | `daily-ui-tests.yml` | `{"ref":"main"}` |
| 跑会员、会员测试 | `membership-ui-tests.yml` | `{"ref":"main"}` |
| 跑购物车、看看购物车 | `cart-ui-tests.yml` | `{"ref":"main","inputs":{"suite":"smoke"}}` |
| 跑全量、每日回归 | `daily-regression.yml` | `{"ref":"main"}` |

### 首页

```http
POST https://api.github.com/repos/Heatherwyz/jujubit-web-automation-ci/actions/workflows/daily-ui-tests.yml/dispatches
```

```json
{"ref":"main"}
```

### 会员

```http
POST https://api.github.com/repos/Heatherwyz/jujubit-web-automation-ci/actions/workflows/membership-ui-tests.yml/dispatches
```

```json
{"ref":"main"}
```

### 购物车

```http
POST https://api.github.com/repos/Heatherwyz/jujubit-web-automation-ci/actions/workflows/cart-ui-tests.yml/dispatches
```

```json
{"ref":"main","inputs":{"suite":"smoke"}}
```

购物车不要传 `full`。`full` 会真实生成模型并修改测试账号购物车。

### 全量

```http
POST https://api.github.com/repos/Heatherwyz/jujubit-web-automation-ci/actions/workflows/daily-regression.yml/dispatches
```

```json
{"ref":"main"}
```

全量会串行执行首页、会员和购物车每日分层，耗时约 40 分钟。

## 4. 妙搭配置

1. 触发条件选“群消息”或“@机器人”。
2. 用关键词或大模型识别上面四类说法。
3. 识别后先回复“正在 GitHub 上执行”。
4. 调用对应的 HTTP 请求。
5. 请求返回 `204` 后回复“已排队，完成后会在群里发结果”。
6. 返回 `401` 表示 Token 无效；返回 `404` 表示工作流文件名或仓库名错误；返回 `403` 表示 Token 没有 Actions 写权限。

## 5. 结果报告

妙搭不需要自己生成测试报告。GitHub Actions 跑完后，现有流程会把通过数、失败数和 HTML 报告链接发到飞书群。
