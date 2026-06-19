"""Sensmos — stałe."""

DOMAIN = "sensmos"

CONF_HOST = "host"
CONF_PIN = "pin"

# entry.options
OPT_FEEDS = "feeds"              # [{node_entity, ha_entity, unit}]
OPT_WEBHOOK = "webhook_enabled"  # bool

# coordinator
SCAN_INTERVAL_S = 30        # /data/status
SLOW_EVERY_N_CYCLES = 10    # /config, /data/native co N cykli

# feeder
FEED_MIN_INTERVAL_S = 15    # min odstęp push per mapowanie
FEED_KEEPALIVE_S = 300      # odśwież wartość na nodzie nawet bez zmiany

# pool — prefiksy wykluczone z sensorów (udostępniamy tylko dane subskrypcji)
POOL_EXCLUDED_PREFIXES = ("get.", "msg.")

EVENT_NODE = "sensmos_event"
EVENT_MESSAGE = "sensmos_message"

PLATFORMS = ["sensor", "binary_sensor"]
