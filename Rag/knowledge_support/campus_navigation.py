"""Declarative page registration shared by navigation and lazy dispatch."""
from dataclasses import dataclass, field
from importlib import import_module
from typing import Mapping


@dataclass(frozen=True)
class Page:
    title: str
    roles: tuple[str, ...]
    module: str
    handler: str
    options: Mapping = field(default_factory=dict)
    menu: bool = True

    def render(self, context):
        return getattr(import_module(self.module), self.handler)(context, **self.options)


class PageRegistry:
    def __init__(self, pages):
        self._pages = {}
        for page in pages:
            if page.title in self._pages:
                raise ValueError(f'重复页面：{page.title}')
            self._pages[page.title] = page

    def navigation(self, role):
        return [page.title for page in self._pages.values()
                if page.menu and role in page.roles]

    def resolve(self, role, title):
        page = self._pages.get(title)
        return page if page and role in page.roles else None


PAGES = PageRegistry([
    Page('教学首页', ('教师端',), 'campus_roles', 'role_home', {'role': '教师端'}),
    Page('学情分析', ('教师端',), 'campus_pages', 'teaching', {'section': '学情分析'}),
    Page('备课与练习', ('教师端',), 'campus_roles', 'preparation_page'),
    Page('教学资料', ('教师端',), 'campus_pages', 'knowledge_center'),
    Page('办公工具', ('教师端',), 'campus_pages', 'office'),
    Page('学习首页', ('学生端',), 'campus_roles', 'role_home', {'role': '学生端'}),
    Page('课程答疑', ('学生端',), 'campus_roles', 'course_answer_page'),
    Page('我的练习', ('学生端',), 'campus_roles', 'practice_page'),
    Page('学习资料', ('学生端',), 'campus_roles', 'learning_materials'),
    Page('我的资料', ('学生端',), 'campus_personal_page', 'personal_files'),
    Page('智能任务', ('教师端', '学生端'), 'campus_agent_page', 'smart_tasks'),
    Page('我的技能', ('教师端', '学生端'), 'campus_agent_page', 'skill_manager'),
    Page('系统设置', ('教师端',), 'campus_settings_page', 'settings_page', menu=False),
])
