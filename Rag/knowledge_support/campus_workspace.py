"""Small pure helpers for current-session work products and task handoffs."""
from hashlib import sha256
from datetime import datetime
from uuid import uuid4


def remember_draft(state, draft, task=None):
    """Store the result and select it only within its owning task."""
    state.setdefault('drafts', []).insert(0, draft)
    category = draft['category']
    if task is None:
        state['active_' + category] = draft['id']
    else:
        draft['task'] = task
        state.setdefault('active_drafts', {}).setdefault(category, {})[task] = draft['id']


def selected_draft(state, category, task=None):
    drafts = state.get('drafts', [])
    if task is None:
        ident = state.get('active_' + category)
        return next((d for d in drafts if d['id'] == ident and d['category'] == category), None)
    ident = state.get('active_drafts', {}).get(category, {}).get(task)
    # Older office drafts used the task title, without explicit task metadata.
    matches = [d for d in drafts if d['category'] == category
               and d.get('task', d['title']) == task]
    return next((d for d in matches if d['id'] == ident), next(iter(matches), None))


def input_fingerprint(content, duplicates, threshold):
    return sha256(content + str((duplicates, threshold)).encode()).hexdigest()


def make_draft(title, category, content, source_signature='', sources=None):
    return {'id':uuid4().hex, 'title':title, 'category':category,
            'content':content, 'created':datetime.now().strftime('%H:%M'),
            'source_signature':source_signature, 'sources':sources or []}


def focus_topics(report):
    return '、'.join(row['知识点'] for row in report['知识点'] if row['需关注']) or '知识迁移与综合应用'
