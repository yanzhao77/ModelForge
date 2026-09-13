# V1.4 — Knowledge / RAG

目标：让 Agent 与 Chat 使用用户自己的知识，并把知识库纳入统一模型/任务体系。

## 实现

| 组件 | 文件 | 说明 |
|---|---|---|
| 文档解析 | `services/knowledge_base.py::FileParser` | 新增 DOCX（python-docx 或纯 zip/OOXML 回退）与 CSV/TSV；原有 PDF/MD/TXT/代码保持 |
| 检索模式 | `services/knowledge_base.py` | `semantic` / `keyword` / `hybrid` / `rerank`，返回 `semantic_score` 与 `lexical_score` |
| 知识库服务 | `services/knowledge_service.py` | 知识库 CRUD、文档挂载/解绑、索引进度 |
| Embedding Provider | `services/embedding_service.py` | `hash`（默认、无依赖、确定性）与 `transformers`（注册表 `EMBEDDING` 模型，均值池化），失败时**显式**回退并给出原因 |
| 能力推导 | `services/model_capabilities.py` | 含 `sentence_bert_config.json`/`modules.json`/`1_Pooling` 的目录 → 只有 `EMBEDDING`，不会出现在 Chat 列表 |
| 任务中心联动 | `api/knowledge.py::_project_index_task` | 上传后投影 `knowledge_index` 任务（进度/分块数可见） |
| API | `api/knowledge.py` | `GET/POST /knowledge/bases`、`GET/PATCH/DELETE /knowledge/bases/{id}`、`.../documents`、`GET /knowledge/embedding`、`POST /knowledge/embed`；`/query`、`/answer` 新增 `retrieval_mode` |

## 验收

| 验收项 | 证据 |
|---|---|
| Knowledge Base | `tests/test_knowledge_rag_v14.py::test_knowledge_base_crud_and_document_binding` |
| Document ingestion | `test_csv_and_docx_are_parsed_into_text` |
| Chunking | 复用 `TextChunker`（既有用例 + 上传分块数） |
| Embedding | `test_embedding_provider_defaults_to_hash_with_a_reason` |
| Qdrant | 第一阶段复用内置向量索引；`embedding`/`retrieval` 已抽出接口，后续可替换 |
| Retrieval | `test_retrieval_modes_change_ranking`（四种模式 + 非法模式 422） |
| Agent RAG | `knowledge_config.collection_ids` + `KBKnowledgeProvider`（V1.1 Agent 链路） |
| Knowledge UI | 既有知识库页面 + 集合 API |
| Index progress | `test_upload_projects_an_indexing_task` |
| E2E RAG | `tests/test_platform_e2e.py::test_chain_rag_document_to_answer` |

## 已知限制

默认 `hash` 向量是词袋相似度，不是语义向量；要获得真实语义检索需注册一个
`EMBEDDING` 模型并安装 `transformers` + `torch`（此时 `/knowledge/embedding`
会报告 `provider=transformers, fallback=false`）。
