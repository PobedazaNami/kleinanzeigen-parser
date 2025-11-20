from .telegram_bot import (
    build_app,
    admin_inline_approve_cb,
    admin_inline_decline_cb,
)
from .runner import set_application_for_send, schedule_jobs, async_run_for_user


def main():
    app = build_app()
    set_application_for_send(app)
    from telegram.ext import CallbackQueryHandler
    # NOTE: user_subscribe_cb is now handled by the user setup conversation handler in build_app()
    # Do not add it again here to avoid conflicts
    app.add_handler(CallbackQueryHandler(admin_inline_approve_cb, pattern=r"^admin_inline_approve:.*$"))
    app.add_handler(CallbackQueryHandler(admin_inline_decline_cb, pattern=r"^admin_inline_decline:.*$"))

    async def _post_start(_: object) -> None:
        await schedule_jobs(app)

    app.post_init = _post_start
    app.run_polling(allowed_updates=["message", "edited_message", "callback_query"])  # minimal


if __name__ == "__main__":
    main()
