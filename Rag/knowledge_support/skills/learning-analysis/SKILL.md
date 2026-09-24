---
name: "learning-analysis"
description: "教师希望解释已分析的学情统计、识别薄弱知识点并提出补弱建议时使用。"
---

1. 调用 get_learning_summary 获取本次会话已经计算的汇总，不编造或推测成绩。
2. 没有摘要时请教师先到“学情分析”完成统计。
3. 比较知识点得分率和关注项，区分统计事实与教学建议；得分率不是学生平均掌握率。
4. 需要课程依据时调用 search_knowledge。用 save_draft 保存建议草稿。
