import os
import tempfile
import unittest
from unittest.mock import patch

from layer1_input.task_store import TaskStateStore
from layer4_tools.tools.wan22 import TaskStatus, Wan22Result, Wan22Tool
from layer6_execution.agent import CreativeAgent
from layer6_execution.state import AgentStage, AgentState


class TaskStatePersistenceTests(unittest.TestCase):
    def test_round_trip_preserves_script_and_wan_task_ids(self):
        with tempfile.TemporaryDirectory() as directory:
            store = TaskStateStore(os.path.join(directory, "agent.db"))
            state = AgentState(
                session_id="abc12345",
                product_input={"product_name": "测试零食"},
            )
            state.set_checkpoint_callback(store.save)
            state.creative_bundle = {
                "hook": "第一口就停不下来",
                "storyboard": [{"time": "0-5s", "scene": "商品特写"}],
            }
            state.set_stage(AgentStage.RENDERING, "准备提交 Wan2.2")
            state.record_video_task(1, "开场镜头", "task-first")
            state.record_video_task(2, "转化镜头", "task-second")
            state.update_video_task("task-first", "RUNNING")

            restored = store.get("abc12345")

            self.assertIsNotNone(restored)
            self.assertEqual(restored.stage, AgentStage.RENDERING)
            self.assertEqual(restored.creative_bundle["hook"], "第一口就停不下来")
            self.assertEqual(
                [task["task_id"] for task in restored.video_tasks],
                ["task-first", "task-second"],
            )
            self.assertEqual(restored.video_tasks[0]["status"], "RUNNING")

    def test_checkpoint_callback_saves_every_stage_change(self):
        with tempfile.TemporaryDirectory() as directory:
            store = TaskStateStore(os.path.join(directory, "agent.db"))
            state = AgentState(session_id="checkpoint")
            state.set_checkpoint_callback(store.save)
            state.set_video_stage("submitting_1", "正在提交第 1 段")

            restored = store.get("checkpoint")

            self.assertEqual(restored.video_stage, "submitting_1")
            self.assertEqual(restored.progress_message, "正在提交第 1 段")

    def test_delete_removes_persisted_task(self):
        with tempfile.TemporaryDirectory() as directory:
            store = TaskStateStore(os.path.join(directory, "agent.db"))
            state = AgentState(session_id="delete-me")
            store.save(state)

            self.assertTrue(store.delete("delete-me"))
            self.assertIsNone(store.get("delete-me"))

    def test_wan_wait_reports_each_remote_status(self):
        tool = Wan22Tool.__new__(Wan22Tool)
        results = iter([
            Wan22Result(task_id="task-one", status=TaskStatus.PENDING),
            Wan22Result(task_id="task-one", status=TaskStatus.RUNNING),
            Wan22Result(
                task_id="task-one",
                status=TaskStatus.SUCCEEDED,
                video_url="https://example.com/video.mp4",
            ),
        ])
        tool.query_task = lambda _task_id: next(results)
        updates = []

        with patch("layer4_tools.tools.wan22.time.sleep"):
            final = tool.wait(
                "task-one",
                poll_interval=1,
                max_wait=10,
                on_update=lambda result: updates.append(result.status),
            )

        self.assertEqual(final.status, TaskStatus.SUCCEEDED)
        self.assertEqual(
            updates,
            [TaskStatus.PENDING, TaskStatus.RUNNING, TaskStatus.SUCCEEDED],
        )

    def test_agent_persists_both_task_ids_before_waiting(self):
        class FakeWan:
            def __init__(self):
                self.submissions = 0

            def i2v(self, **_kwargs):
                self.submissions += 1
                return Wan22Result(
                    task_id=f"task-{self.submissions}",
                    status=TaskStatus.PENDING,
                )

            def wait(self, task_id, on_update=None, **_kwargs):
                result = Wan22Result(
                    task_id=task_id,
                    status=TaskStatus.FAILED,
                    error_message="mock failure",
                )
                if on_update:
                    on_update(result)
                return result

        with tempfile.TemporaryDirectory() as directory:
            store = TaskStateStore(os.path.join(directory, "agent.db"))
            agent = CreativeAgent.__new__(CreativeAgent)
            agent.wan22 = FakeWan()
            state = AgentState(
                session_id="video-flow",
                product_input={
                    "assets": {
                        "product_main_image": "data:image/png;base64,aGVsbG8="
                    }
                },
            )
            state.set_checkpoint_callback(store.save)
            bundle = {
                "shots": [
                    {"label": "镜头一", "wan22_prompt": "商品特写"},
                    {"label": "镜头二", "wan22_prompt": "食用场景"},
                ]
            }

            with self.assertRaisesRegex(RuntimeError, "视频生成失败"):
                agent._generate_10s_video(bundle, state)

            restored = store.get("video-flow")
            self.assertEqual(
                [task["task_id"] for task in restored.video_tasks],
                ["task-1", "task-2"],
            )
            self.assertEqual(
                [task["status"] for task in restored.video_tasks],
                ["FAILED", "FAILED"],
            )


if __name__ == "__main__":
    unittest.main()
