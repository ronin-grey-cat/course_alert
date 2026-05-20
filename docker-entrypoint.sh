#!/bin/sh
set -e

if [ -z "$VAPID_PUBLIC_KEY" ] || [ -z "$VAPID_PRIVATE_KEY" ]; then
  echo ""
  echo "=== VAPID keys not configured ==="
  echo "Run the app once with: python app.py"
  echo "Then visit http://localhost:5000/api/generate-vapid-keys"
  echo "Copy the returned keys into your .env file and restart."
  echo ""
  echo "Or generate them now by running:"
  echo "  python - <<'EOF'"
  echo "from notifications import generate_vapid_keys"
  echo "import json; print(json.dumps(generate_vapid_keys(), indent=2))"
  echo "EOF"
  echo ""
  exit 1
fi

exec "$@"
