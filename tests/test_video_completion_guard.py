import os
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from config import read_env_bool
from layer1_input import routes
from layer6_execution.agent import CreativeAgent
from layer6_execution.state import AgentStage, AgentState


class VideoSwitchParsingTests(unittest.TestCase):
    def test_true_value_allows_railway_whitespace_and_newline(self):
        with patch.dict(os.environ, {"LIVE_ENABLE_VIDEO": "  TrUe \n"}):
            self.assertTrue(read_env_bool("LIVE_ENABLE_VIDEO"))

    def test_false_value_allows_whitespace_and_newline(self):
        with patch.dict(os.environ, {"LIVE_ENABLE_VIDEO": "\t false \n"}):
            self.assertFalse(read_env_bool("LIVE_ENABLE_VIDEO", default=True))

    def test_invalid_value_fails_instead_of_silently_disabling_video(self):
        with patch.dict(os.environ, {"LIVE_ENABLE_VIDEO": "ture"}):
            with self.assertRaisesRegex(ValueError, "LIVE_ENABLE_VIDEO 配置无效"):
                read_env_bool("LIVE_ENABLE_VIDEO")


class VideoCompletionGuardTests(unittest.TestCase):
    def make_agent(self, *, demo_mode=False, enable_video=True):
        agent = CreativeAgent.__new__(CreativeAgent)
        agent.demo_mode = demo_mode
        agent.enable_video = enable_video
        return agent

    def test_live_video_switch_off_is_not_done(self):
        agent = self.make_agent(enable_video=False)
        state = AgentState(
            session_id="video-disabled",
            creative_bundle={"hook": "脚本已经生成"},
        )

        with self.assertRaisesRegex(RuntimeError, "LIVE_ENABLE_VIDEO"):
            agent._require_video_enabled(state)

        self.assertEqual(state.video_stage, "disabled")
        self.assertNotEqual(state.stage, AgentStage.DONE)

    def test_live_video_switch_off_finishes_as_failed_and_keeps_script(self):
        class FakeMemory:
            def start_session(self, _session_id):
                return None

        agent = self.make_agent(enable_video=False)
        agent.memory = FakeMemory()
        agent.user_id = ""
        agent._react_loop = lambda state: agent._require_video_enabled(state)
        state = AgentState(
            session_id="video-disabled-run",
            creative_bundle={"hook": "脚本仍然保留"},
        )

        result = agent.run({}, state=state)

        self.assertEqual(result.stage, AgentStage.FAILED)
        self.assertEqual(result.video_stage, "disabled")
        self.assertEqual(result.creative_bundle["hook"], "脚本仍然保留")
        self.assertIn("LIVE_ENABLE_VIDEO", result.error)

    def test_live_missing_video_output_is_not_done(self):
        agent = self.make_agent(enable_video=True)
        state = AgentState(
            session_id="video-missing",
            creative_bundle={"hook": "脚本已经生成"},
        )

        with self.assertRaisesRegex(RuntimeError, "没有生成可播放的视频成片"):
            agent._require_video_delivery(state)

        self.assertEqual(state.video_stage, "delivery_failed")
        self.assertNotEqual(state.stage, AgentStage.DONE)

    def test_live_complete_video_passes_guard(self):
        agent = self.make_agent(enable_video=True)
        state = AgentState(
            session_id="video-ready",
            video_url="/outputs/video-ready.mp4",
            video_path="/data/outputs/video-ready.mp4",
        )

        agent._require_video_enabled(state)
        agent._require_video_delivery(state)

        self.assertEqual(state.video_stage, "")

    def test_demo_script_can_complete_without_video(self):
        agent = self.make_agent(demo_mode=True, enable_video=False)
        state = AgentState(session_id="demo-script")

        agent._require_video_enabled(state)
        agent._require_video_delivery(state)

        self.assertEqual(state.video_stage, "")

    def test_live_mode_without_api_key_does_not_fall_back_to_demo(self):
        with self.assertRaisesRegex(RuntimeError, "不会静默退回 Demo"):
            CreativeAgent(
                memory_manager=object(),
                dashscope_api_key=" \n",
                demo_mode=False,
                enable_video=True,
            )


class StatusResponseGuardTests(unittest.IsolatedAsyncioTestCase):
    async def test_legacy_live_done_without_video_is_repaired_to_failed(self):
        request_id = "legacy-fake-done"
        state = AgentState(
            session_id=request_id,
            stage=AgentStage.DONE,
            creative_bundle={
                "hook": "脚本已经生成",
                "storyboard": [],
            },
        )

        with (
            patch.object(routes, "_agent", SimpleNamespace(demo_mode=False)),
            patch.dict(routes._states, {request_id: state}),
        ):
            response = await routes.get_status(request_id)

        self.assertEqual(response["status"], "failed")
        self.assertEqual(response["stage"], AgentStage.FAILED.value)
        self.assertEqual(response["video_progress"]["stage"], "delivery_failed")
        self.assertIn("script_preview", response)
        self.assertNotIn("result", response)


if __name__ == "__main__":
    unittest.main()
