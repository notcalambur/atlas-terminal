"""Atlas Terminal — Vercel serverless test entrypoint (minimal)."""
import json


def handler(event, context):
    return {
        "statusCode": 200,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps({"ok": True, "msg": "atlas direct handler alive"})
    }