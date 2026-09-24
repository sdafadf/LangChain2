"""Validated Markdown skill library. Disk access belongs to the UI, not the agent."""
from dataclasses import dataclass
from pathlib import Path
import json
import os
import re
import tempfile

import yaml

MAX_SKILL_BYTES = 24000
MAX_REFERENCE_BYTES = 24000
ROLE_DIRS = {'教师端': 'teacher', '学生端': 'student'}
BUILTIN_ROLES = {
    'course-qa': ('教师端', '学生端'),
    'study-plan': ('教师端', '学生端'),
    'learning-analysis': ('教师端',),
    'teaching-design': ('教师端',),
    'admin-qa': ('教师端',),
    'office-draft': ('教师端',),
}


def validate_name(name):
    if not isinstance(name, str) or not re.fullmatch(r'[a-z][a-z0-9]*(?:-[a-z0-9]+)*', name) or len(name) > 48:
        raise ValueError('技能标识须为 1–48 位小写英文字母、数字或连字符，以字母开头。')
    if name.split('.')[0].upper() in {'CON', 'PRN', 'AUX', 'NUL', *(f'COM{i}' for i in range(1, 10)), *(f'LPT{i}' for i in range(1, 10))}:
        raise ValueError('请换一个技能标识，该名称被系统保留。')
    return name


def parse_skill(text):
    if not isinstance(text, str) or len(text.encode('utf-8')) > MAX_SKILL_BYTES or '\x00' in text:
        raise ValueError('SKILL.md 须为不超过 24 KB 的 UTF-8 文本。')
    normalized = text.lstrip('\ufeff').replace('\r\n', '\n')
    match = re.fullmatch(r'---\n(.*?)\n---\n(.*)', normalized, re.S)
    if not match:
        raise ValueError('SKILL.md 须以 --- 包围的 name、description 开头，随后填写技能步骤。')
    try:
        metadata = yaml.safe_load(match[1])
    except yaml.YAMLError:
        raise ValueError('技能头部 YAML 格式不正确。') from None
    if not isinstance(metadata, dict):
        raise ValueError('技能头部须包含 name 和 description。')
    name = validate_name(metadata.get('name'))
    description = metadata.get('description')
    if not isinstance(description, str) or not description.strip() or len(description) > 500:
        raise ValueError('触发描述须为 1–500 字。')
    body = match[2].strip()
    if not body or len(body) > 12000:
        raise ValueError('技能步骤须为 1–12000 字。')
    return name, description.strip(), body


def skill_text(name, description, body):
    # JSON strings are valid YAML scalars, preventing newline/frontmatter injection.
    text = f'---\nname: {json.dumps(name)}\ndescription: {json.dumps(description, ensure_ascii=False)}\n---\n\n{body.strip()}\n'
    parse_skill(text)
    return text


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    body: str
    origin: str
    enabled: bool = True
    reference: str = ''

    @property
    def text(self):
        return skill_text(self.name, self.description, self.body)

    @property
    def path(self):
        return f'/skills/{self.name}/SKILL.md'


def _atomic_write(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=path.parent, delete=False) as handle:
        temporary = Path(handle.name)
        handle.write(text)
    try:
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


class SkillLibrary:
    def __init__(self, root, role):
        if role not in ROLE_DIRS:
            raise ValueError('请先选择教师端或学生端。')
        self.root = Path(root).resolve()
        self.role = role
        self.user_root = self.root / 'data' / 'user_skills' / ROLE_DIRS[role]

    def _contained(self, path):
        resolved = path.resolve()
        if not resolved.is_relative_to(self.root):
            raise ValueError('技能路径必须位于应用目录内。')
        return resolved

    def _directory(self, name):
        validate_name(name)
        directory = self._contained(self.user_root / name)
        for filename in ('SKILL.md', 'settings.json', 'reference.md'):
            self._contained(directory / filename)
        return directory

    def list(self):
        skills, errors = [], []
        for origin, directory in [('内置', self.root / 'skills'), ('自定义', self.user_root)]:
            directory = self._contained(directory)
            if not directory.exists():
                continue
            for path in sorted(directory.glob('*/SKILL.md')):
                if origin == '内置' and self.role not in BUILTIN_ROLES.get(path.parent.name, ()):
                    continue
                try:
                    path = self._contained(path)
                    if path.stat().st_size > MAX_SKILL_BYTES:
                        raise ValueError('文件超过 24 KB。')
                    name, description, body = parse_skill(path.read_text(encoding='utf-8-sig'))
                    if name != path.parent.name:
                        raise ValueError('技能标识与目录名不一致。')
                    if origin == '自定义' and name in BUILTIN_ROLES:
                        raise ValueError('自定义技能不能覆盖内置技能。')
                    enabled, reference = True, ''
                    if origin == '自定义':
                        settings = self._contained(path.parent / 'settings.json')
                        if settings.exists():
                            if settings.stat().st_size > 1000:
                                raise ValueError('技能状态文件异常。')
                            enabled = json.loads(settings.read_text(encoding='utf-8'))['enabled']
                            if not isinstance(enabled, bool):
                                raise ValueError('启用状态无效。')
                        reference_path = self._contained(path.parent / 'reference.md')
                        if reference_path.exists():
                            if reference_path.stat().st_size > MAX_REFERENCE_BYTES:
                                raise ValueError('参考文本超过 24 KB。')
                            reference = reference_path.read_text(encoding='utf-8')
                    skills.append(Skill(name, description, body, origin, enabled, reference))
                except (ValueError, OSError, KeyError, TypeError):
                    errors.append(f'无法加载 {origin}技能 {path.parent.name}，请检查格式和文件大小。')
        return skills, errors

    def save(self, name, description, body, enabled=True, reference=''):
        text = skill_text(name, description, body)
        if name in BUILTIN_ROLES:
            raise ValueError('内置技能只读，请使用新的技能标识保存副本。')
        if not isinstance(enabled, bool):
            raise ValueError('启用状态无效。')
        if not isinstance(reference, str) or len(reference.encode('utf-8')) > MAX_REFERENCE_BYTES or '\x00' in reference:
            raise ValueError('参考文本须为不超过 24 KB 的文本。')
        directory = self._directory(name)
        # Each file replaces atomically; a running task already owns an immutable snapshot.
        _atomic_write(directory / 'reference.md', reference)
        _atomic_write(directory / 'SKILL.md', text)
        _atomic_write(directory / 'settings.json', json.dumps({'enabled': enabled}))
        return Skill(name, description.strip(), body.strip(), '自定义', enabled, reference)

    def snapshot(self, selected=None):
        skills, errors = self.list()
        if errors:
            raise ValueError('；'.join(errors))
        skills = [skill for skill in skills if skill.enabled]
        if selected is not None:
            skills = [skill for skill in skills if skill.name == selected]
            if not skills:
                raise ValueError('所选技能不存在或已停用，请刷新后重新选择。')
        if len(skills) > 40:
            raise ValueError('一次最多启用 40 个技能，请停用暂时不需要的技能。')
        return skills
