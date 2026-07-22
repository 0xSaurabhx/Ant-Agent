import unittest
import os
import json
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
        self.orig_stats_path = getattr(ant_agent.config, "STATS_PATH", None)
        
        # Monkeypatch Path.home
        pathlib.Path.home = lambda: Path(self.temp_dir.name)
        
        # Override config paths
        ant_agent.config.ANT_AGENT_DIR = Path(self.temp_dir.name) / ".ant_agent"
        ant_agent.config.CONFIG_PATH = Path(self.temp_dir.name) / ".ant_agent" / "config.json"
        ant_agent.config.MEMORY_PATH = Path(self.temp_dir.name) / ".ant_agent" / "memory.json"
        ant_agent.config.TODO_PATH = Path(self.temp_dir.name) / ".ant_agent" / "todo.json"
        ant_agent.config.STATS_PATH = Path(self.temp_dir.name) / ".ant_agent" / "stats.json"
        
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
        if self.orig_stats_path is not None:
            ant_agent.config.STATS_PATH = self.orig_stats_path
        
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
        self.agent.query_llm = lambda *args, **kwargs: "Summary of hello greeting."
        summarize_res = summarizer_tool.execute("")
        self.assertEqual(summarize_res, "Summary of hello greeting.")

        decompose_tool = tools.get_tool("decompose_task", self.agent)
        self.agent.query_llm = lambda *args, **kwargs: "Step 1: Do X\nStep 2: Do Y"
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
        
        # Mock triage and decomposition
        agent.triage_request = lambda x: {"route": "planner", "explanation": "test"}
        original_get_tool = tools.get_tool
        def mock_get_tool(name, agent_context=None):
            if name == "decompose_task":
                class MockDecomposeTool:
                    def execute(self, param):
                        return "1. run token_counter"
                return MockDecomposeTool()
            return original_get_tool(name, agent_context)
        tools.get_tool = mock_get_tool
        
        try:
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

            call_count = 0
            def mock_create(*args, **kwargs):
                nonlocal call_count
                call_count += 1
                if call_count == 1:
                    return MockCompletionsResponse()
                else:
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
        finally:
            tools.get_tool = original_get_tool

    def test_triage_request_direct(self):
        agent = AntAgent(self.config)
        agent.query_triage_llm = lambda prompt, system_override: '{"route": "direct", "tool": "code_runner_with_tests", "parameter": "pm2 restart app", "explanation": "Restarting PM2 is simple"}'
        result = agent.triage_request("restart PM2")
        self.assertEqual(result["route"], "direct")
        self.assertEqual(result["tool"], "code_runner_with_tests")
        self.assertEqual(result["parameter"], "pm2 restart app")

    def test_triage_request_analysis(self):
        agent = AntAgent(self.config)
        agent.query_triage_llm = lambda prompt, system_override: '{"route": "analysis", "tool": null, "parameter": null, "explanation": "Explain architecture needs analysis"}'
        result = agent.triage_request("explain how agent executes task")
        self.assertEqual(result["route"], "analysis")
        self.assertIsNone(result["tool"])

    def test_triage_request_planner(self):
        agent = AntAgent(self.config)
        agent.query_triage_llm = lambda prompt, system_override: '{"route": "planner", "tool": null, "parameter": null, "explanation": "Building API is complex"}'
        result = agent.triage_request("build a full CRUD API")
        self.assertEqual(result["route"], "planner")
        self.assertIsNone(result["tool"])

    def test_run_cycle_direct_execution_with_tool(self):
        agent = AntAgent(self.config)
        agent.triage_request = lambda x: {
            "route": "direct",
            "tool": "token_counter",
            "parameter": "hello triage",
            "explanation": "Simple token counting"
        }
        # Mock summary LLM call
        agent.query_llm = lambda *args, **kwargs: "Direct summary response."
        
        res = agent.run_cycle("count tokens in 'hello triage'", verbose=False)
        self.assertEqual(res, "Direct summary response.")
        
        # Verify tool execution was logged in history
        self.assertEqual(agent.history[0]["role"], "user")
        self.assertEqual(agent.history[1]["role"], "assistant")
        self.assertTrue("tool_calls" in agent.history[1] or "<tool_call>" in str(agent.history[1].get("content")))
        self.assertEqual(agent.history[2]["role"], "tool" if agent.config.get("tool_calling_method") == "native" else "user")

    def test_read_file_lines(self):
        test_file = Path("test_lines.txt")
        test_file.write_text("line 1\nline 2\nline 3\nline 4\nline 5\n")
        
        try:
            tool = tools.get_tool("read_file_lines")
            
            res = tool.execute("test_lines.txt:2-4")
            self.assertEqual(res, "2: line 2\n3: line 3\n4: line 4\n")
            
            res = tool.execute("test_lines.txt:4-10")
            self.assertEqual(res, "4: line 4\n5: line 5\n")
            
            res = tool.execute("test_lines.txt")
            self.assertTrue(res.startswith("Error:"))
            
            res = tool.execute("test_lines.txt:10-20")
            self.assertTrue(res.startswith("Error:"))
            
            # Test range exceeding 50 lines
            long_file = Path("test_long.txt")
            long_file.write_text("\n".join(f"line {i}" for i in range(1, 100)) + "\n")
            try:
                res_exceed = tool.execute("test_long.txt:1-60")
                self.assertTrue("Error: You can read at most 50 lines" in res_exceed)
            finally:
                if long_file.exists():
                    long_file.unlink()
        finally:
            if test_file.exists():
                test_file.unlink()

    def test_generate_repo_map(self):
        test_py = Path("mock_source.py")
        test_py.write_text("class TestClass:\n    def test_method(self):\n        pass\n\ndef test_func():\n    pass\n")
        
        try:
            tool = tools.get_tool("generate_repo_map")
            res = tool.execute("")
            
            self.assertTrue("mock_source.py" in res)
            self.assertTrue("TestClass" in res)
            self.assertTrue("test_method" in res)
            self.assertTrue("test_func" in res)
        finally:
            if test_py.exists():
                test_py.unlink()

    def test_save_session_with_dict_tool_calls(self):
        agent = AntAgent(self.config)
        agent.history = [
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_123",
                        "type": "function",
                        "function": {
                            "name": "web_search",
                            "arguments": '{"parameter": "test"}'
                        }
                    }
                ]
            }
        ]
        
        try:
            agent.save_session()
            self.assertTrue(agent.session_file.exists())
            with open(agent.session_file, "r") as f:
                data = json.load(f)
                history = data.get("history", [])
                self.assertEqual(len(history), 1)
                self.assertEqual(history[0]["tool_calls"][0]["id"], "call_123")
                self.assertEqual(history[0]["tool_calls"][0]["function"]["name"], "web_search")
        finally:
            if agent.session_file.exists():
                agent.session_file.unlink()

    def test_triage_planner_strips_thoughts(self):
        agent = AntAgent(self.config)
        agent.query_triage_llm = lambda prompt, system_override: '{"route": "planner", "tool": null, "parameter": null, "explanation": "complex"}'
        
        original_get_tool = tools.get_tool
        
        class MockDecomposeTool:
            def execute(self, parameter):
                return "<thought>\n* Meta-thought 1\n* Meta-thought 2\n</thought>\n1. Step One\n2. Step Two"
                
        def mock_get_tool(name, context=None):
            if name == "decompose_task":
                return MockDecomposeTool()
            return original_get_tool(name, context)
            
        tools.get_tool = mock_get_tool
        try:
            agent.query_llm = lambda *args, **kwargs: (None, None)
            
            try:
                agent.run_cycle("do something complex", verbose=False)
            except Exception:
                pass
                
            todo_path = Path(".ant_agent/todo.json")
            if todo_path.exists():
                with open(todo_path, "r") as f:
                    todos = json.load(f)
                todo_texts = [t["desc"] for t in todos]
                self.assertTrue("Step One" in todo_texts)
                self.assertTrue("Step Two" in todo_texts)
                self.assertFalse("Meta-thought 1" in todo_texts)
                self.assertFalse("Meta-thought 2" in todo_texts)
        finally:
            tools.get_tool = original_get_tool
            todo_path = Path(".ant_agent/todo.json")
            if todo_path.exists():
                todo_path.unlink()

    def test_continuation_skips_decomposition(self):
        agent = AntAgent(self.config)
        
        todo_path = Path(".ant_agent/todo.json")
        todo_path.parent.mkdir(parents=True, exist_ok=True)
        with open(todo_path, "w") as f:
            json.dump([
                {"desc": "First Task", "done": False},
                {"desc": "Second Task", "done": False}
            ], f)
            
        triage_called = False
        def mock_triage(user_input):
            nonlocal triage_called
            triage_called = True
            return {"route": "direct", "tool": None, "parameter": None}
        agent.triage_request = mock_triage
        
        decompose_called = False
        original_get_tool = tools.get_tool
        class MockDecomposeTool:
            def execute(self, parameter):
                nonlocal decompose_called
                decompose_called = True
                return "1. New task from decomposition"
        def mock_get_tool(name, context=None):
            if name == "decompose_task":
                return MockDecomposeTool()
            return original_get_tool(name, context)
        tools.get_tool = mock_get_tool
        
        try:
            agent.query_llm = lambda *args, **kwargs: "Done."
            
            agent.run_cycle("continue", verbose=False)
            
            self.assertFalse(triage_called)
            self.assertFalse(decompose_called)
            
            with open(todo_path, "r") as f:
                todos = json.load(f)
            self.assertEqual(len(todos), 2)
            self.assertEqual(todos[0]["desc"], "First Task")
        finally:
            tools.get_tool = original_get_tool
            if todo_path.exists():
                todo_path.unlink()

    def test_query_llm_with_history(self):
        agent = AntAgent(self.config)
        agent.history = [
            {"role": "user", "content": "hello agent"},
            {"role": "assistant", "content": "hello user"}
        ]
        
        passed_messages = None
        def mock_create(*args, **kwargs):
            nonlocal passed_messages
            passed_messages = kwargs.get("messages")
            class MockMessage:
                content = "Response from mock model"
            class MockChoice:
                message = MockMessage()
            class MockResponse:
                choices = [MockChoice()]
            return MockResponse()
            
        agent.client.chat.completions.create = mock_create
        
        agent.query_llm(prompt="tell me more", use_history=True)
        
        self.assertIsNotNone(passed_messages)
        self.assertEqual(passed_messages[0]["role"], "system")
        self.assertEqual(passed_messages[1]["role"], "user")
        self.assertEqual(passed_messages[1]["content"], "hello agent")
        self.assertEqual(passed_messages[2]["role"], "assistant")
        self.assertEqual(passed_messages[2]["content"], "hello user")
        self.assertEqual(passed_messages[3]["role"], "user")
        self.assertEqual(passed_messages[3]["content"], "tell me more")

    def test_get_clean_history_messages(self):
        agent = AntAgent(self.config)
        large_content = "X" * 1500
        
        agent.history = [
            {"role": "user", "content": "Initial user message"},
            {"role": "tool", "content": large_content},
            {"role": "assistant", "content": large_content},
            {"role": "user", "content": large_content},
            {"role": "assistant", "content": large_content},
            {"role": "tool", "content": large_content}
        ]
        
        clean_msgs = agent.get_clean_history_messages()
        
        self.assertEqual(len(clean_msgs), 6)
        self.assertEqual(clean_msgs[0]["content"], "Initial user message")
        self.assertEqual(clean_msgs[1]["content"], large_content)
        self.assertEqual(clean_msgs[2]["content"], large_content)
        self.assertEqual(clean_msgs[3]["content"], large_content)
        self.assertEqual(clean_msgs[4]["content"], large_content)
        self.assertEqual(clean_msgs[5]["content"], large_content)

    def test_get_clean_history_messages_serializes_mock_tool_calls(self):
        agent = AntAgent(self.config)
        class MockFunction:
            def __init__(self):
                self.name = "token_counter"
                self.arguments = '{"parameter": "test"}'
        class MockToolCall:
            def __init__(self):
                self.id = "mock_call_1"
                self.type = "function"
                self.function = MockFunction()
                self.model_extra = {"extra_content": {"google": {"thought_signature": "signature_abc"}}}
                
        agent.history = [
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [MockToolCall()]
            }
        ]
        
        clean_msgs = agent.get_clean_history_messages()
        self.assertEqual(len(clean_msgs), 1)
        self.assertTrue(isinstance(clean_msgs[0]["tool_calls"][0], dict))
        self.assertEqual(clean_msgs[0]["tool_calls"][0]["id"], "mock_call_1")
        self.assertEqual(clean_msgs[0]["tool_calls"][0]["function"]["name"], "token_counter")
        self.assertEqual(clean_msgs[0]["tool_calls"][0]["extra_content"]["google"]["thought_signature"], "signature_abc")

    def test_direct_execution_includes_mock_thought(self):
        agent = AntAgent(self.config)
        agent.triage_request = lambda prompt: {
            "route": "direct",
            "tool": "token_counter",
            "parameter": "hello serialize test",
            "explanation": "triage direct"
        }
        agent.query_llm = lambda prompt, system_override, use_history: "direct execution summary"
        
        agent.run_cycle("count tokens", verbose=False)
        
        assistant_msgs = [m for m in agent.history if m["role"] == "assistant" and m.get("tool_calls")]
        self.assertEqual(len(assistant_msgs), 1)
        self.assertEqual(assistant_msgs[0]["content"], "<think>Executing tool directly based on triage routing.</think>")
        
        if agent.session_file.exists():
            agent.session_file.unlink()

    def test_triage_request_planner_for_code_analysis(self):
        agent = AntAgent(self.config)
        agent.query_triage_llm = lambda prompt, system_override: '{"route": "planner", "tool": null, "parameter": null, "explanation": "Analyzing codebase flow requires planning"}'
        result = agent.triage_request("can analyze agent.py and tell me if there is any severe issues or flow in this project")
        self.assertEqual(result["route"], "planner")
        self.assertIsNone(result["tool"])

    def test_get_clean_history_messages_injects_thought_signature(self):
        agent = AntAgent(self.config)
        agent.history = [
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "tc1",
                        "type": "function",
                        "function": {
                            "name": "generate_repo_map",
                            "arguments": ""
                        }
                    }
                ]
            }
        ]
        
        clean_msgs = agent.get_clean_history_messages()
        self.assertEqual(len(clean_msgs), 1)
        self.assertTrue("<think>Executing tool calls.</think>" in clean_msgs[0]["content"])



    def test_usage_tracking(self):
        # Initial stats should not exist or be empty
        from ant_agent.config import STATS_PATH
        self.assertFalse(STATS_PATH.exists())
        
        # Track some usage
        self.agent.track_usage("gemma-4-26b-a4b-it", 100, 50)
        
        # Verify global file contents
        self.assertTrue(STATS_PATH.exists())
        with open(STATS_PATH, "r") as f:
            stats = json.load(f)
            
        self.assertEqual(stats["total_prompt_tokens"], 100)
        self.assertEqual(stats["total_completion_tokens"], 50)
        self.assertEqual(stats["total_total_tokens"], 150)
        
        gemma_stats = stats["models"]["gemma-4-26b-a4b-it"]
        self.assertEqual(gemma_stats["prompt_tokens"], 100)
        self.assertEqual(gemma_stats["completion_tokens"], 50)
        self.assertEqual(gemma_stats["total_tokens"], 150)
        
        # Track more usage with the same model
        self.agent.track_usage("gemma-4-26b-a4b-it", 200, 100)
        
        with open(STATS_PATH, "r") as f:
            stats = json.load(f)
            
        self.assertEqual(stats["total_prompt_tokens"], 300)
        self.assertEqual(stats["total_completion_tokens"], 150)
        self.assertEqual(stats["total_total_tokens"], 450)
        
        # Track usage with a different model
        self.agent.track_usage("gpt-4o", 50, 10)
        
        with open(STATS_PATH, "r") as f:
            stats = json.load(f)
            
        self.assertEqual(stats["total_prompt_tokens"], 350)
        self.assertEqual(stats["total_completion_tokens"], 160)
        self.assertEqual(stats["total_total_tokens"], 510)
        
        self.assertEqual(stats["models"]["gpt-4o"]["prompt_tokens"], 50)
        self.assertEqual(stats["models"]["gpt-4o"]["completion_tokens"], 10)

    def test_reconcile_resumed_session(self):
        # 1. Create a mock session file representing a session created before
        # global stats tracking was introduced. It will have prompt/completion
        # tokens but NO session_tracked_prompt_tokens.
        from ant_agent.config import STATS_PATH
        session_id = "test_resume_reconcile_123"
        session_file = Path(self.temp_dir.name) / ".ant_agent" / "sessions" / f"{session_id}.json"
        session_file.parent.mkdir(parents=True, exist_ok=True)
        
        with open(session_file, "w") as f:
            json.dump({
                "uuid": session_id,
                "history": [],
                "session_prompt_tokens": 1200,
                "session_completion_tokens": 300,
                "timestamp": "2026-07-16T12:00:00"
            }, f)
            
        # Verify stats.json does not exist yet
        self.assertFalse(STATS_PATH.exists())
        
        # 2. Instantiate agent with this session ID. It should load the session
        # and automatically reconcile the untracked tokens.
        agent = AntAgent(self.config, session_id=session_id)
        
        # Verify stats.json was created and populated with reconciled tokens
        self.assertTrue(STATS_PATH.exists())
        with open(STATS_PATH, "r") as f:
            stats = json.load(f)
            
        self.assertEqual(stats["total_prompt_tokens"], 1200)
        self.assertEqual(stats["total_completion_tokens"], 300)
        self.assertEqual(stats["total_total_tokens"], 1500)
        
        # Verify session file was updated with tracked totals
        with open(session_file, "r") as f:
            session_data = json.load(f)
        self.assertEqual(session_data["session_tracked_prompt_tokens"], 1200)
        self.assertEqual(session_data["session_tracked_completion_tokens"], 300)
        
        # 3. Instantiate another agent with the same session. No new untracked
        # tokens exist, so stats.json should remain unchanged.
        agent2 = AntAgent(self.config, session_id=session_id)
        with open(STATS_PATH, "r") as f:
            stats = json.load(f)
            
        self.assertEqual(stats["total_prompt_tokens"], 1200)
        self.assertEqual(stats["total_completion_tokens"], 300)

    def test_auto_summarize_history(self):
        # Setup agent with low token limit to trigger auto-summarization easily
        config = self.config.copy()
        config["max_context_tokens"] = 150
        agent = AntAgent(config)
        agent.history = [
            {"role": "user", "content": "Let's build a massive web application with multiple microservices."},
            {"role": "assistant", "content": "Sure, let's start by planning all the API endpoints and services."},
            {"role": "user", "content": "I want service A to communicate with service B using gRPC protocols."},
            {"role": "assistant", "content": "Excellent choice. We will define protobuf contracts for them."},
            {"role": "user", "content": "Make sure we add logging and error metrics."},
            {"role": "assistant", "content": "Got it. Let's start coding A."},
            {"role": "user", "content": "Okay, write A's main logic."}
        ]
        
        # Mock query_llm to return a fake summary
        original_query_llm = agent.query_llm
        agent.query_llm = lambda prompt, system_override=None, use_history=False: "Mocked Summary of progress"
        
        try:
            # Let's count initial tokens
            initial_count = agent.count_history_tokens()
            # Ensure it exceeds limit * 0.8 (120 tokens)
            self.assertGreater(initial_count, 120)
            
            # Trigger auto-summarization check
            agent.auto_summarize_history_if_needed()
            
            # The history should now be summarized: the first elements collapsed into 1 summary,
            # and the last 3 kept intact.
            # So length should be 1 (summary) + 3 (last messages) = 4
            self.assertEqual(len(agent.history), 4)
            self.assertEqual(agent.history[0]["role"], "user")
            self.assertIn("[CONSOLIDATED PROGRESS SUMMARY OF PREVIOUS WORK]", agent.history[0]["content"])
            self.assertEqual(agent.history[0]["content"], "[CONSOLIDATED PROGRESS SUMMARY OF PREVIOUS WORK]\n\nMocked Summary of progress")
            
            # Last 3 elements must be preserved exactly
            self.assertEqual(agent.history[1]["content"], "Make sure we add logging and error metrics.")
            self.assertEqual(agent.history[2]["content"], "Got it. Let's start coding A.")
            self.assertEqual(agent.history[3]["content"], "Okay, write A's main logic.")
            
        finally:
            agent.query_llm = original_query_llm

    def test_knowledge_gap_blocking(self):
        from ant_agent.tools.python_repl import PythonReplTool
        from ant_agent.tools.filesystem import FilesystemWriteTool, FilesystemEditTool, CodeRunnerWithTestsTool
        
        # Test Python REPL blocking
        repl_tool = PythonReplTool()
        res = repl_tool.execute("print('__GAP::[missing function signature]__')")
        self.assertIn("Code execution blocked due to unresolved Knowledge Gaps", res)
        
        # Test Filesystem Write blocking
        write_tool = FilesystemWriteTool()
        res = write_tool.execute("temp.txt\n=== CONTENT ===\nclass Service:\n    def execute(self):\n        url = '__GAP::[missing url]__'")
        self.assertIn("File writing blocked due to unresolved Knowledge Gaps", res)
        self.assertFalse(Path("temp.txt").exists())
        
        # Setup clean file for edit test
        with open("temp_edit.txt", "w") as f:
            f.write("original text")
            
        # Test Filesystem Edit blocking
        edit_tool = FilesystemEditTool()
        res = edit_tool.execute("temp_edit.txt\n=== SEARCH ===\noriginal text\n=== REPLACE ===\nnew text with __GAP::[missing info]__")
        self.assertIn("File editing blocked due to unresolved Knowledge Gaps", res)
        # Check file was not modified
        with open("temp_edit.txt", "r") as f:
            self.assertEqual(f.read(), "original text")
            
        # Clean up files
        if Path("temp_edit.txt").exists():
            Path("temp_edit.txt").unlink()
            
        # Test Code Runner Command blocking
        runner_tool = CodeRunnerWithTestsTool()
        res = runner_tool.execute("pytest --gap=__GAP::[args]__")
        self.assertIn("execution blocked due to unresolved Knowledge Gaps", res)

    def test_resolve_knowledge_gaps_loop(self):
        agent = AntAgent(self.config)
        
        # Mock query_llm
        queries = []
        def mock_query_llm(prompt, system_override=None, use_history=False):
            queries.append((prompt, system_override, use_history))
            if "Convert this knowledge gap" in prompt:
                return "Mock Search Query"
            elif "extract the exact code snippet" in prompt:
                return "Mock Resolved Code Syntax"
            return "unexpected"
            
        agent.query_llm = mock_query_llm
        
        # Mock web search and fetch tools
        class MockWebSearchTool:
            def __init__(self, context): pass
            def execute(self, query):
                return "Title: Cloudflare workers docs\nURL: https://cloudflare.com/docs\nSnippet: Routing is defined via routing syntax."
                
        class MockWebFetchAndExtractTool:
            def __init__(self, context): pass
            def execute(self, url):
                return "This is the full scraped documentation text from cloudflare.com."
                
        import ant_agent.tools.web
        orig_search = ant_agent.tools.web.WebSearchTool
        orig_fetch = ant_agent.tools.web.WebFetchAndExtractTool
        
        ant_agent.tools.web.WebSearchTool = MockWebSearchTool
        ant_agent.tools.web.WebFetchAndExtractTool = MockWebFetchAndExtractTool
        
        try:
            # Set history
            agent.history = [
                {"role": "user", "content": "How to deploy worker?"},
                {"role": "assistant", "content": "Here is the code: const route = '__GAP::Cloudflare dynamic routing syntax__';"}
            ]
            
            agent.resolve_knowledge_gaps(["Cloudflare dynamic routing syntax"])
            
            # The history should now contain the resolved resolution injection payload at the end
            self.assertEqual(len(agent.history), 3)
            self.assertEqual(agent.history[2]["role"], "user")
            self.assertIn("resolved for your knowledge gaps", agent.history[2]["content"])
            self.assertIn("Mock Resolved Code Syntax", agent.history[2]["content"])
            
        finally:
            ant_agent.tools.web.WebSearchTool = orig_search
            ant_agent.tools.web.WebFetchAndExtractTool = orig_fetch

    def test_analysis_route_read_only(self):
        agent = AntAgent(self.config)
        agent.triage_request = lambda x: {
            "route": "analysis",
            "tool": None,
            "parameter": None,
            "explanation": "Test read-only analysis"
        }
        
        # Mock LLM to return answer on first turn to exit loop
        class MockChoice:
            def __init__(self):
                class MockMessage:
                    def __init__(self):
                        self.content = "This is the explanation of the code."
                        self.tool_calls = None
                self.message = MockMessage()
        class MockResponse:
            def __init__(self):
                self.choices = [MockChoice()]
                self.usage = None
        agent.client.chat.completions.create = lambda **kwargs: MockResponse()
        
        # Initially config has modifying tools
        self.assertIn("filesystem_write", agent.config["active_tools"])
        
        # Capture active_tools during loop execution
        captured_tools = []
        original_get_system_prompt = agent.get_system_prompt
        def mock_get_system_prompt():
            captured_tools.extend(list(agent.config["active_tools"]))
            return original_get_system_prompt()
        agent.get_system_prompt = mock_get_system_prompt
        
        ans = agent.run_cycle("explain how agent executes task", verbose=False)
        self.assertEqual(ans, "This is the explanation of the code.")
        
        # Modifying tools should not have been present during execution
        self.assertNotIn("filesystem_write", captured_tools)
        self.assertNotIn("filesystem_edit", captured_tools)
        self.assertNotIn("filesystem_delete", captured_tools)
        self.assertNotIn("code_runner_with_tests", captured_tools)
        
        # Modifying tools should be restored after execution
        self.assertIn("filesystem_write", agent.config["active_tools"])

    def test_safe_chat_completion_retries_on_rate_limit(self):
        agent = AntAgent(self.config)
        
        import time
        orig_sleep = time.sleep
        sleep_calls = []
        time.sleep = lambda secs: sleep_calls.append(secs)
        
        call_count = 0
        class MockChoice:
            def __init__(self):
                class MockMessage:
                    def __init__(self):
                        self.content = "Success response"
                        self.tool_calls = None
                self.message = MockMessage()
        class MockResponse:
            def __init__(self):
                self.choices = [MockChoice()]
                self.usage = None
                
        def mock_create(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise Exception("Error 429: resource_exhausted rate limit exceeded")
            return MockResponse()
            
        agent.client.chat.completions.create = mock_create
        
        try:
            res = agent.safe_chat_completion(model="gpt-4", messages=[])
            self.assertEqual(res.choices[0].message.content, "Success response")
            self.assertEqual(call_count, 3)
            self.assertEqual(len(sleep_calls), 2)
            self.assertEqual(sleep_calls[0], 4)
            self.assertEqual(sleep_calls[1], 8)
        finally:
            time.sleep = orig_sleep

    def test_tool_authorization_config_and_check(self):
        agent = AntAgent(self.config)
        self.assertFalse(agent.is_authorization_required("filesystem_write"))

        agent.config["authorization_required_tools"] = ["filesystem_write", "python_repl"]
        self.assertTrue(agent.is_authorization_required("filesystem_write"))
        self.assertTrue(agent.is_authorization_required("python_repl"))
        self.assertFalse(agent.is_authorization_required("web_search"))

        # Test alias authorization_required
        agent.config.pop("authorization_required_tools")
        agent.config["authorization_required"] = ["filesystem_delete"]
        self.assertTrue(agent.is_authorization_required("filesystem_delete"))
        self.assertFalse(agent.is_authorization_required("filesystem_write"))

    def test_tool_authorization_approval_flow(self):
        agent = AntAgent(self.config)
        agent.config["authorization_required_tools"] = ["filesystem_write"]

        approved_calls = []
        def auth_cb(tname, tparam):
            approved_calls.append((tname, tparam))
            return True

        res = agent._execute_tool_with_auth("filesystem_write", "test_auth.txt\n=== CONTENT ===\nhello auth", authorization_callback=auth_cb)
        self.assertEqual(len(approved_calls), 1)
        self.assertEqual(approved_calls[0][0], "filesystem_write")
        self.assertIn("Successfully wrote", res)

    def test_tool_authorization_denial_flow(self):
        agent = AntAgent(self.config)
        agent.config["authorization_required_tools"] = ["python_repl"]

        denied_calls = []
        def auth_cb(tname, tparam):
            denied_calls.append((tname, tparam))
            return False

        res = agent._execute_tool_with_auth("python_repl", "import os; print(os.name)", authorization_callback=auth_cb)
        self.assertEqual(len(denied_calls), 1)
        self.assertEqual(denied_calls[0][0], "python_repl")
        self.assertTrue(res.startswith("Tool execution denied by user"))
        self.assertIn("python_repl", res)

if __name__ == "__main__":
    unittest.main()
