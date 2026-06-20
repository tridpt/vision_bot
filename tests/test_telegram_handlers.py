import unittest

from vision_bot_core.telegram_handlers import TelegramHandlerContext, register_telegram_handlers


class FakeBot:
    def __init__(self):
        self.message_handlers = []
        self.callback_handlers = []
        self.replies = []

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

    def reply_to(self, message, text, **kwargs):
        self.replies.append((message, text, kwargs))


class FakeUser:
    def __init__(self, user_id):
        self.id = user_id


class FakeChat:
    def __init__(self, chat_id):
        self.id = chat_id


class FakeMessage:
    def __init__(self, text, user_id=123, chat_id=123):
        self.text = text
        self.from_user = FakeUser(user_id)
        self.chat = FakeChat(chat_id)


class TelegramHandlersTests(unittest.TestCase):
    def _create_context_and_bot(self):
        bot = FakeBot()
        self.radar_state = None
        self.settings = {}

        def update_setting(name, value):
            self.settings[name] = value

        def set_radar_state(active, chat_id=None):
            self.radar_state = active

        ctx = TelegramHandlerContext(
            bot=bot,
            allowed_user_id=123,
            get_setting=lambda name: self.settings.get(name, 10),
            update_setting=update_setting,
            trim_alert_history=lambda limit: None,
            clear_alert_history_files=lambda: None,
            set_radar_state=set_radar_state,
            build_status_message=lambda: "status",
            list_backups=lambda: [],
            restore_latest_settings_backup=lambda: None,
            restore_latest_alert_history_backup=lambda: None,
            format_timestamp=lambda timestamp: str(timestamp),
            format_size=lambda size: str(size),
            send_alert_history=lambda chat_id: None,
            capture_and_analyze_environment=lambda chat_id, question, reply_to_message=None: None,
            scan_cameras=lambda chat_id: None,
            test_camera=lambda chat_id: None,
            schedule_bot_restart=lambda: None,
            tail_error_log=lambda: "log",
            log_error=lambda context, error=None: None,
            get_dashboard_url=lambda: "http://127.0.0.1:8765",
        )
        return ctx, bot

    def _get_handler(self, bot, command_name):
        for kwargs, func in bot.message_handlers:
            if command_name in kwargs.get("commands", []):
                return func
        return None

    def test_register_telegram_handlers_adds_commands_and_callback_handler(self):
        ctx, bot = self._create_context_and_bot()
        register_telegram_handlers(ctx)

        command_sets = [
            tuple(item[0].get("commands", []))
            for item in bot.message_handlers
            if "commands" in item[0]
        ]
        self.assertIn(("start", "help"), command_sets)
        self.assertIn(("menu",), command_sets)
        self.assertIn(("auto",), command_sets)
        self.assertIn(("stop",), command_sets)
        self.assertEqual(len(bot.callback_handlers), 1)

    def test_start_command_replies_welcome(self):
        ctx, bot = self._create_context_and_bot()
        register_telegram_handlers(ctx)
        handler = self._get_handler(bot, "start")
        
        msg = FakeMessage("/start")
        handler(msg)
        
        self.assertEqual(len(bot.replies), 1)
        self.assertIn("Chào Boss", bot.replies[0][1])

    def test_auto_command_turns_on_radar(self):
        ctx, bot = self._create_context_and_bot()
        register_telegram_handlers(ctx)
        handler = self._get_handler(bot, "auto")
        
        msg = FakeMessage("/auto")
        handler(msg)
        
        self.assertTrue(self.radar_state)
        self.assertEqual(len(bot.replies), 1)
        self.assertIn("Đã BẬT Radar", bot.replies[0][1])

    def test_stop_command_turns_off_radar(self):
        ctx, bot = self._create_context_and_bot()
        register_telegram_handlers(ctx)
        handler = self._get_handler(bot, "stop")
        
        msg = FakeMessage("/stop")
        handler(msg)
        
        self.assertFalse(self.radar_state)
        self.assertEqual(len(bot.replies), 1)
        self.assertIn("Đã TẮT Radar", bot.replies[0][1])

    def test_unauthorized_user_is_ignored(self):
        ctx, bot = self._create_context_and_bot()
        register_telegram_handlers(ctx)
        handler = self._get_handler(bot, "start")
        
        msg = FakeMessage("/start", user_id=999) # Not 123
        handler(msg)
        
        self.assertEqual(len(bot.replies), 1)
        self.assertIn("không nhận lệnh", bot.replies[0][1])


if __name__ == "__main__":
    unittest.main()
