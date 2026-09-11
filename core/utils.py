from num2words import num2words


def amount_in_words(amount, currency_name='shillings'):
    """'300000' -> 'Three hundred thousand shillings only' (matches the printed receipt book)."""
    words = num2words(int(amount))
    return f'{words.capitalize()} {currency_name} only'
