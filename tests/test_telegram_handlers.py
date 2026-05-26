import unittest

from vision_bot_core.telegram_handlers import TelegramHandlerContext, register_telegram_handlers


class FakeBot:
    def __init__(self):
        self.message_handlers = []
        self.callback_handlers = []

    def message_handler(self, **kwargs):
        def decorator(func):
            self.message_handlers.append((kwargs, func))
            return func
        return decorator

    def callback_query_handler(self, **kwargs):
        def decorator(func):
            self.callback_handlers.append((kwargs, func))
            return func
        return decorator


class TelegramHandlersTests(unittest.TestCase):
    def test_register_telegram_handlers_adds_commands_and_callback_handler(self):
        bot = FakeBot()
        ctx = TelegramHandlerContext(
            bot=bot,
            allowed_user_id=123,
            get_setting=lambda name: 10,
            update_setting=lambda name, value: None,
            trim_alert_history=lambda limit: None,
            clear_alert_history_files=lambda: None,
            set_radar_state=lambda active, chat_id=None: None,
            build_status_message=lambda: "status",
            list_backups=lambda: [],
            format_timestamp=lambda timestamp: str(timestamp),
            format_size=lambda size: str(size),
            send_alert_history=lambda chat_id: None,
            capture_and_analyze_environment=lambda chat_id, question, reply_to_message=None: None,
            schedule_bot_restart=lambda: None,
            tail_error_log=lambda: "log",
            log_error=lambda context, error=None: None,
        )

        register_telegram_handlers(ctx)

        command_sets = [
            tuple(item[0].get("commands", []))
            for item in bot.message_handlers
            if "commands" in item[0]
        ]
        self.assertIn(("start", "help"), command_sets)
        self.assertIn(("menu",), command_sets)
        self.assertIn(("status",), command_sets)
        self.assertIn(("settings",), command_sets)
        self.assertEqual(len(bot.callback_handlers), 1)


if __name__ == "__main__":
    unittest.main()
