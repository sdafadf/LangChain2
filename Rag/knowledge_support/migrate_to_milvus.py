"""One-time read-only SQLite migration. Reuse vectors; no embedding API requests."""
import argparse
import json
import sqlite3
from pathlib import Path
from campus_embeddings import EmbeddingConfig
from campus_milvus import MilvusKnowledge, MilvusSettings


def migrate(root):
    root = Path(root).resolve()
    source = root / 'data/campus.sqlite3'
    if not source.is_file():
        raise ValueError('未找到旧知识库文件；新安装无需运行迁移。')
    config = EmbeddingConfig.from_project(root)
    knowledge = MilvusKnowledge(MilvusSettings.from_project(root), config)
    connection = sqlite3.connect(source.as_uri()+'?mode=ro', uri=True)
    imported = skipped = 0
    try:
        documents = connection.execute('SELECT id,source,category,text FROM documents').fetchall()
        prepared = []
        # Validate all old records before mutating Milvus, and never silently re-embed.
        for doc_id, name, category, text in documents:
            vectors = connection.execute('SELECT chunk,text,vector FROM campus_vectors WHERE document_id=? AND model_key=? ORDER BY chunk',
                                         (doc_id,config.fingerprint)).fetchall()
            chunks = [text[i:i+800] for i in range(0,len(text),700) if text[i:i+800].strip()]
            if len(vectors) != len(chunks) or any(index != i or chunk != chunks[i] for i,(index,chunk,_) in enumerate(vectors)):
                raise ValueError('有资料缺少匹配当前模型的完整旧向量，迁移停止；未重新发送文本到外部服务。')
            prepared.append((name,category,text,[(chunk,json.loads(vector)) for _,chunk,vector in vectors]))
        for name,category,text,items in prepared:
            if knowledge.import_document(name,category,text,items):
                imported += 1
            else:
                skipped += 1
        print(json.dumps({'imported':imported,'already_present':skipped,'status':knowledge.status()},ensure_ascii=True))
    finally:
        connection.close()
        knowledge.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--project', default=str(Path(__file__).resolve().parent))
    migrate(parser.parse_args().project)
