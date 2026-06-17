# Feijoa

A Discord bot with economy, leveling, paper trading, moderation, and automated server management.

---

## For Server Members

#### 💰 Economy

| Command | Description |
|-|-|
| `/daily` | Claim 20–50 credits (1% chance at a 100–1,000 jackpot). Buttons to set DM reminders and share your result. |
| `/bal [member]` | View wallet balance and bump count. |
| `/donate <member> <amount>` | Transfer currency to another user. Alias: `/give`. |
| `/leaderboard <stat>` | Top 200 users by Currency, Bumps, Level, or XP. Paginated with 🥇🥈🥉 medals. |
| `/blackjack <bet>` | Blackjack against the bot. Hit, Stand, Double Down, Split, Surrender. 6-deck shoe; Blackjack pays ×2.5. 3-min timeout. |
| `/blackjack-stats` | Your personal win/loss record and net profit. |
| `/blackjack-leaderboard` | Top 10 players by net credits. |

---

#### ✨ Leveling & Voice

- **XP gain**: 1 XP per message (≥4 unique lowercase letters), 5-min cooldown per channel. Bonus +4 XP after 6+ hours away.
- **`/level rank [member]`**: Level, total XP, progress bar, and XP to next level.
- **`/level opt-out`** / **`/level opt-in`**: Leave or re-join the leveling system.
- **`/vcinfo [member]`**: Peak concurrent users today (server view) or your total VC minutes and last-seen time (member view).
- **`/vcheatmap`**: Heatmap image of voice channel activity over time.

---

#### 🌐 Translation

- **`/language <lang>`**: Set your language (`en`, `bg`, `ro`). Messages you send in a different language than the server default are auto-translated for you.
- **`/autotranslate <enabled>`**: Toggle auto-translation on/off.
- **Translate** *(right-click → Apps)*: Manually translate any message.
- **Flag reactions**: React 🇬🇧 🇺🇸 🇧🇬 🇷🇴 to any message for an instant translation.

---

#### 🔔 Reminders

- **`@bot remind [me] [to] <time> <message>`**: Natural-language reminders (`in 5 minutes`, `tomorrow at 5pm`). Confirms with a Discord timestamp.
- **`/reminders list`**: All your active reminders.
- **`/reminders delete <id>`**: Cancel a reminder.
- Fired reminders include **Snooze** buttons: 15m · 1h · 1d.

---

#### 📈 Paper Trading

Leveraged stock simulation using server currency. Tickers: TQQQ, TNA, SOXL, FAZ, TMF, UGL, BITX.

| Command | Description |
|-|-|
| `/stocks` | All tradable assets and what they track. |
| `/price` | Current cached prices and market status. |
| `/buy <ticker> <amount> [leverage]` | Open a long position. Up to 10× leverage. |
| `/short <ticker> <amount> [leverage]` | Open a short position. Same leverage rules. |
| `/close <position_id> [amount]` | Close all or part of a position. Shows realized P&L. |
| `/portfolio [member]` | Full portfolio: cash, equity, P&L, all open positions. Can view others'. |

Positions are auto-liquidated if margin is exhausted; you'll get a DM.

---

#### 🤝 Social & Utilities

| Command | Description |
|-|-|
| `/invites top` | Leaderboard of top inviters. |
| `/invites mylist` | Private list of members you've invited. |
| `/pingrole <role>` | Ping members of a configured event role. 3 uses/min. |
| `/mojangprofile <player>` | Minecraft profile lookup (username or UUID). |
| `/help [command]` | List all commands or get detail on one. |
| **Who started this?** *(right-click → Apps)* | Identifies who invoked a slash command or sent a reply. |

---

#### 🔒 Privacy & Data

| Command | Description |
|-|-|
| `/my-data` | Export all your data (activity, reminders, positions, ledger) as JSON. |
| `/forget-me` | Delete your data across all servers. Requires confirmation; ledger retained for audit. |

---

#### 🤖 Automated Features

- **Bump rewards**: Successful `/bump` (Disboard) earns 30–50 currency and increments your bump stat. Reminders fire at +2h and +2h10m if the server hasn't been bumped again.
- **Reaction roles**: React to designated messages to gain roles; remove the reaction to lose them.
- **Voice streaks**: When everyone leaves VC, the bot posts a session summary (duration, peak users, unique participants) — for sessions with 2+ users lasting 60+ seconds.
- **Inactive role**: Assigned automatically when a member's last activity exceeds the configured threshold; removed the moment they become active again.

---

## For Staff & Administrators

#### 🛡️ Moderation

| Command | Description |
|-|-|
| `/moderate ban <member> [reason] [delete_messages]` | Ban with optional message history deletion. |
| `/moderate kick <member> [reason]` | Kick from server. |
| `/moderate timeout <member> <duration> [reason]` | Timeout (e.g. `10m`, `1h`, `7d`). |
| `/moderate untimeout <member> [reason]` | Remove active timeout. |
| `/moderate mute <member> [reason]` | Assign the configured Muted role. |
| `/moderate unmute <member> [reason]` | Remove the Muted role. |
| `/listroles` | All guild roles sorted by hierarchy and permissions. |

---

#### ⚙️ Configuration

| Command | Description |
|-|-|
| `/config autodiscover` | Scans channels/roles and suggests settings for approval. |
| `/config view` | All current bot settings. |
| `/config channel <feature> <channel>` | Set a channel for a feature. |
| `/config role <feature> <role>` | Set a role for a feature. |
| `/config forward ...` | Auto-forward embeds from a source bot to a target channel. |
| `/config prune ...` | Set inactivity threshold and roles to prune. |
| **Debug Reaction Role** *(right-click → Apps)* | DMs a validity + permission report for a reaction role message. |

---

#### 🤖 Automated Backend

- **Mod logging**: All `/moderate` actions logged to `mod_log_channel_id` with moderator, target, and reason.
- **Join/leave logging**: Embed log sent to `join_leave_log_channel_id`, including inviter, account age, and onboarding status. Auto-verification runs on smart indicators (avatar decoration, booster status, onboarding completion).
- **Anti-spam**: Auto-timeout for members sending identical messages across multiple channels rapidly.
- **Activity tracking**: Passively records last-active timestamps across messages, interactions, voice, reactions, and more — powers the inactivity pruner.
- **Inactivity pruner** *(hourly)*: Removes configured roles from members inactive beyond the threshold.
- **Custom role pruner** *(hourly)*: Deletes roles prefixed `Custom: ` older than 30 days.
- **Server stats channels**: Updates designated voice channel names with live member counts every 5 minutes.
- **GDPR retention** *(weekly)*: Cleans up stale reminders (90d+), inactive user records (600d+), and old VC sessions (90d+).
- **Message forwarder**: Auto-forwards messages from a configured source bot (e.g. QOTD) to a target channel.

---

#### 🖥️ Game Server Administration

*(Requires `MC_GUILD_ID` and `SERVERS_PATH`)*

| Command | Description |
|-|-|
| `/server list` | Online/Offline status for all managed servers. |
| `/server status <name>` | Detailed info for a specific server. |
| `/server start <name>` | Start a server. |
| `/server stop <name>` | Stop a server. |
| `/server rcon <name> <command>` | Send an RCON command. |
| `/server refresh` | Force re-scan of all server statuses. |
