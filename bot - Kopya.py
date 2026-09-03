# ============================================================
# /GONDER
# ============================================================

async def gonder(
    update: Update,
    context: ContextTypes.DEFAULT_TYPE
):

    if not context.args:

        await update.message.reply_text(
            "❌ Gönderilecek mesajı yazmalısın.\n\n"
            "Örnek:\n"
            "/gonder BTC yükseliş sinyali verdi 🚀"
        )

        return

    message = " ".join(
        context.args
    )

    if TARGET_CHAT_ID is None:

        await update.message.reply_text(
            "❌ Hedef kanal tanımlı değil."
        )

        return

    try:

        await context.bot.send_message(
            chat_id=TARGET_CHAT_ID,
            text=message
        )

        await update.message.reply_text(
            "✅ Mesaj kanala gönderildi.\n\n"
            f"📢 Hedef: {TARGET_CHAT_ID}"
        )

        safe_print(
            "MANUEL MESAJ GONDERILDI:",
            message
        )

    except Exception as e:

        safe_print(
            "Manuel mesaj gonderme hatasi:",
            type(e).__name__,
            str(e)
        )

        await update.message.reply_text(
            "❌ Mesaj gönderilemedi.\n\n"
            "Botun kanalda yönetici olduğundan "
            "ve mesaj gönderme yetkisi bulunduğundan "
            "emin ol."
        )
