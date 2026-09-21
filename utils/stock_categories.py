"""Account category values used by admin stock intake."""

CATEGORY_LABELS = {
    "nonspam": "Non-Spam",
    "spam": "Spam",
}


def category_value(selection):
    """Translate an explicit admin selection to the stored stock value."""
    if selection == "nonspam":
        return "Good"
    if selection == "spam":
        return "spam"
    raise ValueError("A valid stock category selection is required")
