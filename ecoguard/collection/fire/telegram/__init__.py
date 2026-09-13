"""Raw messages from Israeli fire-reporting channels.

The only sub-hour detection path in the system — satellites are hours behind by
construction, and a person posting a photo is not.

`listener` owns the Telethon session and credentials; `collector` turns
messages into observations. Nothing here classifies or geolocates: the original
Hebrew is stored untouched so old messages stay replayable when the extractor
improves.
"""
