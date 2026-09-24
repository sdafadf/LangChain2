---
name: "course-qa"
description: "课程概念讲解、课程问题答疑、提示引导和自测题，依据课程原文回答。"
---

1. 确认问题，必要时用 list_documents 查看资料目录。
2. 调用 search_knowledge，category 为“课程”。
3. 按用户要求讲解或给提示，结论标注工具返回的 [资料N]。资料不足时明确说明。
4. 自测题标为生成练习建议；历史回答不是原文依据。需要时用 save_draft 保存学习摘录。
