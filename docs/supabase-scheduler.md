# 用 Supabase pg_cron 定时触发 GitHub 全量回归

> 准时入口。GitHub 自己的 `schedule` 已从 `daily-regression.yml` 移除：
> 它对本仓库长期迟到 4–5 小时，与外部调度并存会让同一天重复跑全量
> （每轮约 40 分钟，且购物车层会真实操作测试账号）。
> 本机 LaunchAgent 也已卸载，改由 Supabase 服务端触发，不依赖某台 Mac 开机。

## 当前实际状态（2026-09-23）

- **任务所在库**：测试环境运营工作台（私有化 Supabase），由用户确认留在这里，
  不迁正式库。
- **定时任务**：`cron.job` 里 `jobid=113`，任务名 `独立站UI回归-早九晚九`，
  `active=true`。
- **触发目标**：一次 `net.http_post` 调
  `repos/Heatherwyz/jujubit-web-automation-ci/actions/workflows/daily-regression.yml/dispatches`。
  不再分三个旧工作流各打一次——代码已合并成单一工作流串行跑四层
  （离线 → 首页 → 会员 → 购物车）。
- **PAT 密钥**：Vault 里叫 `jujubit_github_actions_pat`。
- **时间**：`0 1,13 * * *`，`pg_cron` 是 UTC，对应北京 09:00 和 21:00。

本文件是运维手册，描述怎么排查和重建。**现状以 `cron.job` 实际记录为准**，
文档和库里不一致时以库为准。

## 需要什么凭据

**只需要一个 GitHub PAT。** 运营后台的 `DASHBOARD_USERNAME` /
`DASHBOARD_PASSWORD` 在这里用不上——那是登录后台页面的，不是调 GitHub API 的。

PAT 要求（用 fine-grained token，不要用 classic）：

| 项 | 值 |
| --- | --- |
| 类型 | Fine-grained personal access token |
| Repository access | Only select repositories → `jujubit-web-automation-ci` |
| 权限 | Actions: **Read and write**（仅此一项） |
| 有效期 | 90 天或更短，到期前轮换 |

生成地址：https://github.com/settings/personal-access-tokens/new

**PAT 绝不写进 SQL 或仓库**，存 Supabase Vault，用的时候按名字取。

## 第 1 步：启用扩展

Supabase Dashboard → Database → Extensions，开这两个：

- `pg_cron` — 定时器
- `pg_net` — 让数据库能发 HTTP 请求

## 第 2 步：把 PAT 存进 Vault

Dashboard → Project Settings → Vault → Add new secret：

- Name: `jujubit_github_actions_pat`
- Secret: 粘贴刚才生成的 PAT

## 第 3 步：建 / 更新定时任务

SQL Editor 里执行。任务已存在时直接 `alter_job`，不要重建——重建会换 jobid，
排查历史时对不上。

```sql
-- 创建（首次）。北京 09:00 / 21:00 = UTC 01:00 / 13:00。
select cron.schedule(
  '独立站UI回归-早九晚九',
  '0 1,13 * * *',
  $$
  select net.http_post(
    url := 'https://api.github.com/repos/Heatherwyz/jujubit-web-automation-ci/actions/workflows/daily-regression.yml/dispatches',
    headers := jsonb_build_object(
      'Authorization', 'Bearer ' || (
        select decrypted_secret from vault.decrypted_secrets
        where name = 'jujubit_github_actions_pat' limit 1
      ),
      'Accept', 'application/vnd.github+json',
      'X-GitHub-Api-Version', '2022-11-28',
      'User-Agent', 'jujubit-supabase-scheduler',
      'Content-Type', 'application/json'
    ),
    body := jsonb_build_object('ref', 'main'),
    timeout_milliseconds := 15000
  );
  $$
);

-- 已存在则原地更新（jobid 不变）。
select cron.alter_job(
  job_id := 113,
  schedule := '0 1,13 * * *',
  command := $$
  select net.http_post(
    url := 'https://api.github.com/repos/Heatherwyz/jujubit-web-automation-ci/actions/workflows/daily-regression.yml/dispatches',
    headers := jsonb_build_object(
      'Authorization', 'Bearer ' || (
        select decrypted_secret from vault.decrypted_secrets
        where name = 'jujubit_github_actions_pat' limit 1
      ),
      'Accept', 'application/vnd.github+json',
      'X-GitHub-Api-Version', '2022-11-28',
      'User-Agent', 'jujubit-supabase-scheduler',
      'Content-Type', 'application/json'
    ),
    body := jsonb_build_object('ref', 'main'),
    timeout_milliseconds := 15000
  );
  $$
);
```

**cron 表达式是 UTC**，不是北京时间。pg_cron 跟随数据库时区，Supabase 默认 UTC。

## 第 4 步：验证

先手动跑一次任务体，确认能真的触发：

```sql
select net.http_post(
  url := 'https://api.github.com/repos/Heatherwyz/jujubit-web-automation-ci/actions/workflows/daily-regression.yml/dispatches',
  headers := jsonb_build_object(
    'Authorization', 'Bearer ' || (
      select decrypted_secret from vault.decrypted_secrets
      where name = 'jujubit_github_actions_pat' limit 1
    ),
    'Accept', 'application/vnd.github+json',
    'X-GitHub-Api-Version', '2022-11-28',
    'User-Agent', 'jujubit-supabase-scheduler',
    'Content-Type', 'application/json'
  ),
  body := jsonb_build_object('ref', 'main'),
  timeout_milliseconds := 15000
);
```

成功的标志是 GitHub 返回 **204 No Content**。查响应：

```sql
select id, status_code, content
from net._http_response
order by created desc
limit 3;
```

- `204` → 成功，去 Actions 页面能看到新的 `workflow_dispatch` 运行
- `401` → PAT 无效或过期
- `403` → PAT 权限不够（要 Actions: Read and write）
- `404` → 仓库名或工作流文件名不对，也可能是 PAT 没勾这个仓库

再确认 GitHub 侧收到了：

```bash
gh run list --repo Heatherwyz/jujubit-web-automation-ci --limit 3
```

## 运维

```sql
-- 看已建的任务
select jobid, jobname, schedule, active from cron.job;

-- 看执行历史（排查漏跑）
select jobid, status, return_message, start_time
from cron.job_run_details
order by start_time desc limit 10;

-- 临时停用
update cron.job set active = false where jobid = 113;

-- 删掉
select cron.unschedule(113);
```

## 注意

**只保留一条触发路径。** 现在 GitHub cron 已从工作流移除、本机 LaunchAgent
已卸载，Supabase 是唯一入口。如果之后又加回别的调度，同一天会重复跑全量——
购物车层每轮都会在测试账号下真实生成模型并加购。

**PAT 到期会静默失效。** 到期后 `net.http_post` 返回 401，但 pg_cron 任务
本身仍显示成功（HTTP 请求发出去了）。所以要定期看 `net._http_response` 的
`status_code`，或者在飞书群没收到卡片时去查这张表。

**Studio 的 Cron 列表页经常画不出来**（侧栏显示 `project/undefined`，主区域空白），
是前端渲染问题，任务实际在数据库里。以 `cron.job` 和 `cron.job_run_details` 为准，
不要按那张空页判断"任务没了"。
