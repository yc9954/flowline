# Team mail (greenmail + Roundcube)

Test environment, test credentials. Everything runs on the Mac mini's docker, on `flownet` next to the desks.

Company-specific values come from the environment — `FLOWLINE_MAIL_DOMAIN` (northwind.local), `FLOWLINE_MAIL_TITLE`
("Northwind Mail": Roundcube's product name, so the window title is "<title> :: Inbox"), `FLOWLINE_MAIL_USERS`
(pm,finance,sales,ops,studio,director; index ↔ desk), `FLOWLINE_MAIL_HOST`, `FLOWLINE_MAIL_SMTP_PORT` / `_IMAP_PORT` /
`_API_PORT`, `FLOWLINE_WEBMAIL_PORT` — for `scripts/mail.sh`, `mail.py`, the Roundcube config and the autologin plugin
alike. Everything below describes the defaults, i.e. the Northwind demo. The skills themselves never read this file's
people: they take addresses by role from the run's board block (`board.py`, README.md), and they verify mail over IMAP
only when `board.mail_domain` **and** `FLOWLINE_MAIL_HOST` are set (the block-less demo keeps the localhost tunnel).

## Stack

| container | image | on flownet | on the mini (127.0.0.1) |
|---|---|---|---|
| `mail`    | greenmail/standalone:2.1.3 (in-memory, `-Dgreenmail.auth.disabled`, users pre-created) | `mail:3025` SMTP, `mail:3143` IMAP | 3025, 3143, REST API 3081 |
| `webmail` | roundcube/roundcubemail:1.6.11-apache (sqlite, Elastic skin, plain-text compose, 14-day sessions, no ip_check, light mode) | `http://webmail/` | http://127.0.0.1:3180 |

Config: `executor/assets/mail/roundcube.inc.php` (mounted as `/var/roundcube/config/zz-flowline.inc.php`) and the tiny
plugin `executor/assets/mail/flowline_autologin/` (`?_fl_user=<login>` logs that person in when there is no session,
so the desk windows come up logged in and re-login themselves on a reload).

```sh
scripts/mail.sh up | down | status          # from the laptop (re-executes on the mini) or on the mini
scripts/mail.sh seed                        # older threads in every inbox (skips subjects already there)
scripts/mail.sh reset [login|all]           # empty mailbox(es) — re-take: `reset all` then `seed`
scripts/mail.sh desks [N | deskX ...]       # pinned inbox window per desk + screenshot data/mail/deskN.png
scripts/mail.sh desks-down [N | deskX ...]
```
`down` loses all mail (greenmail is in-memory); `up` + `seed` rebuilds it in ~20 s (`seed` fills the six demo inboxes only).

## People (the Northwind demo: `mail.py DEMO_PEOPLE`, filled by `seed`; any other login@domain also works, auth is disabled)

| login | address | who | desk |
|---|---|---|---|
| pm | pm@northwind.local | Priya, PM | desk1 |
| finance | finance@northwind.local | Finance | desk2 |
| sales | sales@northwind.local | Sales | desk3 |
| ops | ops@northwind.local | Ops | desk4 |
| studio | studio@northwind.local | Studio manager | desk5 |
| director | director@northwind.local | Owner/director (signs); desk6 is the assistant reading this box | desk6 |

Password for all six: `flowline` (greenmail also accepts any password: auth is disabled). Roundcube login accepts
`pm` or `pm@northwind.local`.

## On a desk (what the agent sees)

Chromium app window (`--app`, class `FlowlineMail`, profile `/config/.flowline-mail`, launched with `GTK_THEME=Greybird`
so Roundcube renders light — the skin follows prefers-color-scheme), normal non-maximised window at
140,70 size 1360×860, sticky on all workspaces, title `(N) Northwind Mail :: Inbox` — "Inbox" is the thing to look for.
URL: `http://webmail/?_task=mail&_fl_user=<login>`. New mail appears within 30 s (refresh_interval), or click Refresh.

Send a mail with an attachment through the GUI:
1. Click **Compose** (left rail, top).
2. **To**: type the address (`finance@northwind.local`), **Subject**, then the body (plain-text editor).
3. Click **Attach** (toolbar, paperclip) — or **Attach a file** in the right column — the GTK "Open Files" chooser opens.
4. In the chooser press **ctrl+L**, type the full path (e.g. `/config/Documents/For signature/proposal-172.pdf`), wait a
   second, then **click the "Open" button** (bottom-right of the chooser). **Do not press Enter and do not double-click
   the file**: in this Chromium (156) + GTK 3.24.52 the activation path closes the chooser without handing the file to
   the page — the dialog disappears, the attachment list stays empty and no upload reaches the server (seen on
   desk3/4/5 run logs 2026-11-09 13:0x; the Open button worked every time on desk4 and desk5). Alternative that also
   goes through the button: navigate to the folder, single-click the file, click **Open**.
5. The file appears in the attachment list on the right with its name (an upload POST `_action=upload` shows in
   `docker logs webmail`). Then click **Send** (toolbar, top-left). Back to the inbox; the mail is in Sent.

Prove the attach path on a desk in one command: `scripts/mail.sh attach-test desk4 [/config/Documents/pricing-sheet.ods]`
(opens Compose if needed, attaches through the Open button, checks the webmail log, screenshot data/mail/desk4-attach.png;
the compose stays open — close it with the Mail button / discard, or relaunch the window with `desks-down deskN` + `desks deskN`).

Reading: click a message in the list — it opens in the right pane (widescreen layout); attachments are listed under the
headers; **Reply** / **Forward** in the toolbar.

## Helper (`executor/mail.py`, stdlib only)

From the laptop open the tunnel once: `ssh -fN -L 3143:localhost:3143 -L 3025:localhost:3025 mini`. On the mini
nothing is needed (localhost). Inside a desk container set `FLOWLINE_MAIL_HOST=mail`.

```python
import mail
mail.send("finance", "pm", "Updated quote: lunchtime classes", "see attached", attachments=["quote.pdf"])
mail.list_inbox("pm", since="2026-11-09T10:00")        # [{id, from, to, subject, date, attachments:[names], snippet}]
mail.find("pm", "quote", with_attachment=True)          # True = any attachment; "quote.pdf" = by name; None = no filter
mail.fetch_attachment("pm", msg["id"], "quote.pdf")     # -> bytes
mail.reset("pm")                                        # {"user": ..., "deleted": n}  (all folders)
mail.seed()
```
`id` is the IMAP UID in that user's INBOX (stable until `reset`); `send()` returns the same dict shape with the Message-ID
as `id`. Users may be given as login or full address; `to` may be a list.

CLI: `uv run python mail.py list finance | send finance pm "subj" --body "..." --attach f.pdf | find pm quote
[--attachment any|name] | fetch pm <id> <name> [--out path] | reset <login|all> | seed | users` — JSON on stdout.

Deterministic checks for skills: `find("pm", "quote", with_attachment="corrected")` non-empty = "the PM received
Finance's mail with the corrected sheet attached"; `find("director", "proposal", with_attachment="proposal-172.pdf")`
= "the Director received proposal-172.pdf"; `fetch_attachment` to compare bytes/sha256 with the file on the desk.

## Re-take

`scripts/mail.sh reset all && scripts/mail.sh seed` (mailboxes back to the seeded state; the desk windows stay logged
in and refresh on their own). If a window is gone: `scripts/mail.sh desks deskN`. If `mail` was restarted, run `seed`
again (in-memory store).
