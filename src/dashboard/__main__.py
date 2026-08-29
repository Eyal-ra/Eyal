"""הפעלת שרת הדשבורד: ``python -m src.dashboard``."""

from . import create_app, load_config


def main() -> None:
    cfg = load_config()
    dash = cfg.get("dashboard", {}) or {}
    host = dash.get("host", "0.0.0.0")
    port = int(dash.get("port", 9999))
    hostname = dash.get("hostname", "cpateam-dash")

    app = create_app(cfg)

    shown_port = "" if port == 80 else f":{port}"
    print("=" * 60)
    print("  הדשבורד עלה!")
    print(f"  כתובת ידידותית:  http://{hostname}{shown_port}")
    print(f"  (מאזין על {host}:{port})")
    print("  להגדרת הכתובת הידידותית הריצו: python scripts/setup_hostname.py")
    print("=" * 60)

    app.run(host=host, port=port)


if __name__ == "__main__":
    main()
