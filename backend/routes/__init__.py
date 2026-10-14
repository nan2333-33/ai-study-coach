from .materials import bp as materials_bp
from .chat import bp as chat_bp
from .quiz import bp as quiz_bp
from .review import bp as review_bp
from .progress import bp as progress_bp
from .report import bp as report_bp


def register_routes(app):
    app.register_blueprint(materials_bp)
    app.register_blueprint(chat_bp)
    app.register_blueprint(quiz_bp)
    app.register_blueprint(review_bp)
    app.register_blueprint(progress_bp)
    app.register_blueprint(report_bp)
