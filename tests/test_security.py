import os
import unittest
from unittest.mock import patch

from security import redact_sensitive_data, safe_error_message


class SecurityRedactionTests(unittest.TestCase):
    def test_redacts_key_with_trailing_newline_from_header_error(self):
        key = "sk-exampleSecret123456"
        error = ValueError(f"Illegal header value b'Bearer {key}\\n'")

        with patch.dict(os.environ, {"DASHSCOPE_API_KEY": f"{key}\n"}):
            message = safe_error_message(error)

        self.assertNotIn(key, message)
        self.assertIn("格式不正确", message)

    def test_redacts_bearer_and_key_assignment(self):
        key = "sk-exampleSecret123456"
        value = (
            f"Authorization: Bearer {key}; "
            f"DASHSCOPE_API_KEY={key}"
        )

        message = redact_sensitive_data(value)

        self.assertNotIn(key, message)
        self.assertIn("[已隐藏]", message)

    def test_generic_error_is_chinese_and_length_limited(self):
        message = safe_error_message(RuntimeError("upstream failed " + "x" * 500))

        self.assertTrue(message.startswith("生成失败："))
        self.assertLessEqual(len(message), len("生成失败：") + 300)

    def test_safe_message_is_idempotent(self):
        message = "DashScope 请求超时，请稍后重试。"

        self.assertEqual(safe_error_message(message), message)


if __name__ == "__main__":
    unittest.main()
