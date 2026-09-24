"""Offline tests: actual LangGraph memory/tool loop with a scripted chat model."""
import os
os.environ["LANGSMITH_TRACING"] = "false"
os.environ["LANGCHAIN_TRACING_V2"] = "false"
import unittest
from unittest.mock import Mock
from pydantic import Field
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from backend import Settings, KnowledgeBase
from support_agent import SupportConversation


class ScriptedModel(FakeMessagesListChatModel):
    seen: list = Field(default_factory=list)
    fail_next: bool = False

    def bind_tools(self, tools, **kwargs):
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        self.seen.append(list(messages))
        if self.fail_next:
            self.fail_next = False
            raise ConnectionError("test model unavailable")
        return super()._generate(messages, stop=stop, run_manager=run_manager, **kwargs)


def search(query, call_id):
    return AIMessage(content="", tool_calls=[
        {"name": "search_knowledge", "args": {"query": query}, "id": call_id}
    ])


class ConversationTests(unittest.TestCase):
    def make_conversation(self, responses, hits=None):
        model = ScriptedModel(responses=responses)
        kb = KnowledgeBase(Settings())
        kb.retrieve = Mock(return_value=hits or [])
        conversation = SupportConversation(Settings(), model=model, kb=kb)
        self.addCleanup(conversation.close)
        return conversation, model, kb

    def test_memory_and_history_aware_tool(self):
        conversation, model, kb = self.make_conversation([
            AIMessage(content="你是什么时候购买的？"),
            search("购买课程三天后退款有哪些条件？", "call1"),
            AIMessage(content="请参考退款条件。[资料1]"),
        ], [{"text": "退款须按规定办理", "source": "a.txt", "chunk_id": 0, "score": 0.8}])
        first = conversation.ask("我想退款")
        thread = conversation.thread_id
        self.assertEqual(first["sources"], [])
        second = conversation.ask("三天前")
        self.assertEqual(conversation.thread_id, thread)
        kb.retrieve.assert_called_once_with("购买课程三天后退款有哪些条件？", 5)
        self.assertEqual(second["sources"][0]["reference"], "资料1")
        state = conversation.agent.get_state({"configurable": {"thread_id": thread}})
        users = [m.content for m in state.values["messages"] if isinstance(m, HumanMessage)]
        self.assertEqual(users, ["我想退款", "三天前"])
        self.assertTrue(any(m.content == "你是什么时候购买的？" for m in model.seen[1]))
        self.assertTrue(any(isinstance(m, ToolMessage) for m in state.values["messages"]))

    def test_conversation_isolation(self):
        a, _, _ = self.make_conversation([AIMessage(content="已了解")])
        b, model_b, _ = self.make_conversation([AIMessage(content="你好")])
        a.ask("我的课程是Python")
        b.ask("你好")
        self.assertNotEqual(a.thread_id, b.thread_id)
        self.assertFalse(any("Python" in str(m.content) for m in model_b.seen[0]))

    def test_model_error_recovery_preserves_successful_history(self):
        conversation, model, _ = self.make_conversation([AIMessage(content="请问购买时间？"), AIMessage(content="已了解")])
        conversation.ask("我想退款")
        model.fail_next = True
        with self.assertRaises(ConnectionError):
            conversation.ask("三天前")
        conversation.ask("三天前")
        users = [m.content for m in model.seen[-1] if isinstance(m, HumanMessage)]
        self.assertEqual(users, ["我想退款", "三天前"])

    def test_tool_error_then_retry(self):
        conversation, model, kb = self.make_conversation([
            search("退款条件", "failed"), search("退款条件", "retry"), AIMessage(content="资料不足")
        ])
        kb.retrieve.side_effect = [ConnectionError("test database unavailable"), []]
        with self.assertRaises(ConnectionError):
            conversation.ask("退款条件")
        result = conversation.ask("退款条件")
        self.assertEqual(result["sources"], [])
        users = [m.content for m in model.seen[-1] if isinstance(m, HumanMessage)]
        self.assertEqual(users, ["退款条件"])

    def test_historical_citation_is_still_available(self):
        conversation, _, _ = self.make_conversation([
            search("规则", "c1"), AIMessage(content="规则见[资料1]"),
            AIMessage(content="上轮参考资料是[资料1]"),
        ], [{"text": "规则", "source": "a.txt", "chunk_id": 0, "score": 0.8}])
        conversation.ask("有哪些规则")
        result = conversation.ask("刚才引用了哪里")
        self.assertEqual(result["sources"][0]["reference"], "资料1")

    def test_close_removes_memory(self):
        conversation, _, _ = self.make_conversation([AIMessage(content="你好")])
        conversation.ask("你好")
        config = {"configurable": {"thread_id": conversation.thread_id}}
        self.assertIsNotNone(conversation.memory.get_tuple(config))
        conversation.close()
        self.assertIsNone(conversation.memory.get_tuple(config))


if __name__ == "__main__":
    unittest.main()
