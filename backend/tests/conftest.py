import os, tempfile
from pathlib import Path
_TMPDIR = tempfile.mkdtemp(prefix='smtest_')
os.environ['DATABASE_URL'] = f'sqlite+aiosqlite:///{Path(_TMPDIR)/"test.db"}'
os.environ['STOCKOS_RATE_LIMIT_DEFAULT_PER_MINUTE'] = '100000'
os.environ['STOCKOS_RATE_LIMIT_AUTH_PER_MINUTE'] = '100000'
from app.core.config import reset_settings
reset_settings()
from app.db.session import SessionFactory, engine

