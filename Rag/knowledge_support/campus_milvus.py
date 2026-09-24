"""Docker Milvus campus knowledge store. Runtime never reads or writes SQLite.

Documents become searchable only after their final manifest is written.
All similarity ranking runs in MilvusClient.search, not in Python.
"""
import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

from campus_embeddings import ProjectEmbedder, validate_vectors


def literal(value):
    return json.dumps(value, ensure_ascii=False)


@dataclass(frozen=True)
class MilvusSettings:
    uri: str = 'http://localhost:19530'
    database: str = 'rag_tutorial'
    collection: str = 'campus_docs_v1'
    dimension: int = 3072
    token: str = field(default='', repr=False)

    @classmethod
    def from_project(cls, root):
        from dotenv import dotenv_values
        values = {}
        root = Path(root).resolve()
        for directory in [root, *root.parents]:
            path = directory / '.env'
            if path.is_file():
                for key,value in dotenv_values(path).items():
                    values.setdefault(key,value)
                if directory != root:
                    break
        for key in ('MILVUS_URL','MILVUS_DATABASE','MILVUS_CAMPUS_COLLECTION','MILVUS_TOKEN','EMBED_DIMENSION'):
            if key in os.environ:
                values[key] = os.environ[key]
        result = cls(values.get('MILVUS_URL') or cls.uri,
                     values.get('MILVUS_DATABASE') or cls.database,
                     values.get('MILVUS_CAMPUS_COLLECTION') or cls.collection,
                     int(values.get('EMBED_DIMENSION') or 3072), values.get('MILVUS_TOKEN') or '')
        if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,254}', result.collection) or result.collection == 'docs':
            raise ValueError('校园集合名称无效，且不能使用原客服 docs 集合。')
        return result


class MilvusKnowledge:
    def __init__(self, settings, config, client=None, embedder=None):
        self.settings, self.config = settings, config
        self.embedder = embedder or ProjectEmbedder(config)
        self._client = client
        self._ready = False

    @property
    def client(self):
        if self._client is None:
            from pymilvus import MilvusClient
            self._client = MilvusClient(uri=self.settings.uri, db_name=self.settings.database,
                                       token=self.settings.token, timeout=15)
        if not self._ready:
            self._ensure_collection()
            self._ready = True
        return self._client

    def _ensure_collection(self):
        from pymilvus import DataType
        client = self._client
        if not client.has_collection(self.settings.collection, timeout=15):
            client.create_collection(collection_name=self.settings.collection,
                dimension=self.settings.dimension, id_type='string', max_length=64,
                vector_field_name='vector', metric_type='COSINE', auto_id=False,
                consistency_level='Strong', timeout=30)
        schema = client.describe_collection(self.settings.collection, timeout=15)
        fields = {f['name']:f for f in schema['fields']}
        if (schema.get('auto_id') or not schema.get('enable_dynamic_field')
                or fields.get('id',{}).get('type') != DataType.VARCHAR
                or not fields.get('id',{}).get('is_primary')
                or fields.get('vector',{}).get('type') != DataType.FLOAT_VECTOR
                or int(fields.get('vector',{}).get('params',{}).get('dim',0)) != self.settings.dimension):
            raise ValueError('校园 Milvus 集合结构或维度不兼容；未修改已有集合，请检查配置。')
        # The reported score is interpreted as cosine; reject incompatible indexes.
        indexes = client.list_indexes(self.settings.collection, timeout=15)
        for name in indexes:
            index = client.describe_index(self.settings.collection, name, timeout=15)
            if index.get('field_name') == 'vector' and index.get('metric_type') != 'COSINE':
                raise ValueError('校园向量索引必须使用 COSINE，未更改原索引。')
        client.load_collection(self.settings.collection, timeout=30)

    def _key(self, document_id, chunk):
        return hashlib.sha256((document_id+'\n'+self.config.fingerprint+'\n'+str(chunk)).encode()).hexdigest()

    def _filter(self):
        return 'model_key == ' + literal(self.config.fingerprint)

    def _manifests(self, category=None):
        condition = self._filter() + ' and record_type == "manifest"'
        if category is not None:
            condition += ' and category == ' + literal(category)
        iterator = self.client.query_iterator(self.settings.collection, filter=condition,
            output_fields=['document_id','source','category','total_chars','chunk_count'],
            batch_size=500, consistency_level='Strong', timeout=15)
        rows = []
        try:
            while True:
                batch = iterator.next()
                if not batch:
                    break
                rows.extend(batch)
        finally:
            iterator.close()
        return rows

    def list(self):
        return sorted([{'id':r['document_id'],'来源':r['source'],'分类':r['category'],
                        '字符数':r['total_chars'],'片段数':r['chunk_count']} for r in self._manifests()], key=lambda r:r['来源'])

    def status(self):
        documents = self.list()
        return {'documents':len(documents),'chunks':sum(row['片段数'] for row in documents),
                'database':self.settings.database,'collection':self.settings.collection}

    def add(self, source, category, text):
        return self.import_document(source, category, text)

    def import_document(self, source, category, text, items=None):
        """items accepts previously validated (text, vector) pairs for local migration."""
        if category not in ('课程','行政') or not text.strip() or len(text) > 200000:
            raise ValueError('请选择课程或行政分类，文本需为 1 至 20 万字符。')
        doc_id = hashlib.sha256((category+'\n'+text).encode()).hexdigest()
        marker_id = self._key(doc_id, 'manifest')
        existing = self.client.get(self.settings.collection, ids=[marker_id],
                                   output_fields=['id'], consistency_level='Strong', timeout=15)
        if existing:
            return False
        if items is None:
            chunks = [text[i:i+800] for i in range(0,len(text),700) if text[i:i+800].strip()]
            items = list(zip(chunks, self.embedder.embed(chunks)))
        if not items:
            raise ValueError('没有可导入片段。')
        vectors = [v for _,v in items]
        validate_vectors(vectors, len(items))
        if len(vectors[0]) != self.settings.dimension:
            raise ValueError('Embedding 维度与 Milvus 集合不一致。')
        metadata = {'document_id':doc_id,'source':source.replace('\\','/').rsplit('/',1)[-1][:150],
                    'category':category,'model_key':self.config.fingerprint,
                    'chunk_count':len(items),'total_chars':len(text)}
        for offset in range(0,len(items),32):
            rows = [{**metadata,'id':self._key(doc_id,i),'record_type':'chunk','chunk_id':i,
                     'text':chunk,'vector':vector} for i,(chunk,vector) in enumerate(items[offset:offset+32],offset)]
            self.client.upsert(self.settings.collection, data=rows, timeout=30)
        # The manifest is the commit marker. Partial writes remain excluded from search.
        self.client.upsert(self.settings.collection, data=[{**metadata,'id':marker_id,
            'record_type':'manifest','chunk_id':-1,'text':'','vector':vectors[0]}], timeout=30)
        return True

    def delete(self, document_id):
        # Hide the document before removing chunks; failure cannot expose partial deletion.
        self.client.delete(self.settings.collection, ids=[self._key(document_id,'manifest')], timeout=15)
        self.client.delete(self.settings.collection,
            filter=self._filter()+' and document_id == '+literal(document_id), timeout=30)

    def client_search(self, query, category, limit=4, document_ids=None):
        """Question -> original embedding -> Milvus client.search -> cited source chunks."""
        if category not in ('课程','行政') or not query.strip():
            raise ValueError('请输入问题并选择正确资料分类。')
        documents = self._manifests(category)
        if document_ids is not None:
            selected = set(document_ids)
            documents = [doc for doc in documents if doc['document_id'] in selected]
        if not documents:
            return []
        vectors = self.embedder.embed([query])
        validate_vectors(vectors, 1)
        if len(vectors[0]) != self.settings.dimension:
            raise ValueError('查询向量维度与 Milvus 集合不一致。')
        doc_ids = [doc['document_id'] for doc in documents]
        results = self.client.search(collection_name=self.settings.collection, data=vectors,
            anns_field='vector', limit=limit,
            filter=self._filter()+' and record_type == "chunk" and category == '+literal(category)
                   +' and document_id in '+literal(doc_ids),
            search_params={'metric_type':'COSINE','params':{}},
            output_fields=['text','source','document_id','chunk_id'],
            consistency_level='Strong', timeout=20)
        hits = []
        for hit in (results[0] if results else []):
            entity = hit.get('entity',{})
            if entity.get('text') and float(hit['distance']) >= 0.25:
                hits.append({'text':entity['text'],'source':entity.get('source','未知来源'),
                             'chunk_id':entity.get('chunk_id'), 'score':float(hit['distance']),
                             'reference':f'资料{len(hits)+1}'})
        return hits

    def search(self, query, category, limit=4, document_ids=None):
        return self.client_search(query, category, limit, document_ids=document_ids)

    def close(self):
        if self._client is not None:
            self._client.close()
            self._client = None
            self._ready = False
