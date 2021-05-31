#!/usr/bin/env python3
"""
Trello -> ICS Shimmy

This is a simple API that exposes Trello cards as an ICS feed.

Specifically it supports 'start date' events spanning multiple days.

MIT License

Copyright (c) 2021 Infra Bits

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
"""
import logging
import sys
import urllib.parse
from datetime import datetime, timezone

import requests

from flask import Flask, make_response, request, redirect

logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config.from_envvar("TRELLO_ICS_SHIMMY_SETTINGS")


def get_cards():
    r = requests.get(
        f'https://api.trello.com/1/boards/{app.config.get("TRELLO_BOARD_ID")}/cards/visible',
        params={
            "key": app.config.get("TRELLO_ACCESS_KEY"),
            "token": app.config.get("TRELLO_ACCESS_TOKEN"),
        },
    )
    r.raise_for_status()
    return r.json()


def get_lists_by_id():
    r = requests.get(
        f'https://api.trello.com/1/boards/{app.config.get("TRELLO_BOARD_ID")}/lists',
        params={
            "key": app.config.get("TRELLO_ACCESS_KEY"),
            "token": app.config.get("TRELLO_ACCESS_TOKEN"),
        },
    )
    r.raise_for_status()
    return {list["id"]: list for list in r.json()}


def chunk_string(string, length):
    """Chunk a string into parts under the specified length."""
    if len(string) <= 73:
        return [string]

    return [string[i:i + length] for i in range(0, len(string), length)]


@app.route("/c/<access_key>.ics", methods=["GET"])
def build_ics(access_key):
    """Main ICS endpoint."""
    if access_key != app.config.get("ICS_KEY"):
        return make_response("Not Found", 404)

    ics_payload = []
    ics_payload.append("BEGIN:VCALENDAR")
    ics_payload.append("VERSION:2.0")
    ics_payload.append("PRODID:-//Infra Bits//Trello -> ICS Shimmy//EN")
    ics_payload.append("REFRESH-INTERVAL:PT5M")

    lists_by_id = get_lists_by_id()
    for card in get_cards():
        # No time data - can't map to a calendar
        if not card["due"]:
            continue

        ics_payload.append("BEGIN:VEVENT")

        if card["desc"]:
            description = "\n ".join(chunk_string(f'{card["desc"]}\\n\\nCard URL: {card["url"]}', 73))
        else:
            description = "\n ".join(chunk_string(f'Card URL: {card["url"]}', 73))

        ics_payload.append(f"DESCRIPTION:{description}")
        ics_payload.append(f'URL:{card["url"]}')
        ics_payload.append(f'SUMMARY:{card["name"]} [{lists_by_id[card["idList"]]["name"]}]')
        ics_payload.append(f'UID:{card["id"]}@trello.com')
        if card["start"]:
            start_date = (
                datetime.strptime(card["start"], "%Y-%m-%dT%H:%M:%S.%f%z")
                .astimezone(timezone.utc)
                .replace(hour=0, minute=0, second=0, microsecond=0)
                .strftime("%Y%m%dT%H%M%SZ")
            )
            due_date = (
                datetime.strptime(card["due"], "%Y-%m-%dT%H:%M:%S.%f%z")
                .astimezone(timezone.utc)
                .strftime("%Y%m%dT%H%M%SZ")
            )
            ics_payload.append(f"DTSTAMP:{start_date}")
            ics_payload.append(f"DTSTART:{start_date}")
            ics_payload.append(f"DTEND:{due_date}")
        else:
            due_date = (
                datetime.strptime(card["due"], "%Y-%m-%dT%H:%M:%S.%f%z")
                .astimezone(timezone.utc)
                .strftime("%Y%m%dT%H%M%SZ")
            )
            ics_payload.append(f"DTSTAMP:{due_date}")
            ics_payload.append(f"DTSTART:{due_date}")
            ics_payload.append("DURATION:PT1H")
        ics_payload.append("END:VEVENT")

    ics_payload.append("END:VCALENDAR")
    return "\n".join(ics_payload), 200, {"Content-Type": "text/calendar"}


@app.route("/a/<access_key>/token", methods=["GET"])
def get_auth_token_callback(access_key):
    """Trello authorization endpoint."""
    if access_key != app.config.get("ICS_KEY"):
        return make_response("Not Found", 404)

    # Note: We cannot postMessage to a localhost URL, so format the token for copying
    return make_response(
        """<!doctype html>
    <html lang="en">
    <body></body>
    <script type="text/javascript">
        document.body.innerHTML = '<pre>' + window.location.hash.split('=')[1] + '</pre>';
    </script>
    </html>""",
        200,
    )


@app.route("/a/<access_key>", methods=["GET"])
def get_auth_token(access_key):
    """Trello authorization endpoint."""
    if access_key != app.config.get("ICS_KEY"):
        return make_response("Not Found", 404)

    if app.config.get("TRELLO_ACCESS_TOKEN"):
        return make_response("Token already set", 400)

    if app.config.get("TRELLO_ACCESS_KEY"):
        return make_response("Missing access key", 500)

    params = urllib.parse.urlencode({
        "key": app.config.get("TRELLO_ACCESS_KEY"),
        "return_url": f"http{'s' if request.is_secure else ''}://{request.host}/a/{access_key}/token",
        "callback_method": "fragment",
        "response_type": "token",
        "scope": "read",
        "expiration": "never",
        "name": "Trello -> ICS Shimmy",
    })
    return redirect(f"https://api.trello.com/1/authorize?{params}", code=302)


if __name__ == "__main__":
    logging.basicConfig(stream=sys.stderr, level=logging.INFO)
    app.run()
