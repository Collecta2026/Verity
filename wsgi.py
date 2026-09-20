"""Production entry point for gunicorn:  gunicorn wsgi:app"""
from app import app, init_db

# create tables (and seed defaults on first boot) against the configured database
init_db()

if __name__ == "__main__":
    app.run()
