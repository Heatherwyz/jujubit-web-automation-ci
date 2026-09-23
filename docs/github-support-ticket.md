# GitHub Support 工单：请求清除失联旧 commit

> 用途：force push 重写历史后，旧 commit 仍留在 GitHub 服务端，用完整 SHA
> 能继续读到已移除的内部文档。GitHub 不会自动回收，必须提工单请他们做
> 服务端 GC 并清缓存。**这一步完成前不要把仓库改为公开。**
>
> 提交地址：https://support.github.com/
> 分类选：Account or profile → Sensitive data removal
>
> 本文件只是提工单用的模板，不含任何内部信息，可以留在仓库里。

## 事实核对（2026-09-22 实测）

| 项 | 值 |
| --- | --- |
| 仓库 | `Heatherwyz/jujubit-web-automation` |
| 当前可见性 | Private |
| Fork 数 | 0 |
| PR 数 | 0 |
| 协作者 | 仅 owner 一人 |
| 首个受影响 commit | `af4c1d62b7a5863677a61b0d7e202520bcaae18f`（2026-09-17） |
| 重写前 main HEAD | `681fc3d9d63f69544cf4916414c169496a91ad4d` |
| 重写后 main HEAD | `537087b9db242fe31a9634af592524587df29688` |

验证过仍可访问（这是提工单的依据）：

```bash
# 旧 SHA 仍能取到已移除的内部文档目录，返回 9 个文件
gh api "/repos/Heatherwyz/jujubit-web-automation/contents/docs/requirements?ref=681fc3d9d63f69544cf4916414c169496a91ad4d"
```

## 工单正文（英文，直接复制）

```
Subject: Request server-side GC after history rewrite (internal docs + tenant identifiers removed)

Repository: Heatherwyz/jujubit-web-automation

I have rewritten this repository's history with git-filter-repo and
force-pushed to remove content that should never have been committed:

1. An internal product-requirements directory (docs/requirements/, 9 files)
   containing confidential membership-system design documents and internal
   manual test cases copied from our company wiki.
2. A hard-coded internal Lark (Feishu) tenant hostname and wiki document
   token, which identify our company's private workspace.
3. An internal operations back-office URL.

First changed commit: af4c1d62b7a5863677a61b0d7e202520bcaae18f
Old main HEAD before rewrite: 681fc3d9d63f69544cf4916414c169496a91ad4d
New main HEAD after rewrite:  537087b9db242fe31a9634af592524587df29688

All current refs are clean. However, the dangling commits are still
reachable by full SHA. For example this still returns the removed
directory listing:

  GET /repos/Heatherwyz/jujubit-web-automation/contents/docs/requirements
      ?ref=681fc3d9d63f69544cf4916414c169496a91ad4d

Repository state: 0 forks, 0 pull requests, single collaborator (owner).
So no external clones or PR refs need dereferencing.

Request: please run garbage collection on the server and remove cached
views so the stale commits are no longer retrievable. Rotating a
credential is not applicable here — this is confidential company
documentation, not a secret that can be rotated.

I plan to make this repository public only after this cleanup is
confirmed complete.

Thank you.
```

## 提交后

GitHub 确认清理完成后，用这条命令验证（应返回 404 而不是文件列表）：

```bash
gh api "/repos/Heatherwyz/jujubit-web-automation/contents/docs/requirements?ref=681fc3d9d63f69544cf4916414c169496a91ad4d"
```

确认 404 后才可以改公开可见性。

## 本地备份位置

重写前的完整历史已备份，万一需要回退：

- 需求文档副本：`~/jujubit-requirements-backup-20260922-163516/`
- 全仓库 bundle：`~/jujubit-repo-backup-20260922-165104.bundle`（已验证完整）

从 bundle 恢复：`git clone <bundle 路径> <目标目录>`
