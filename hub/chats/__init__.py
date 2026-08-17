"""原始对话库:五个平台的历史对话,字节级原样、append-only 收进金库备份区。

设计见 docs/specs/2026-08-14-hub-chats-raw-store.md v2。两层职责不能混:
原始层(金库 <host>/<tool>/chats/)是唯一事实源、坏了没得重建;
派生层(~/.hub/chats-index.db)是索引,随时可以删了重建。
"""
