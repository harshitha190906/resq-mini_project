"""
ResQNet — run.py
=================
Entry point for the Flask application.
Running ``python run.py`` will start the development server on localhost.
"""

from app import create_app

app = create_app()

if __name__ == "__main__":
    # Enable debug mode for easy development – can be toggled via Config.
    app.run(host="0.0.0.0", port=5000, debug=app.config.get("DEBUG", True))
