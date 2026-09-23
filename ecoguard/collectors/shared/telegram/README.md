# Telegram

Messages from the configured channels. Stores what was posted and who posted
it; whether it describes anything real is decided by the text detector.

| File | What it does |
|---|---|
| `policy.py` | Which channels are read, and how their identity is checked |
| `collector.py` | Reads the recent messages from each one |
| `session.py` | The login credentials and the saved session |
| `listener.py` | A one-off command for logging in and pinning each channel |

## Why channels are pinned by number

A channel name can be released and taken over by somebody else. Each configured
channel is therefore pinned to its numeric identity, and a channel that answers
under the right name but the wrong number is refused.

Posts are re-read rather than only followed forward, because operational
channels edit a message as an incident develops.
