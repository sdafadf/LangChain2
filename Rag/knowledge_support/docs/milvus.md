# Docker Milvus 检索说明

当前实例：Docker 容器 `milvus-standalone`，宿主机 `localhost:19530`。数据库 `rag_tutorial`，原客服集合 `docs` 保留，校园集合 `campus_docs_v1` 使用 3072 维 COSINE 索引。

## 问题如何匹配答案

用户已选择 RAG 流程，不构建历史问答匹配库：

1. 上传原文切成片段，调用原 `text-embedding-3-large` 服务获得向量。
2. 原文片段和向量写入 Milvus。文档全部完成后写入完成标记。
3. 提问调用同一个 embedding 模型生成查询向量。
4. `MilvusKnowledge.client_search()` 内实际调用 `self.client.search()`，匹配同分类、同模型、已完成的资料片段。
5. 将检索原文与问题交给原 `deepseek-v4-flash` 生成引用资料的答案。

`client_search` 是本项目封装的方法，Milvus Python SDK 实际方法名是 `client.search`。Python 不自行计算余弦相似度，不从本地 SQLite 遍历向量。

## 旧资料迁移

本次已迁移 6 份资料、52 个片段。迁移脚本仅从旧文件读取已有向量再写入本机 Milvus，不重新请求 embedding，不删除旧文件。

```text
python migrate_to_milvus.py --project <原项目目录>
```

运行前校验旧向量模型指纹及片段完整性；有缺失就报错，不静默重建或跳过。重复执行会跳过已提交资料。旧文件仅作为迁移备份留存，应用入口不会再打开它。

## 配置和故障

- `MILVUS_URL` 默认 `http://localhost:19530`；`MILVUS_DATABASE` 默认 `rag_tutorial`。
- `MILVUS_CAMPUS_COLLECTION` 默认 `campus_docs_v1`；不会采用原 `MILVUS_COLLECTION=docs`。
- `EMBED_DIMENSION` 默认 3072；模型维度必须与集合一致。
- Milvus 不可用时提示检查 Docker，绝不自动切回 SQLite。
- 部分写入缺少完成标记，不参与检索；重传同一资料会使用相同主键补齐。
- 资料删除先移除完成标记再删除片段，避免部分删除的资料仍被查询。
- 相似度阈值 0.25 是当前启发式设置，不能当作答案正确率。
- 历史聊天只在 Streamlit 会话中保留，未写入 Milvus 问答集合。

界面不会提供另一套 SQLite 模式。本地规则统计不需要 Milvus，但资料上传和检索需要运行中的 Docker 服务，远程 embedding 与 ChatModel 需要网络。
