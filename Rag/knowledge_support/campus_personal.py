"""Session-owned student documents; never writes to the shared course store."""
import hashlib
import math

from campus_embeddings import validate_vectors


class PersonalKnowledge:
    def __init__(self):
        self.documents = {}

    def add(self, source, text):
        if not text.strip() or len(text) > 200000:
            raise ValueError('资料须包含文字，且不超过 20 万字符。')
        ident = hashlib.sha256(text.encode('utf-8')).hexdigest()
        if ident in self.documents:
            return ident, False
        if len(self.documents) >= 10 or sum(len(d['text']) for d in self.documents.values()) + len(text) > 500000:
            raise ValueError('本次会话最多保存 10 份资料、合计 50 万字符，请先删除不需要的文件。')
        self.documents[ident] = {
            'name': str(source).replace('\\', '/').rsplit('/', 1)[-1][:150],
            'text': text,
            'chunks': [text[i:i + 800] for i in range(0, len(text), 700) if text[i:i + 800].strip()],
            'vectors': None, 'model_key': None,
        }
        return ident, True

    def delete(self, ident):
        self.documents.pop(ident, None)

    def read(self, ident):
        return self.documents[ident]['text']


class PersonalSearch:
    def __init__(self, knowledge, embedder, model_key):
        self.knowledge, self.embedder, self.model_key = knowledge, embedder, model_key

    def search(self, query, category, limit=4, document_ids=None):
        if category != '课程' or not query.strip():
            raise ValueError('请输入有效的课程问题。')
        # An explicit selection is required; missing IDs never expand to other documents.
        if not document_ids:
            return []
        selected = [self.knowledge.documents[ident] for ident in dict.fromkeys(document_ids)
                    if ident in self.knowledge.documents]
        if not selected:
            return []
        query_vectors = self.embedder.embed([query])
        validate_vectors(query_vectors, 1)
        query_vector = query_vectors[0]
        hits = []
        for doc in selected:
            vectors = doc['vectors'] if doc['model_key'] == self.model_key else None
            if vectors is None:
                vectors = self.embedder.embed(doc['chunks'])
            validate_vectors(vectors, len(doc['chunks']))
            if len(vectors[0]) != len(query_vector):
                raise ValueError('资料与问题的向量维度不一致，请检查向量模型配置。')
            doc['vectors'], doc['model_key'] = vectors, self.model_key
            for chunk, vector in zip(doc['chunks'], vectors):
                score = sum(a*b for a,b in zip(query_vector, vector)) / (
                    math.sqrt(sum(a*a for a in query_vector)) * math.sqrt(sum(a*a for a in vector)))
                if score >= 0.25:
                    hits.append({'text': chunk, 'source': doc['name'], 'score': score})
        hits.sort(key=lambda hit: hit['score'], reverse=True)
        return [{**hit, 'reference': f'资料{i}'} for i, hit in enumerate(hits[:limit], 1)]
