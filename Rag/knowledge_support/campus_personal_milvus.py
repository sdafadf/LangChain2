"""Persistent, local student library in a separate Milvus collection."""
from dataclasses import replace
from hashlib import sha256

from campus_milvus import MilvusKnowledge, literal


def student_settings(settings):
    # Keep names valid even when the configured public collection uses 255 chars.
    suffix = sha256(settings.collection.encode()).hexdigest()[:12]
    name = settings.collection[:220] + '_student_' + suffix
    return replace(settings, collection=name)


class StudentMilvus(MilvusKnowledge):
    def add(self, source, category, text):
        if category != '课程' or not text.strip() or len(text) > 200000:
            raise ValueError('个人资料须包含文字，且不超过 20 万字符。')
        ident = sha256(('课程\n' + text).encode()).hexdigest()
        if self.client.get(self.settings.collection, ids=[self._key(ident, 'manifest')],
                           output_fields=['id'], consistency_level='Strong', timeout=15):
            return False
        # Preserve every window so long blank sections do not shift text offsets.
        chunks = [text[i:i+800] for i in range(0, len(text), 700)]
        vectors = self.embedder.embed([chunk if chunk.strip() else '空白段落' for chunk in chunks])
        from campus_embeddings import validate_vectors
        validate_vectors(vectors, len(chunks))
        return self.import_document(source, category, text, list(zip(chunks, vectors)))

    def read_text(self, ident):
        manifest = next((row for row in self._manifests('课程') if row['document_id'] == ident), None)
        if manifest is None:
            raise ValueError('这份长期资料已不存在，请刷新列表。')
        iterator = self.client.query_iterator(self.settings.collection,
            filter=self._filter() + ' and record_type == "chunk" and document_id == ' + literal(ident),
            output_fields=['chunk_id', 'text'], batch_size=500, consistency_level='Strong', timeout=15)
        rows = []
        try:
            while True:
                batch = iterator.next()
                if not batch:
                    break
                rows.extend(batch)
        finally:
            iterator.close()
        if len(rows) != manifest['chunk_count']:
            raise ValueError('资料片段不完整，请重新上传这份文件。')
        # Existing ingestion uses 800-char windows with a 700-char stride.
        text = [' '] * manifest['total_chars']
        for row in sorted(rows, key=lambda item: item['chunk_id']):
            start = row['chunk_id'] * 700
            text[start:start + len(row['text'])] = row['text']
        return ''.join(text)


class PersistentPersonalKnowledge:
    def __init__(self, knowledge):
        self.knowledge = knowledge
        self._documents = None

    @property
    def documents(self):
        if self._documents is None:
            self._documents = {row['id']: {'name': row['来源'], 'chars': row['字符数']}
                               for row in self.knowledge.list() if row['分类'] == '课程'}
        return self._documents

    def add(self, source, text):
        added = self.knowledge.add(source, '课程', text)
        ident = sha256(('课程\n' + text).encode()).hexdigest()
        self._documents = None
        return ident, added

    def read(self, ident):
        if ident not in self.documents:
            raise ValueError('请选择当前资料库中的文件。')
        return self.knowledge.read_text(ident)

    def delete(self, ident):
        if ident not in self.documents:
            raise ValueError('资料已不存在，请刷新列表。')
        self.knowledge.delete(ident)
        self._documents = None

    def search(self, query, category, limit=4, document_ids=None):
        # Never allow an unscoped search to expand to all persistent documents.
        if not document_ids:
            return []
        return self.knowledge.search(query, category, limit, document_ids=document_ids)
