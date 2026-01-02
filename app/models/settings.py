from app.models import db
from datetime import datetime


class Setting(db.Model):
    """Configuration settings stored in database."""

    __tablename__ = 'settings'

    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(100), unique=True, nullable=False, index=True)
    value = db.Column(db.Text, nullable=True)
    description = db.Column(db.String(255), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f'<Setting {self.key}={self.value}>'

    @staticmethod
    def get(key, default=None):
        """Get a setting value by key."""
        setting = Setting.query.filter_by(key=key).first()
        return setting.value if setting else default

    @staticmethod
    def set(key, value, description=None):
        """Set a setting value by key."""
        setting = Setting.query.filter_by(key=key).first()
        if setting:
            setting.value = value
            setting.updated_at = datetime.utcnow()
            if description:
                setting.description = description
        else:
            setting = Setting(key=key, value=value, description=description)
            db.session.add(setting)
        db.session.commit()
        return setting

    @staticmethod
    def delete(key):
        """Delete a setting by key."""
        setting = Setting.query.filter_by(key=key).first()
        if setting:
            db.session.delete(setting)
            db.session.commit()
            return True
        return False

    @staticmethod
    def is_configured():
        """Check if the application has been configured."""
        calibre_library = Setting.get('calibre_library_path')
        calibredb_path = Setting.get('calibredb_path')
        return bool(calibre_library and calibredb_path)
