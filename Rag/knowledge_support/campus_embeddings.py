"""Use the original project's embedding endpoint; keep campus vectors in SQLite."""
import hashlib
import json
import math
import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlparse

from campus_core import LocalKnowledge


@dataclass(frozen=True)
class EmbeddingConfig:
    model: str = 'text-embedding-3-large'
    base_url: str = 'https://api.openai.com/v1'
    api_key: str = field(default='', repr=False)

    @classmethod
    def from_project(cls, root):
        from dotenv import dotenv_values
        values = {}
        root = Path(root).resolve()
        for parent in [root, *root.parents]:
            candidate = parent / '.env'
            if candidate.is_file():
                for key, value in dotenv_values(candidate).items():
                    values.setdefault(key, value)
                if parent != root:
                    break
        values.update({key: value for key, value in os.environ.items()
                       if key in ('EMBED_MODEL_NAME', 'OPENAI_BASE_URL', 'OPENAI_API_KEY')})
        name = values.get('EMBED_MODEL_NAME') or 'openai:text-embedding-3-large'
        if name.startswith('openai:'):
            name = name[len('openai:'):]
        return cls(name, values.get('OPENAI_BASE_URL') or cls.base_url,
                   values.get('OPENAI_API_KEY') or '')

    @property
    def fingerprint(self):
        return hashlib.sha256((self.base_url.rstrip('/')+'\n'+self.model).encode()).hexdigest()


class ProjectEmbedder:
    def __init__(self, config):
        self.config = config

    def embed(self, texts):
        if not self.config.api_key:
            raise ValueError('未找到原项目 OPENAI_API_KEY，请配置本目录或上级 .env。')
        url = urlparse(self.config.base_url)
        if url.scheme not in ('http', 'https') or not url.hostname or url.username or url.password:
            raise ValueError('原项目 OPENAI_BASE_URL 格式无效。')
        import httpx
        from langchain_openai import OpenAIEmbeddings
        try:
            with httpx.Client(trust_env=False, timeout=60, follow_redirects=False) as client:
                embedding = OpenAIEmbeddings(model=self.config.model,
                    base_url=self.config.base_url, api_key=self.config.api_key,
                    http_client=client, request_timeout=60, max_retries=0,
                    check_embedding_ctx_length=False)
                vectors = embedding.embed_documents(texts, chunk_size=32)
        except Exception as exc:
            raise RuntimeError('Embedding 服务调用失败，请检查原项目模型、地址、密钥或网络；未切换其他模型。') from None
        validate_vectors(vectors, len(texts))
        return vectors


def validate_vectors(vectors, count):
    if len(vectors) != count or not vectors:
        raise ValueError('Embedding 返回向量数量不正确。')
    dimension = len(vectors[0])
    if not dimension or any(len(v) != dimension or not all(isinstance(n, (int,float)) and math.isfinite(n) for n in v)
                            or not sum(n*n for n in v) > 0 for v in vectors):
        raise ValueError('Embedding 返回无效向量或不一致的维度。')


class VectorKnowledge(LocalKnowledge):
    """Atomic per-document indexing; never mix models/endpoints in retrieval."""
    def __init__(self, path, config, embedder=None):
        super().__init__(path)
        self.config = config
        self.embedder = embedder or ProjectEmbedder(config)
        with self.connect() as conn:
            conn.execute('CREATE TABLE IF NOT EXISTS campus_vectors (document_id TEXT, model_key TEXT, chunk INTEGER, text TEXT, vector TEXT, PRIMARY KEY(document_id,model_key,chunk))')

    def _vectors(self, text):
        chunks = [text[i:i+800] for i in range(0, len(text), 700) if text[i:i+800].strip()]
        vectors = self.embedder.embed(chunks)
        validate_vectors(vectors, len(chunks))
        return list(zip(chunks, vectors))

    def _save_vectors(self, conn, doc_id, items):
        conn.execute('DELETE FROM campus_vectors WHERE document_id=? AND model_key=?', (doc_id, self.config.fingerprint))
        conn.executemany('INSERT INTO campus_vectors VALUES (?,?,?,?,?)',
                         [(doc_id,self.config.fingerprint,i,text,json.dumps(vector)) for i,(text,vector) in enumerate(items)])

    def add(self, source, category, text):
        if category not in ('课程', '行政') or not text.strip() or len(text) > 200000:
            raise ValueError('请选择课程或行政分类，文本需为 1 至 20 万字符。')
        doc_id = hashlib.sha256((category+'\n'+text).encode()).hexdigest()
        with self.connect() as conn:
            if conn.execute('SELECT 1 FROM documents WHERE id=?', (doc_id,)).fetchone() and conn.execute(
                    'SELECT 1 FROM campus_vectors WHERE document_id=? AND model_key=?', (doc_id,self.config.fingerprint)).fetchone():
                return False
        items = self._vectors(text)
        with self.connect() as conn:
            size = conn.execute('SELECT COALESCE(SUM(length(text)),0) FROM documents WHERE id<>?', (doc_id,)).fetchone()[0]
            if size + len(text) > 5000000:
                raise ValueError('轻量知识库已达 500 万字符上限。')
            conn.execute('INSERT OR IGNORE INTO documents VALUES (?,?,?,?)',
                         (doc_id,source.replace('\\','/').rsplit('/',1)[-1][:150],category,text))
            self._save_vectors(conn, doc_id, items)
        return True

    def pending(self, category=None):
        with self.connect() as conn:
            return conn.execute('SELECT d.id,d.text FROM documents d WHERE (? IS NULL OR d.category=?) AND NOT EXISTS '
                '(SELECT 1 FROM campus_vectors v WHERE v.document_id=d.id AND v.model_key=?)',
                (category,category,self.config.fingerprint)).fetchall()

    def index_pending(self):
        count = 0
        for doc_id, text in self.pending():
            items = self._vectors(text)
            with self.connect() as conn:
                if conn.execute('SELECT 1 FROM documents WHERE id=?', (doc_id,)).fetchone():
                    self._save_vectors(conn, doc_id, items)
                    count += 1
        return count

    def delete(self, document_id):
        with self.connect() as conn:
            conn.execute('DELETE FROM campus_vectors WHERE document_id=?', (document_id,))
            conn.execute('DELETE FROM documents WHERE id=?', (document_id,))

    def search(self, query, category, limit=4):
        if self.pending(category):
            raise ValueError('部分资料尚未使用当前 embedding 模型建索引，请到知识库管理点击“为已有资料建立向量索引”。')
        with self.connect() as conn:
            stored = conn.execute('SELECT d.source,v.text,v.vector FROM campus_vectors v JOIN documents d ON d.id=v.document_id '
                'WHERE d.category=? AND v.model_key=?', (category,self.config.fingerprint)).fetchall()
        if not stored:
            return []
        query_vectors = self.embedder.embed([query])
        validate_vectors(query_vectors, 1)
        query_vector = query_vectors[0]
        q_norm = math.sqrt(sum(n*n for n in query_vector))
        hits = []
        for source,text,encoded in stored:
            vector = json.loads(encoded)
            validate_vectors([vector], 1)
            if len(vector) != len(query_vector):
                raise ValueError('查询与资料向量维度不一致，请检查模型配置；未混用索引。')
            score = sum(a*b for a,b in zip(vector,query_vector)) / (q_norm*math.sqrt(sum(n*n for n in vector)))
            if score >= 0.25:
                hits.append({'source':source,'text':text,'score':score})
        hits.sort(key=lambda hit:hit['score'], reverse=True)
        return [{**hit,'reference':f'资料{i}'} for i,hit in enumerate(hits[:limit],1)]
