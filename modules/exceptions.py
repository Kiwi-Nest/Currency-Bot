from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from modules.errors import InsufficientFunds


class UserError(Exception):
    """Base exception for errors that should be displayed to the user."""


class InsufficientFundsError(UserError):
    """Raised when a user doesn't have enough cash for a transaction."""

    def __init__(self, error: InsufficientFunds) -> None:
        self.error = error
        super().__init__(
            f"Insufficient funds. You need ${error.required} but only have ${error.available}.",
        )
