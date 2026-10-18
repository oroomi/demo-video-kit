"""Dry-run fixtures: lets you rehearse a take WITHOUT spending live TTS characters or model tokens.
A take recorded with the mock is flagged ("mock": true) and assemble refuses it unless --allow-mock."""
import json


def mock_aava(answer_text, mp3_path):
    body = open(mp3_path, "rb").read()

    def install(ctx):
        def chat(route):
            sse = ("event: status\ndata: {\"state\":\"thinking\"}\n\n"
                   f"event: delta\ndata: {json.dumps({'text': answer_text})}\n\n"
                   f"event: done\ndata: {json.dumps({'text': answer_text, 'keys': [], 'sources': []})}\n\n")
            route.fulfill(status=200, headers={"content-type": "text/event-stream"}, body=sse)

        def prepare(route):
            route.fulfill(status=200, content_type="application/json", body=json.dumps({"url": "/api/aava/tts/mock.mp3"}))

        def stream(route):
            route.fulfill(status=200, headers={"content-type": "audio/mpeg", "accept-ranges": "none"}, body=body)

        ctx.route("**/api/aava/chat", chat)
        ctx.route("**/api/aava/tts/prepare", prepare)
        ctx.route("**/api/aava/tts/mock.mp3", stream)
    return install
