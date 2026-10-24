import os, tempfile
from pathlib import Path
_TMPDIR = tempfile.mkdtemp(prefix='smtest_')
os.environ['DATABASE_URL'] = f'sqlite+aiosqlite:///{Path(_TMPDIR)/"test.db"}'
from app.core.config import reset_settings
reset_settings()
from app.db.session import SessionFactory, engine

