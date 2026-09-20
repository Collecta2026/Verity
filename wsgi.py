"""
Production entry point for gunicorn:  gunicorn wsgi:app

Startup is made safe for multiple workers: Render starts several gunicorn
workers at once and each imports this module, so table creation and seeding
must tolerate another worker doing the same thing at the same moment.
"""
import logging, sys
from app import app, init_db

logging.basicConfig(stream=sys.stderr, level=logging.INFO,
                    format="%(asctime)s %(levelname)s %(message)s")
app.logger.setLevel(logging.INFO)

try:
    init_db()
    app.logger.info("Verity: database ready")
except Exception:
    # Never take the worker down on a startup race — log it and let the
    # health check report the real state.
    app.logger.exception("Verity: init_db failed at startup")

if __name__ == "__main__":
    app.run()
