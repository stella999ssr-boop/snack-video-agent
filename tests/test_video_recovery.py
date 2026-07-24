import io
import os
import subprocess
import tempfile
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest.mock import patch

from layer4_tools.tools.wan22 import TaskStatus, Wan22Result
from layer6_execution.agent import CreativeAgent
from layer6_execution.state import AgentStage, AgentState


class ExistingWanTaskRecoveryTests(unittest.TestCase):
    def test_recovery_reuses_task_ids_without_submitting_new_wan_jobs(self):
        class QueryOnlyWan:
            def i2v(self, **_kwargs):
                raise AssertionError("recovery must not submit i2v")

            def t2v(self, **_kwargs):
                raise AssertionError("recovery must not submit t2v")

            def wait(self, task_id, on_update=None, **_kwargs):
                result = Wan22Result(
                    task_id=task_id,
                    status=TaskStatus.SUCCEEDED,
                    video_url=f"https://example.com/{task_id}.mp4",
                )
                if on_update:
                    on_update(result)
                return result

        agent = CreativeAgent.__new__(CreativeAgent)
        agent.demo_mode = False
        agent.wan22 = QueryOnlyWan()
        state = AgentState(
            session_id="recover-me",
            stage=AgentStage.FAILED,
            creative_bundle={
                "shots": [
                    {"label": "镜头一", "copy": ""},
                    {"label": "镜头二", "copy": ""},
                ],
            },
            video_tasks=[
                {"shot": 1, "label": "镜头一", "task_id": "task-one"},
                {"shot": 2, "label": "镜头二", "task_id": "task-two"},
            ],
        )

        with patch.object(
            agent,
            "_compose_video_urls",
            return_value=("/outputs/recover-me_10s.mp4", "/tmp/recover-me_10s.mp4"),
        ) as compose:
            video_url, video_path = agent.recover_video_from_existing_tasks(state)

        self.assertEqual(video_url, "/outputs/recover-me_10s.mp4")
        self.assertEqual(video_path, "/tmp/recover-me_10s.mp4")
        self.assertEqual(state.stage, AgentStage.DONE)
        self.assertIn("未重新提交", state.progress_message)
        compose.assert_called_once()
        recovered_urls = compose.call_args.args[2]
        self.assertEqual(
            [item[2] for item in recovered_urls],
            [
                "https://example.com/task-one.mp4",
                "https://example.com/task-two.mp4",
            ],
        )

    def test_concat_filter_is_ascii_decrease(self):
        agent = CreativeAgent.__new__(CreativeAgent)
        agent.FFMPEG_ASPECT_RATIO_MODE = "decrease"
        state = AgentState(session_id="ascii-filter")
        bundle = {
            "shots": [
                {"label": "镜头一", "copy": ""},
                {"label": "镜头二", "copy": ""},
            ],
        }
        video_urls = [
            (0, "镜头一", "https://example.com/one.mp4"),
            (1, "镜头二", "https://example.com/two.mp4"),
        ]
        response = SimpleNamespace(
            content=b"mock-mp4",
            raise_for_status=lambda: None,
        )
        commands = []

        def fake_ffmpeg(command, _label):
            commands.append(command)
            with open(command[-1], "wb") as output:
                output.write(b"merged")

        with tempfile.TemporaryDirectory() as directory:
            agent.output_dir = directory
            with (
                patch("layer6_execution.agent.httpx.get", return_value=response),
                patch.object(agent, "_run_ffmpeg", side_effect=fake_ffmpeg),
            ):
                video_url, video_path = agent._compose_video_urls(
                    bundle,
                    state,
                    video_urls,
                )

            self.assertTrue(os.path.isfile(video_path))
            self.assertEqual(video_url, "/outputs/ascii-filter_10s.mp4")

        concat_filter = commands[0][commands[0].index("-filter_complex") + 1]
        self.assertIn("force_original_aspect_ratio=decrease", concat_filter)
        self.assertNotIn("减少", concat_filter)

    def test_ffmpeg_failure_logs_full_stderr(self):
        error = subprocess.CalledProcessError(
            1,
            ["ffmpeg", "-version"],
            output="full stdout",
            stderr="first diagnostic line\nfinal diagnostic line",
        )
        output = io.StringIO()
        with (
            patch("layer6_execution.agent.subprocess.run", side_effect=error),
            redirect_stdout(output),
            self.assertRaisesRegex(RuntimeError, "final diagnostic line"),
        ):
            CreativeAgent._run_ffmpeg(["ffmpeg", "-version"], "测试合成")

        log = output.getvalue()
        self.assertIn("full stdout", log)
        self.assertIn("first diagnostic line", log)
        self.assertIn("final diagnostic line", log)


if __name__ == "__main__":
    unittest.main()
