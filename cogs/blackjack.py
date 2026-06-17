import asyncio
from collections import defaultdict
from enum import Enum, auto
from typing import TYPE_CHECKING, ClassVar, Final, TypedDict

import discord
from blackjack21 import DEFAULT_SUITS, Action, Card, Dealer, Deck, GameState, Player, Table
from blackjack21 import GameResult as LibGameResult
from blackjack21.exceptions import InvalidActionError, PlayFailure
from discord import app_commands
from discord.ext import commands

from modules.dtypes import GuildId, Member, PositiveInt, UserId
from modules.errors import InsufficientFunds
from modules.exceptions import UserError
from modules.guild_cog import GuildOnlyHybridCog
from modules.result import Err, Ok

if TYPE_CHECKING:
    from discord import Interaction

    from modules.BotCore import BotCore
    from modules.CurrencyLedgerDB import CurrencyLedgerDB, EventReason
    from modules.UserDB import UserDB

SECOND_COOLDOWN: Final[int] = 1


class GameResult(Enum):
    """Represents the final outcome of a hand for stat tracking and payouts."""

    WIN = auto()
    LOSS = auto()
    PUSH = auto()
    BLACKJACK = auto()
    SURRENDER = auto()


class ResultConfig(TypedDict):
    stat: str
    net_mult: float
    payout_mult: float
    reason: EventReason | None


RESULT_CONFIG: Final[dict[GameResult, ResultConfig]] = {
    GameResult.WIN: {
        "stat": "wins",
        "net_mult": 1.0,
        "payout_mult": 2.0,
        "reason": "BLACKJACK_WIN",
    },
    GameResult.BLACKJACK: {
        "stat": "blackjacks",
        "net_mult": 1.5,
        "payout_mult": 2.5,
        "reason": "BLACKJACK_BLACKJACK",
    },
    GameResult.LOSS: {
        "stat": "losses",
        "net_mult": -1.0,
        "payout_mult": 0.0,
        "reason": None,
    },
    GameResult.SURRENDER: {
        "stat": "losses",
        "net_mult": -0.5,
        "payout_mult": 0.5,
        "reason": "BLACKJACK_SURRENDER_RETURN",
    },
    GameResult.PUSH: {
        "stat": "pushes",
        "net_mult": 0.0,
        "payout_mult": 1.0,
        "reason": "BLACKJACK_PUSH",
    },
}


class BlackjackView(discord.ui.View):
    """Manages the entire game state, logic, and UI components for a single game."""

    GAME_TIMEOUT: ClassVar[float] = 180.0  # 3 minutes

    def __init__(
        self,
        bot: BotCore,
        user: discord.Member,
        bet: int,
        *,
        user_db: UserDB,
        ledger_db: CurrencyLedgerDB,
    ) -> None:
        super().__init__(timeout=self.GAME_TIMEOUT)
        self.bot = bot
        self.user_db = user_db
        self.ledger_db = ledger_db
        self.user = user
        self.initial_bet = bet
        self.last_action: str | None = None

        # Using 6 decks is common in casinos.
        deck = Deck(suits=DEFAULT_SUITS, count=6)

        self.table = Table(players=[(user.display_name, bet)], deck=deck)
        self.player: Player = self.table.players[0]
        self.dealer: Dealer = self.table.dealer
        self.outcome_message: str | None = None

        try:
            self.table.start_game()
        except (InvalidActionError, RuntimeError) as e:
            self.outcome_message = f"Error: Could not start game. {e}"
            self.disable_all_buttons(True)
            self.stop()
            return

        if self.table.state == GameState.ROUND_OVER:
            asyncio.create_task(self._end_game())  # noqa: RUF006
        else:
            self._update_buttons()

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user.id:
            await interaction.response.send_message(
                "This is not your game of blackjack. Use the `/blackjack` command to start your own.",
                ephemeral=True,
            )
            return False
        return True

    @property
    def total_bet_at_risk(self) -> int:
        return sum(hand.bet for hand in self.player.hands)

    def _update_buttons(self) -> None:
        self.clear_items()
        for item in (self.hit, self.stand, self.double_down, self.surrender, self.split, self.play_again, self.new_bet):
            item.disabled = False
        if self.table.state == GameState.ROUND_OVER:
            self.add_item(self.play_again)
            self.add_item(self.new_bet)
        elif self.table.state == GameState.PLAYERS_TURN:
            actions = self.table.available_actions()
            if Action.HIT in actions:
                self.add_item(self.hit)
            if Action.STAND in actions:
                self.add_item(self.stand)
            if Action.DOUBLE in actions:
                self.add_item(self.double_down)
            if Action.SURRENDER in actions:
                self.add_item(self.surrender)
            if Action.SPLIT in actions:
                self.add_item(self.split)

    def disable_all_buttons(self, is_disabled: bool = True) -> None:
        for item in self.children:
            if isinstance(item, discord.ui.Button):
                item.disabled = is_disabled

    async def check_and_charge(
        self,
        interaction: Interaction,
        amount: int,
        action_name: str,
    ) -> bool:
        assert interaction.guild
        user_id = UserId(interaction.user.id)
        guild_id = GuildId(interaction.guild.id)

        reason: EventReason
        match action_name:
            case "double down":
                reason = "BLACKJACK_DOUBLE_DOWN"
            case "split":
                reason = "BLACKJACK_SPLIT"
            case _:
                reason = "BLACKJACK_BET"

        match await self.user_db.burn_currency(
            Member(user_id, guild_id),
            amount=PositiveInt(amount),
            event_reason=reason,
            ledger_db=self.ledger_db,
            initiator_id=user_id,
        ):
            case Ok(_):
                return True
            case Err(InsufficientFunds(available, required)):
                msg = f"You don't have enough credits to {action_name}. You need ${required:,} but only have ${available:,}."
                raise UserError(msg)
        return False

    async def resolve_payout_and_stats(self, result: GameResult, bet_amount: int) -> None:
        if not (config := RESULT_CONFIG.get(result)):
            return

        guild_id = GuildId(self.user.guild.id)
        user_id = UserId(self.user.id)

        stats = blackjack_stats[guild_id][user_id]

        stats[config["stat"]] += 1
        stats["net_credits"] += int(bet_amount * config["net_mult"])

        payout = int(bet_amount * config["payout_mult"])
        payout_reason = config.get("reason")

        if payout > 0 and payout_reason:
            await self.user_db.mint_currency(
                Member(user_id, guild_id),
                amount=PositiveInt(payout),
                event_reason=payout_reason,
                ledger_db=self.ledger_db,
                initiator_id=user_id,
            )

    def _map_result_to_outcome(
        self,
        lib_result: LibGameResult,
        bet: int,
        hand_name: str,
    ) -> tuple[GameResult, str]:
        match lib_result:
            case LibGameResult.PLAYER_BUST:
                return (GameResult.LOSS, f"{hand_name}: Busted! You lose ${bet:,}.")
            case LibGameResult.DEALER_WIN:
                return (GameResult.LOSS, f"{hand_name}: Dealer wins. You lose ${bet:,}.")
            case LibGameResult.PUSH:
                return (GameResult.PUSH, f"{hand_name}: It's a push! Bet returned.")
            case LibGameResult.BLACKJACK:
                return (GameResult.BLACKJACK, f"{hand_name}: Blackjack! You win ${int(bet * 1.5):,}.")
            case LibGameResult.PLAYER_WIN | LibGameResult.DEALER_BUST:
                return (GameResult.WIN, f"{hand_name}: You win! You get ${bet:,}.")
            case LibGameResult.SURRENDER:
                return (GameResult.SURRENDER, f"{hand_name}: Surrendered. Half your bet (${bet // 2:,}) returned.")
            case _:
                return (GameResult.PUSH, f"{hand_name}: Push (unknown result).")

    async def _end_game(self) -> None:
        messages = []
        for i, hand in enumerate(self.player.hands):
            bet = hand.bet
            lib_result = hand.result
            if lib_result is None:
                continue

            hand_name = "Main Hand"
            if len(self.player.hands) > 1:
                hand_name = "Split Hand 1" if i == 0 else f"Split Hand {i + 1}"

            payout_reason, message_fragment = self._map_result_to_outcome(lib_result, bet, hand_name)
            messages.append(message_fragment)
            await self.resolve_payout_and_stats(payout_reason, bet)

        self.outcome_message = "\n".join(messages)
        self._update_buttons()

    async def _handle_stand_or_dd(self, interaction: Interaction) -> None:
        self.disable_all_buttons()
        await interaction.response.edit_message(embed=self.create_embed(), view=self)
        await asyncio.sleep(1.5)

        await self._end_game()
        await interaction.edit_original_response(embed=self.create_embed(), view=self)

    def create_embed(self) -> discord.Embed:
        is_game_over = self.table.state == GameState.ROUND_OVER

        color = discord.Colour.blue()
        if is_game_over and self.outcome_message:
            if "push" in self.outcome_message.lower():
                color = discord.Colour.light_grey()
            elif "win" in self.outcome_message.lower() or "blackjack" in self.outcome_message.lower():
                color = discord.Colour.green()
            else:
                color = discord.Colour.red()

        embed = discord.Embed(
            title=f"Blackjack | Total Bet: ${self.total_bet_at_risk:,}",
            color=color,
        )

        dealer_hand = self.table.dealer_visible_hand
        dealer_hand_str = format_hand(dealer_hand)

        dealer_hand_val: int | str
        if is_game_over:
            dealer_hand_val = self.dealer.total
        elif dealer_hand:
            dealer_hand_val = dealer_hand[0].value
        else:
            dealer_hand_val = "?"

        embed.add_field(
            name="Dealer's Hand",
            value=f"{dealer_hand_str}\n**Total: {dealer_hand_val}**",
            inline=False,
        )

        for i, hand in enumerate(self.player.hands):
            is_active = (hand is self.table.current_hand) and not is_game_over
            active_marker = "► " if is_active else ""

            hand_name = f"{self.user.display_name}'s Hand"
            if len(self.player.hands) > 1:
                hand_name = "Split Hand 1" if i == 0 else f"Split Hand {i + 1}"

            embed.add_field(
                name=f"{active_marker}{hand_name} (Bet: ${hand.bet:,})",
                value=f"{format_hand(list(hand))}\n**Total: {hand.total}**",
            )

        if self.outcome_message:
            embed.description = f"**{self.outcome_message}**"

        footer = "Game Over" if is_game_over else "It's your turn!"
        if self.last_action:
            footer += f" | {self.last_action}"
        embed.set_footer(text=footer)
        return embed

    # Button callbacks

    @discord.ui.button(label="Hit", style=discord.ButtonStyle.secondary, emoji="➕")  # noqa: RUF001
    async def hit(self, interaction: Interaction, _button: discord.ui.Button) -> None:
        current_hand = self.table.current_hand
        try:
            card = self.table.hit()
            self.last_action = f"You hit and drew a {card}."
            if current_hand and current_hand.bust:
                self.last_action += " You busted!"
        except (PlayFailure, InvalidActionError) as e:
            await interaction.response.send_message(f"Error: {e}", ephemeral=True)
            return

        if self.table.state == GameState.ROUND_OVER:
            await self._handle_stand_or_dd(interaction)
        else:
            self._update_buttons()
            await interaction.response.edit_message(embed=self.create_embed(), view=self)

    @discord.ui.button(label="Stand", style=discord.ButtonStyle.primary, emoji="✋")
    async def stand(self, interaction: Interaction, _button: discord.ui.Button) -> None:
        current_hand = self.table.current_hand
        assert current_hand
        try:
            self.last_action = f"You stood with a total of {current_hand.total}."
            self.table.stand()
        except (PlayFailure, InvalidActionError) as e:
            await interaction.response.send_message(f"Error: {e}", ephemeral=True)
            return

        if self.table.state == GameState.ROUND_OVER:
            await self._handle_stand_or_dd(interaction)
        else:
            self._update_buttons()
            await interaction.response.edit_message(embed=self.create_embed(), view=self)

    @discord.ui.button(label="Double Down", style=discord.ButtonStyle.success, emoji="💰")
    async def double_down(self, interaction: Interaction, _button: discord.ui.Button) -> None:
        current_hand = self.table.current_hand
        assert current_hand
        bet_amount = current_hand.bet
        if not await self.check_and_charge(interaction, bet_amount, "double down"):
            return

        try:
            card = self.table.double_down()
            self.last_action = f"You doubled down and drew a {card}. Final total: {current_hand.total}."
        except (PlayFailure, InvalidActionError) as e:
            await interaction.response.send_message(f"Error: {e}", ephemeral=True)
            return

        if self.table.state == GameState.ROUND_OVER:
            await self._handle_stand_or_dd(interaction)
        else:
            self._update_buttons()
            await interaction.response.edit_message(embed=self.create_embed(), view=self)

    @discord.ui.button(label="Split", style=discord.ButtonStyle.success, emoji="✌️")
    async def split(self, interaction: Interaction, _button: discord.ui.Button) -> None:
        current_hand = self.table.current_hand
        assert current_hand
        bet_amount = current_hand.bet
        if not await self.check_and_charge(interaction, bet_amount, "split"):
            return

        try:
            self.table.split()
            self.last_action = "You split your hand!"
            if self.table.state == GameState.ROUND_OVER:
                await self._handle_stand_or_dd(interaction)
            else:
                self._update_buttons()
                await interaction.response.edit_message(embed=self.create_embed(), view=self)
        except (PlayFailure, InvalidActionError) as e:
            await interaction.response.send_message(f"Error: {e}", ephemeral=True)

    @discord.ui.button(label="Surrender", style=discord.ButtonStyle.danger, emoji="🏳️")
    async def surrender(self, interaction: Interaction, _button: discord.ui.Button) -> None:
        try:
            self.table.surrender()
            self.last_action = "You surrendered this hand."
        except (PlayFailure, InvalidActionError) as e:
            await interaction.response.send_message(f"Error: {e}", ephemeral=True)
            return

        if self.table.state == GameState.ROUND_OVER:
            await self._handle_stand_or_dd(interaction)
        else:
            self._update_buttons()
            await interaction.response.edit_message(embed=self.create_embed(), view=self)

    @discord.ui.button(label="Play Again", style=discord.ButtonStyle.success)
    async def play_again(self, interaction: Interaction, _button: discord.ui.Button) -> None:
        assert interaction.guild
        user_id = UserId(interaction.user.id)
        guild_id = GuildId(interaction.guild.id)
        match await self.user_db.burn_currency(
            Member(user_id, guild_id),
            amount=PositiveInt(self.initial_bet),
            event_reason="BLACKJACK_BET",
            ledger_db=self.ledger_db,
            initiator_id=user_id,
        ):
            case Err(InsufficientFunds(available, required)):
                await interaction.response.edit_message(
                    content=f"You can't play again. You need ${required:,} but only have ${available:,}.",
                    embed=None,
                    view=None,
                )
                return
            case Ok(_):
                pass

        self.outcome_message = None
        self.last_action = "New round started."

        try:
            self.table.start_game()
        except (InvalidActionError, RuntimeError) as e:
            await interaction.response.edit_message(
                content=f"Error starting new round: {e}",
                embed=None,
                view=None,
            )
            return

        self.player = self.table.players[0]

        if self.table.state == GameState.ROUND_OVER:
            await self._end_game()
        else:
            self._update_buttons()

        await interaction.response.edit_message(embed=self.create_embed(), view=self)

    @discord.ui.button(label="New Bet", style=discord.ButtonStyle.secondary)
    async def new_bet(self, interaction: Interaction, _button: discord.ui.Button) -> None:
        self.stop()
        await interaction.response.edit_message(
            content="Use the `/blackjack` command to start a new game with a new bet.",
            embed=None,
            view=None,
        )


def format_hand(hand: list[Card]) -> str:
    suits = {"Hearts": "♥️", "Diamonds": "♦️", "Spades": "♠️", "Clubs": "♣️"}

    def format_card(card: Card) -> str:
        return f"`{card.rank}{suits.get(card.suit, card.suit)}`"

    return " ".join(format_card(c) for c in hand) if hand else "`Empty`"


def user_stats_factory() -> dict[str, int]:
    return {
        "wins": 0,
        "losses": 0,
        "pushes": 0,
        "blackjacks": 0,
        "net_credits": 0,
    }


blackjack_stats: defaultdict[int, defaultdict[int, dict[str, int]]] = defaultdict(
    lambda: defaultdict(user_stats_factory),
)


class BlackjackCog(GuildOnlyHybridCog):
    def __init__(self, bot: BotCore, *, user_db: UserDB, ledger_db: CurrencyLedgerDB) -> None:
        self.bot = bot
        self.user_db = user_db
        self.ledger_db = ledger_db

    @commands.hybrid_command(
        name="blackjack",
        description="Start a game of Blackjack.",
    )
    @commands.cooldown(1, SECOND_COOLDOWN * 5, commands.BucketType.user)
    @app_commands.describe(bet="The amount of credits you want to bet.")
    async def blackjack(
        self,
        ctx: commands.Context,
        bet: commands.Range[int, 1],
    ) -> None:
        assert ctx.guild
        user_id = UserId(ctx.author.id)
        guild_id = GuildId(ctx.guild.id)
        match await self.user_db.burn_currency(
            Member(user_id, guild_id),
            amount=PositiveInt(bet),
            event_reason="BLACKJACK_BET",
            ledger_db=self.ledger_db,
            initiator_id=user_id,
        ):
            case Err(InsufficientFunds(available, required)):
                await ctx.send(
                    f"Insufficient funds! You tried to bet ${required:,} but only have ${available:,}.",
                    ephemeral=True,
                )
                return
            case Ok(_):
                pass

        assert isinstance(ctx.author, discord.Member)
        view = BlackjackView(
            self.bot,
            ctx.author,
            bet,
            user_db=self.user_db,
            ledger_db=self.ledger_db,
        )
        await ctx.send(embed=view.create_embed(), view=view, ephemeral=False)

    @commands.hybrid_command(
        name="blackjack-stats",
        description="View your blackjack statistics for this server.",
    )
    @commands.cooldown(1, SECOND_COOLDOWN * 10, commands.BucketType.user)
    async def blackjack_stats(self, ctx: commands.Context) -> None:
        assert ctx.guild
        stats = blackjack_stats.get(ctx.guild.id, {}).get(ctx.author.id)
        if not stats:
            await ctx.send("You haven't played any games yet!", ephemeral=True)
            return

        embed = discord.Embed(
            title=f"{ctx.author.display_name}'s Blackjack Stats",
            color=discord.Colour.gold(),
        )
        total_games = stats["wins"] + stats["losses"] + stats["pushes"] + stats["blackjacks"]
        win_rate = ((stats["wins"] + stats["blackjacks"]) / total_games * 100) if total_games > 0 else 0

        embed.add_field(name="Total Games", value=f"{total_games}")
        embed.add_field(name="Win Rate", value=f"{win_rate:.2f}%")
        embed.add_field(name="Pushes", value=f"{stats['pushes']}")
        embed.add_field(name="Wins", value=f"{stats['wins']}")
        embed.add_field(name="Losses", value=f"{stats['losses']}")
        embed.add_field(name="Blackjacks", value=f"{stats['blackjacks']}")
        embed.add_field(name="Net Credits", value=f"{stats['net_credits']:,}")
        await ctx.send(embed=embed, ephemeral=True)

    @commands.hybrid_command(
        name="blackjack-leaderboard",
        description="View the server's blackjack leaderboard.",
    )
    @commands.cooldown(1, SECOND_COOLDOWN * 10, commands.BucketType.user)
    async def blackjack_leaderboard(self, ctx: commands.Context) -> None:
        assert ctx.guild
        guild_stats = blackjack_stats.get(ctx.guild.id)
        if not guild_stats:
            await ctx.send(
                "No one has played any games on this server yet!",
                ephemeral=True,
            )
            return

        sorted_players = sorted(
            guild_stats.items(),
            key=lambda item: item[1]["net_credits"],
            reverse=True,
        )
        embed = discord.Embed(
            title="Blackjack Leaderboard",
            description="Top players by net credits won.",
            color=discord.Colour.gold(),
        )
        for i, (user_id, stats) in enumerate(sorted_players[:10]):
            embed.add_field(
                name=f"{i + 1}. <@{user_id}>",
                value=f"**Net Credits:** {stats['net_credits']:,}",
                inline=False,
            )

        await ctx.send(embed=embed, ephemeral=True)


async def setup(bot: BotCore) -> None:
    await bot.add_cog(BlackjackCog(bot, user_db=bot.user_db, ledger_db=bot.ledger_db))
