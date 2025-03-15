# telegram_inline.py
class InlineKeyboardButton:
    def __init__(self, text, callback_data):
        self.text = text
        self.callback_data = callback_data

    def to_dict(self):
        return {"text": self.text, "callback_data": self.callback_data}

class InlineKeyboardMarkup:
    def __init__(self, inline_keyboard):
        self.inline_keyboard = inline_keyboard

    def to_dict(self):
        return {"inline_keyboard": [[button.to_dict() for button in row] for row in self.inline_keyboard]}
