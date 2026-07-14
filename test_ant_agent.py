import unittest
import os
import tempfile
import pathlib
from pathlib import Path
from ant_agent.config import DEFAULT_CONFIG
import ant_agent.config
from ant_agent.memory import SimpleVectorDB
from ant_agent.agent import AntAgent
from ant_agent import tools

class TestAntAgent(unittest.TestCase):
    def setUp(self):
        self.orig_cwd = os.getcwd()
        self.temp_dir = tempfile.TemporaryDirectory()
        
        # Keep references to original paths
        self.orig_home = pathlib.Path.home
        self.orig_oneb_dir = ant_agent.config.ANT_AGENT_DIR
        self.orig_config_path = ant_agent.config.CONFIG_PATH
        self.orig_memory_path = ant_agent.config.MEMORY_PATH
        self.orig_todo_path = ant_agent.config.TODO_PATH
        
        # Monkeypatch Path.home
        pathlib.Path.home = lambda: Path(self.temp_dir.name)
        
        # Override config paths
        ant_agent.config.ANT_AGENT_DIR = Path(self.temp_dir.name) / ".ant_agent"
        ant_agent.config.CONFIG_PATH = Path(self.temp_dir.name) / ".ant_agent" / "config.json"
        ant_agent.config.MEMORY_PATH = Path(self.temp_dir.name) / ".ant_agent" / "memory.json"
        ant_agent.config.TODO_PATH = Path(self.temp_dir.name) / ".ant_agent" / "todo.json"
        
        # Change current working directory to temp dir
        os.chdir(self.temp_dir.name)

        # Create a mock/test configuration
        self.config = DEFAULT_CONFIG.copy()
        self.config["embedding_provider"] = "mock"
        self.config["llm_api_key"] = "mock"
        self.config["global_memory_file"] = Path(self.temp_dir.name) / ".ant_agent" / "global_memory.json"
        self.agent = AntAgent(self.config)

    def tearDown(self):
        # Restore home and config paths
        pathlib.Path.home = self.orig_home
        ant_agent.config.ANT_AGENT_DIR = self.orig_oneb_dir
        ant_agent.config.CONFIG_PATH = self.orig_config_path
        ant_agent.config.MEMORY_PATH = self.orig_memory_path
        ant_agent.config.TODO_PATH = self.orig_todo_path
        
        # Restore CWD
        os.chdir(self.orig_cwd)
        self.temp_dir.cleanup()

    def test_xml_parsing(self):
        # Test standard parsing
        text = "<tool_call><function=python_repl><parameter>print(1 + 1)</parameter></function></tool_call>"
        name, param = self.agent.parse_tool_call(text)
        self.assertEqual(name, "python_repl")
        self.assertEqual(param, "print(1 + 1)")

        # Test tool call with newlines
        text = """Some conversational text...
<tool_call>
<function=filesystem_write>
<parameter>test.txt
=== CONTENT ===
hello world</parameter>
</function>
</tool_call>
and some trailing text."""
        name, param = self.agent.parse_tool_call(text)
        self.assertEqual(name, "filesystem_write")
        self.assertEqual(param, "test.txt\n=== CONTENT ===\nhello world")

        # Test tool call with custom </param> closing tag
        text = "<tool_call><function=web_search><parameter>president of india</param></function></tool_call>"
        name, param = self.agent.parse_tool_call(text)
        self.assertEqual(name, "web_search")
        self.assertEqual(param, "president of india")

        # Test tool call with function name attribute and paramParameter tags
        text = "<function name=web_search><paramParameter>current president of india</Parameter></function></tool_call>"
        name, param = self.agent.parse_tool_call(text)
        self.assertEqual(name, "web_search")
        self.assertEqual(param, "current president of india")

        # Test no tool call
        text = "Hello, how can I help you today?"
        name, param = self.agent.parse_tool_call(text)
        self.assertIsNone(name)
        self.assertIsNone(param)

    def test_vector_db_mock(self):
        db = SimpleVectorDB(self.config, memory_file=Path(self.temp_dir.name) / "test_memory.json")
        # Clear database records
        db.data = []
        
        db.store("The quick brown fox jumps over the lazy dog.")
        db.store("Artificial Intelligence and Machine Learning are transforming industries.")
        db.store("I love eating delicious pizza with cheese.")

        # Recall using keyword overlap
        results = db.recall("intelligent machine", limit=1)
        self.assertEqual(len(results), 1)
        self.assertIn("Artificial Intelligence", results[0]["text"])

        # Recall another topic
        results = db.recall("tasty food cheese", limit=1)
        self.assertEqual(len(results), 1)
        self.assertIn("delicious pizza", results[0]["text"])

    def test_core_tools(self):
        # test token_counter
        tool = tools.get_tool("token_counter")
        res = tool.execute("hello world")
        self.assertTrue("Token count:" in res)

        # test plan_and_todo
        tool = tools.get_tool("plan_and_todo")
        tool.execute("clear")
        res = tool.execute("add Buy milk")
        self.assertIn("Buy milk", res)
        res = tool.execute("list")
        self.assertIn("Buy milk", res)
        self.assertIn("0:", res)
        res = tool.execute("complete 0")
        self.assertIn("Completed task", res)

        # test memory tools
        self.agent.global_db.data = []
        self.agent.workspace_db.data = []
        store_tool = tools.get_tool("vector_memory_store", self.agent)
        
        # Test global routing
        store_tool.execute("The user's favorite color is blue.")
        self.assertEqual(len(self.agent.global_db.data), 1)
        self.assertEqual(len(self.agent.workspace_db.data), 0)

        # Test workspace routing
        store_tool.execute("The go code repository is active.")
        self.assertEqual(len(self.agent.workspace_db.data), 1)

        recall_tool = tools.get_tool("vector_memory_recall", self.agent)
        recall_res = recall_tool.execute("favorite color")
        self.assertIn("favorite color is blue", recall_res)
        
        recall_res2 = recall_tool.execute("go repository")
        self.assertIn("go code repository", recall_res2)

        # test conversation summarizer tool
        summarizer_tool = tools.get_tool("conversation_summarizer", self.agent)
        self.agent.history = [
            {"role": "user", "content": "Hello"},
            {"role": "assistant", "content": "Hi there!"}
        ]
        # mock LLM response
        self.agent.query_llm = lambda p, system_override=None: "Summary of hello greeting."
        summarize_res = summarizer_tool.execute("")
        self.assertEqual(summarize_res, "Summary of hello greeting.")

        # test decompose_task tool
        decompose_tool = tools.get_tool("decompose_task", self.agent)
        self.agent.query_llm = lambda p, system_override=None: "Step 1: Do X\nStep 2: Do Y"
        decompose_res = decompose_tool.execute("Build a house")
        self.assertEqual(decompose_res, "Step 1: Do X\nStep 2: Do Y")

        # test ask_clarifying_questions tool
        ask_tool = tools.get_tool("ask_clarifying_questions", self.agent)
        ask_res = ask_tool.execute("What color?")
        self.assertIn("What color?", ask_res)

    def test_filesystem_tools(self):
        # test write
        write_tool = tools.get_tool("filesystem_write")
        write_res = write_tool.execute("test_write.txt\n=== CONTENT ===\ncontent of the test file")
        self.assertIn("Successfully wrote", write_res)

        # test read
        read_tool = tools.get_tool("filesystem_read")
        read_res = read_tool.execute("test_write.txt")
        self.assertEqual(read_res, "content of the test file")

        # test edit
        edit_tool = tools.get_tool("filesystem_edit")
        edit_res = edit_tool.execute("test_write.txt\n=== SEARCH ===\ncontent of the test file\n=== REPLACE ===\nupdated content")
        self.assertIn("Successfully edited", edit_res)

        # check edit result
        read_res = read_tool.execute("test_write.txt")
        self.assertEqual(read_res, "updated content")

        # test delete
        delete_tool = tools.get_tool("filesystem_delete")
        delete_res = delete_tool.execute("test_write.txt")
        self.assertIn("Successfully deleted", delete_res)

    def test_native_tool_calling(self):
        self.config["tool_calling_method"] = "native"
        agent = AntAgent(self.config)
        
        # Test schemas generation
        schemas = agent.get_tool_schemas()
        self.assertTrue(len(schemas) > 0)
        self.assertEqual(schemas[0]["type"], "function")
        self.assertIn("parameter", schemas[0]["function"]["parameters"]["properties"])
        
        # Mock LLM response with tool call
        class MockFunction:
            def __init__(self):
                self.name = "token_counter"
                self.arguments = '{"parameter": "test message"}'
        class MockToolCall:
            def __init__(self):
                self.id = "call_abc123"
                self.type = "function"
                self.function = MockFunction()
        class MockMessage:
            def __init__(self):
                self.content = None
                self.tool_calls = [MockToolCall()]
        class MockChoice:
            def __init__(self):
                self.message = MockMessage()
        class MockCompletionsResponse:
            def __init__(self):
                self.choices = [MockChoice()]

        # We will mock client.chat.completions.create to return the tool call first,
        # then a final response.
        call_count = 0
        def mock_create(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return MockCompletionsResponse()
            else:
                # Final response
                class FinalMessage:
                    def __init__(self):
                        self.content = "Finished reasoning."
                        self.tool_calls = None
                class FinalChoice:
                    def __init__(self):
                        self.message = FinalMessage()
                class FinalResponse:
                    def __init__(self):
                        self.choices = [FinalChoice()]
                return FinalResponse()

        agent.client.chat.completions.create = mock_create
        res = agent.run_cycle("hi", verbose=False)
        self.assertEqual(res, "Finished reasoning.")
        self.assertEqual(call_count, 2)
        # Check that the history contains correct structured native messages
        self.assertEqual(agent.history[1]["role"], "assistant")
        self.assertTrue("tool_calls" in agent.history[1])
        self.assertEqual(agent.history[2]["role"], "tool")
        self.assertEqual(agent.history[2]["tool_call_id"], "call_abc123")

if __name__ == "__main__":
    unittest.main()
