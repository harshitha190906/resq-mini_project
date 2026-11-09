"""
ResQNet — app/config.py
========================
Configuration object for the Flask application.
Only minimal settings are required for the educational project.
"""

class Config:
    """Base configuration for Flask.

    In a real deployment you would extend this with environment‑specific
    subclasses (DevelopmentConfig, ProductionConfig, etc.).
    """

    DEBUG = True
    TESTING = False
    # Secret key is required for session handling – a static value is fine for
    # this educational example.
    SECRET_KEY = "dev-secret-key"
    # JSON responses should be pretty‑printed when debugging.
    JSONIFY_PRETTYPRINT_REGULAR = True
